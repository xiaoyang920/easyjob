"""Opt-in real-model repair of a synthetic read-only tool; no user/DB data."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from app.graph import tool_executor
from app.config import get_llm
from app.services.tool_recovery import ToolPolicy


async def main():
    model = get_llm()
    invoked, checks = [], {}
    live_calls = 0
    @tool
    async def lookup(query: str) -> str:
        """Look up a public synthetic fixture. query must be cache-aside."""
        invoked.append(query)
        return json.dumps({'receipt': 'fixture-ok', 'query': query})

    class InjectInvalidFirst:
        def __init__(self, delegate, inject=False):
            self.delegate, self.inject = delegate, inject
        def bind_tools(self, tools):
            return InjectInvalidFirst(self.delegate.bind_tools(tools), True)
        async def ainvoke(self, messages, **kwargs):
            nonlocal live_calls
            if self.inject:
                self.inject = False
                # Deterministically exercise the actual recovery code. All
                # subsequent decisions/summary are made by the configured model.
                return AIMessage(content='', tool_calls=[{'type': 'tool_call', 'name': 'lookup', 'args': {}, 'id': 'qa-invalid'}])
            live_calls += 1
            if live_calls == 1:
                feedback = messages[-1]
                checks['correlated_error_message'] = isinstance(feedback, ToolMessage) and feedback.status == 'error' and feedback.tool_call_id == 'qa-invalid'
            return await self.delegate.ainvoke(messages, **kwargs)

    started = perf_counter()
    with patch.object(tool_executor, 'get_llm', return_value=InjectInvalidFirst(model)), \
         patch.object(tool_executor, 'get_langfuse_callback', return_value=None):
        answer = await tool_executor.run_tool_agent(
            '你是只读工具调用验收助手。若收到参数错误，按 Schema 修正一次。只有工具返回后才能答复。',
            '调用 lookup，query 必须为 cache-aside。最终只返回工具结果里的 receipt 和 query，不需要解释。',
            [lookup], tool_policies={'lookup': ToolPolicy(True)}, timeout=90, tag='tool_repair_live_qa')
    checks['one_successful_tool_execution'] = invoked == ['cache-aside']
    checks['answer_uses_actual_tool_result'] = 'fixture-ok' in answer and 'cache-aside' in answer
    checks['bounded_model_calls'] = 2 <= live_calls <= 3
    report = {'checks': checks, 'actual_model_calls': live_calls,
              'successful_tool_calls': len(invoked), 'duration_ms': round((perf_counter() - started) * 1000)}
    path = ROOT / 'logs' / 'tool-recovery-smoke.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    assert all(checks.values()), 'Tool repair smoke failed; inspect report'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Allow real model requests using public synthetic data')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required; this consumes model quota')
    asyncio.run(main())
