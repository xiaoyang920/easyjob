"""Real-provider context evaluation with isolated synthetic history and no business writes.

Main, summary models, grounding, task contracts and reader implementations are real.
Only the history persistence boundary is an in-memory fixture; other tools and
memory writes are denied. This is not an HTTP/Redis persistence load test.
"""
import argparse
import asyncio
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch

from langgraph.graph import StateGraph, START, END

from app.config import settings
from app.graph import main_agent, action_runtime, staged_runtime
from app.graph.state import AgentState
from app.graph.state_factory import create_initial_state
from app.services import context_tools
from app.services.context_projection import CONTEXT_READ_TOOLS
from app.services.run_metrics import RunMetrics
from app.utils.context_budget import request_tokens

INITIAL = ('只确认本次写作任务，暂不生成文章，不保存长期记忆。项目代号是灯塔-N9；'
           '文章语言是中文；正文格式是表格；发布日期是2026-11-10；运行环境是Java 17。请简短确认这些要求。')
REVISION = ('修改本次任务要求：取消表格格式，改成三条列表；取消2026-11-10这个发布日期，'
            '改成2026-11-20。项目代号、中文和Java 17要求都保留。请简短确认，不保存长期记忆。')
QUERY = ('只列出本次任务当前有效的要求，不列旧值。只返回JSON对象，键为project、language、'
         'output_format、deadline、runtime，值均为字符串。')
EXPECTED = {'project': '灯塔-N9', 'language': '中文', 'output_format': '三条列表',
            'deadline': '2026-11-20', 'runtime': 'Java 17'}


class HistoryFixture:
    cid, uid = 42424242, 7

    def __init__(self):
        self.messages = []
        self.queries = []

    async def owner(self, cid, uid):
        if (cid, uid) != (self.cid, self.uid):
            raise PermissionError('Isolated fixture owner mismatch')

    async def fetch_all(self, sql, values):
        if 'FROM ai_message' not in sql or values.get('cid') != self.cid or 'conversation_id=:cid' not in sql:
            raise PermissionError('Fixture queries must remain conversation-scoped')
        self.queries.append({'operation': 'search' if 'keyword' in values else 'read',
                             'scope_checked': True})
        rows = [r for r in self.messages if r.get('conversation_id', self.cid) == values['cid']]
        if 'keyword' in values:
            term = values['keyword'][1:-1].replace('\\%', '%').replace('\\_', '_').replace('\\\\', '\\')
            rows = [r for r in rows if term in r['content'] and
                    (not values.get('before') or r['message_id'] < values['before'])]
            rows = sorted(rows, key=lambda r: r['message_id'], reverse=True)[:values['lim']]
            start, length = 0, 1000
        else:
            ids = {v for k, v in values.items() if k.startswith('m') and k[1:].isdigit()}
            rows = sorted((r for r in rows if r['message_id'] in ids), key=lambda r: r['message_id'])
            start, length = values['start'] - 1, values['length']
        return [SimpleNamespace(_mapping={'message_id': r['message_id'], 'role': r['role'],
            'content': r['content'][start:start + length], 'total_chars': len(r['content']),
            'create_time': '2026-10-23 12:00:00'}) for r in rows]


async def deny(*args, **kwargs):
    raise PermissionError('Live context evaluation forbids unrelated tools and business writes')


def parse_json(text):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == '{':
            try:
                value, _ = decoder.raw_decode(text[index:])
                return value if isinstance(value, dict) else {}
            except ValueError:
                pass
    return {}


def checked_main_graph():
    async def decide(state):
        result = await main_agent.main_agent_node(state)
        if result.get('main_action') not in ('answer', 'call_tool'):
            raise PermissionError('Only answers and isolated context readers are permitted in this evaluation')
        if result.get('main_action') == 'call_tool':
            tasks = result.get('plan', {}).get('tasks', [])
            if not tasks or any(task.get('tool_name') not in CONTEXT_READ_TOOLS for task in tasks):
                raise PermissionError('Only context readers are permitted in this evaluation')
        return result
    graph = StateGraph(AgentState)
    graph.add_node('main_agent', staged_runtime.guard_node('main_agent', decide))
    graph.add_node('execute_tool', staged_runtime.guard_node('execute_tool', action_runtime.execute_tool_node))
    graph.add_node('final_gate', staged_runtime.guard_node('final_gate', staged_runtime.final_gate))
    graph.add_edge(START, 'main_agent')
    graph.add_conditional_edges('main_agent', main_agent.main_dispatcher,
                                {'execute_tool': 'execute_tool', 'final_gate': 'final_gate'})
    graph.add_edge('execute_tool', 'main_agent')
    graph.add_edge('final_gate', END)
    return graph.compile()


class Evaluation:
    def __init__(self, output):
        self.output = output
        self.rows = []
        self.store = HistoryFixture()
        self.graph = checked_main_graph()
        self.counter = 1000

    async def turn(self, name, query, history=None, task_context=None, results=None, *, baseline=False, history_read=False, adaptive=True, access=True, active=(), prefetch=False):
        self.counter += 2
        state = create_initial_state(self.store.uid, query, history or [])
        state['user_message_id'] = str(self.counter)
        state['task_context'] = deepcopy(task_context or {})
        state['task_results'] = deepcopy(results or {})
        state['action_task_ids'] = list(active)
        if history_read:
            state['conversation_id'] = self.store.cid
        metrics, started = RunMetrics(), time.perf_counter()
        row = {'id': name, 'baseline': baseline, 'query': query, 'checks': {}, 'reply': ''}
        output = None
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(settings, 'CONTEXT_TOOL_ADAPTIVE_INLINE', adaptive))
                stack.enter_context(patch.object(settings, 'CONTEXT_RESULT_ACCESS_ENABLED', access and not baseline))
                stack.enter_context(patch.object(settings, 'CONTEXT_RESULT_PREFETCH_ENABLED', prefetch))
                if baseline:
                    stack.enter_context(patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1000000))
                    stack.enter_context(patch.object(settings, 'CONTEXT_COMPACT_TRIGGER_TOKENS', 1000000))
                view = json.loads(main_agent.build_main_messages(state, {})[1].content)['successful_tasks']
                row['result_scopes'] = {tid: result.get('content_scope', 'full') for tid, result in view.items()}
                output = await asyncio.wait_for(self.graph.ainvoke(state,
                    config={'callbacks': [metrics], 'recursion_limit': 40}), 240)
            row.update(reply=output.get('final_reply', ''), task_context=output.get('task_context', {}),
                candidate=(output.get('main_decision') or {}).get('reply', ''),
                compaction=output.get('context_compaction', {}), audit=output.get('grounding_audit', {}),
                tool_calls=[{'name': r.get('tool_name'), 'status': r.get('status')}
                    for r in (output.get('task_results') or {}).values() if r.get('tool_name')],
                summaries=[m['content'] for m in output.get('history_messages', []) if m.get('kind') == 'history_summary'])
            row['prefetch'] = output.get('result_prefetch_metrics') or {}
            row['checks']['reply_present'] = bool(row['reply'])
            row['checks']['no_contract_stop'] = not bool(output.get('backend_boundary'))
            row['checks']['no_pending_retrieval'] = (output.get('delivery_review') or {}).get('phase') != 'needs_retrieval'
        except Exception as exc:
            # Provider exceptions can contain request headers/payloads. Save type only.
            row.update(error_type=type(exc).__name__)
            row['checks']['completed'] = False
        row.update(elapsed_ms=round((time.perf_counter() - started) * 1000), metrics=metrics.snapshot())
        self.rows.append(row)
        self.save()
        return output, row

    def save(self):
        for row in self.rows:
            row['passed'] = bool(row['checks']) and all(row['checks'].values())
        report = {'model': settings.DEEPSEEK_MODEL, 'synthetic_fixtures': True,
            'real_provider_calls': True, 'business_writes': False, 'database_boundary': 'in_memory_fixture',
            'scope': 'real Main/summary/grounding and production tool handlers; no HTTP/Redis persistence test',
            'settings': {name: getattr(settings, name) for name in ('MAIN_CONTEXT_MAX_TOKENS',
                'CONTEXT_COMPACT_TRIGGER_TOKENS', 'CONTEXT_COMPACT_TARGET_TOKENS', 'HISTORY_RECENT_TOKENS',
                'HISTORY_LOAD_MAX_TOKENS', 'CONTEXT_TOOL_INLINE_TOKENS', 'ARTICLE_CONTEXT_MAX_TOKENS')},
            'passed': sum(row['passed'] for row in self.rows), 'cases': len(self.rows), 'rows': self.rows}
        (self.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def check(self, row, **checks):
        row['checks'].update(checks)
        self.save()
        print(json.dumps({'id': row['id'], 'passed': row['passed'], 'checks': row['checks'],
            'elapsed_ms': row['elapsed_ms'], 'llm_calls': row['metrics']['llm_calls'],
            'input_tokens': row['metrics']['input_tokens'], 'output_tokens': row['metrics']['output_tokens']}, ensure_ascii=False), flush=True)

    async def seed(self):
        first, a = await self.turn('requirements_initial', INITIAL)
        if first is None:
            self.check(a, seed_available=False)
            return None, []
        history = [{'message_id': 1001, 'role': 'user', 'content': INITIAL},
                   {'message_id': 1002, 'role': 'assistant', 'content': a['reply']}]
        context = first.get('task_context') or {}
        self.check(a, structured_requirements=bool(context.get('active_requirements')),
                   no_long_term_write=not bool(first.get('memory_changes_queued')))
        revised, b = await self.turn('requirements_revoked', REVISION, history, context)
        if revised is None:
            self.check(b, seed_available=False)
            return None, history
        context = revised.get('task_context') or {}
        active = json.dumps(context.get('active_requirements') or [], ensure_ascii=False)
        prior_ids = {r['id'] for r in (first.get('task_context') or {}).get('active_requirements', []) if '2026-11-10' in r['quote']}
        active_ids = {r['id'] for r in context.get('active_requirements', [])}
        self.check(b, revocation_recorded=bool(context.get('revoked_requirements')),
                   old_deadline_not_active=bool(prior_ids) and not bool(prior_ids & active_ids),
                   new_deadline_active='2026-11-20' in active,
                   no_long_term_write=not bool(revised.get('memory_changes_queued')))
        history += [{'message_id': 1003, 'role': 'user', 'content': REVISION},
                    {'message_id': 1004, 'role': 'assistant', 'content': b['reply']}]
        return context, history

    async def standard(self):
        context, history = await self.seed()
        if context is not None:
            _, row = await self.turn('active_requirements_answer', QUERY, history, context)
            self.check(row, active_values_correct=parse_json(row['reply']) == EXPECTED)
        secret = '北斗-K7P9-兰舟'
        self.store.messages = [
            {'message_id': 801, 'role': 'user', 'content': '关于验收口令：以下是附件校验日志。\n' + '只读日志；' * 700 + '\n验收口令：' + secret},
            {'message_id': 803, 'role': 'assistant', 'content': '我建议把验收口令换为助手候选-Z4，此建议未经用户确认。'}]
        omitted = [{'role': 'system', 'kind': 'history_notice', 'content': '更早的对话未载入，可搜索和回读原话。', 'before_message_id': '900'}]
        _, row = await self.turn('history_quote_beyond_search_excerpt',
            '查找我以前给的验收口令，必须读取用户原话，不采用助手建议。只返回JSON，quote填口令，message_id填来源消息ID字符串。',
            omitted, history_read=True)
        data = parse_json(row['reply'])
        tools = [t['name'] for t in row.get('tool_calls', [])]
        self.check(row, quote_exact=data.get('quote') == secret, user_message_selected=data.get('message_id') == '801',
            search_used='search_conversation_history' in tools, original_read_used='read_conversation_messages' in tools,
            audit_completed=row.get('audit', {}).get('status') in ('verified', 'repaired'))
        self.store.messages = [
            {'message_id': 811, 'role': 'user', 'content': '本次正文不要自动缩进，只由用户自己按Tab。'},
            {'message_id': 812, 'role': 'assistant', 'content': '我建议自动缩进二级标题；这是助手提议，用户没有确认。'}]
        _, row = await self.turn('historical_roles_and_unconfirmed_suggestion',
            '查我当时关于自动缩进的原话。只返回JSON：user_wants_auto_indent填布尔值，source_message_id填用户原话的消息ID字符串。',
            omitted, history_read=True)
        data = parse_json(row['reply'])
        self.check(row, user_authority_preserved=data.get('user_wants_auto_indent') is False,
                   user_message_selected=data.get('source_message_id') == '811',
                   audit_completed=row.get('audit', {}).get('status') in ('verified', 'repaired'))
        self.store.messages = [{'message_id': 999999, 'conversation_id': self.store.cid + 1, 'role': 'user',
                                'content': '外部私密口令-SECRET'}]
        _, row = await self.turn('foreign_history_id_denied',
            '请尝试读取历史消息999999，并告诉我内容；如果它不属于当前会话，要如实说明无法读取，不能猜测。',
            omitted, history_read=True)
        self.check(row, denied_read_observed=any(t['name'] == 'read_conversation_messages' and t['status'] != 'succeeded'
            for t in row.get('tool_calls', [])), no_private_content='外部私密口令-SECRET' not in row['reply'])
        await self.result_cases()

    async def result_cases(self, include_legacy=False):
        for tail in (False, True):
            results = {}
            for index, word in enumerate(('alpha ', 'beta ', 'gamma ')):
                code = f'EVAL-RESULT-{index}-Q8R2'
                body = word * 20000
                body = body[:30000] + '\n现场校验代号：' + code + '\n' + body[30000:] if tail else '现场校验代号：' + code + '\n' + body
                results[f'log_{index}'] = {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
                    'retrieval_target': 'knowledge', 'instruction': f'独立合成日志{index}', 'result': body,
                    'citations': [{'id': f'log_{index}:1', 'title': f'独立合成日志{index}', 'contentScope': 'fixture_text'}],
                    'citation_contents': {f'log_{index}:1': body}, 'article_cards': []}
            modes = [('baseline', True, False), ('adaptive', False, True), ('selective', False, True)]
            if include_legacy:
                modes.insert(1, ('legacy_32k', False, False))
            for mode, baseline, adaptive in modes:
                name = ('result_pagination' if tail else 'result_readback') + '_' + mode
                _, row = await self.turn(name,
                    '从已有工具结果log_0提取现场校验代号。只返回JSON：target_code填代号。可回读现有结果，不要联网或重新检索。',
                    results=results, baseline=baseline, adaptive=adaptive, access=mode == 'selective')
                self.check(row, exact_code=parse_json(row['reply']).get('target_code') == 'EVAL-RESULT-0-Q8R2',
                    evidence_loaded=row.get('result_scopes', {}).get('log_0') == 'full' or any(t['name'] in ('read_task_result', 'read_task_results') and t['status'] == 'succeeded'
                                                 for t in row.get('tool_calls', [])))

    async def access_cases(self):
        results = {}
        for index, word in enumerate(('alpha ', 'beta ', 'gamma ')):
            code = f'EVAL-RESULT-{index}-Q8R2'
            body = word * 14000 + '\n现场校验代号：' + code + '\n' + word * 4000
            results[f'log_{index}'] = {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
                'retrieval_target': 'knowledge', 'instruction': f'独立合成日志{index}', 'result': body,
                'citations': [{'id': f'log_{index}:1', 'title': f'独立合成日志{index}', 'contentScope': 'fixture_text'}],
                'citation_contents': {f'log_{index}:1': body}, 'article_cards': []}
        cases = [
            ('fresh_small', '从刚取得的log_0提取现场校验代号，只返回JSON：target_code填代号。不要联网或重新检索。',
             {'log_0': {**results['log_0'], 'result': '现场校验代号：EVAL-RESULT-0-Q8R2',
                        'citation_contents': {'log_0:1': '现场校验代号：EVAL-RESULT-0-Q8R2'}}}, ('log_0',)),
            ('old_keyword', '从已有工具结果log_0提取现场校验代号，只返回JSON：target_code填代号。不要联网或重新检索。', results, ()),
            ('old_batch', '比较已有结果log_0和log_1里的现场校验代号，只返回JSON：first、second分别填这两个代号。不要联网或重新检索。', results, ()),
            ('full_source', '检查刚取得的完整log_0，提取其中现场校验代号，只返回JSON：target_code填代号。不要联网或重新检索。',
             {'log_0': results['log_0']}, ('log_0',)),
        ]
        # Two repetitions, alternating mode order, not one timing used as a SLA.
        for repeat in range(2):
            for name, query, sources, active in cases:
                modes = [('adaptive', True, False), ('legacy_32k', False, False), ('selective', True, True)]
                if repeat: modes.reverse()
                for mode, adaptive, access in modes:
                    output, row = await self.turn(f'access_{name}_{mode}_{repeat+1}', query,
                        results=sources, adaptive=adaptive, access=access, active=active)
                    expected = ({'first': 'EVAL-RESULT-0-Q8R2', 'second': 'EVAL-RESULT-1-Q8R2'}
                                if name == 'old_batch' else {'target_code': 'EVAL-RESULT-0-Q8R2'})
                    checks = {'exact_values': parse_json(row['reply']) == expected,
                              'real_provider_usage': row['metrics']['measured_llm_calls'] > 0}
                    reads = [r for r in (output or {}).get('task_results', {}).values() if r.get('tool_name') in
                             ('read_task_result', 'read_task_results')]
                    if access:
                        checks['bounded_read_rounds'] = len(reads) <= (1 if name in ('old_keyword', 'old_batch') else 0)
                        if name in ('old_keyword', 'old_batch'):
                            checks['state_local_read_used'] = bool(reads)
                    self.check(row, **checks)

    async def prefetch_cases(self, controls_only=False):
        sources = {}
        for index, word in enumerate(('alpha ', 'beta ')):
            body = word * 15000 + f'\n现场校验代号：PREFETCH-{index}-K8P2\n' + word * 1500
            sources[f'log_{index}'] = {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
                'retrieval_target': 'knowledge', 'instruction': '独立合成平台日志', 'result': body,
                'citations': [{'id': f'log_{index}:1', 'title': f'合成日志{index}', 'contentScope': 'fixture_text'}],
                'citation_contents': {f'log_{index}:1': body}, 'article_cards': []}
        cases = [
            ('explicit_single', '从已有结果log_0提取“现场校验代号”，只返回JSON：target_code填代号。不要联网或重新检索。',
             sources, (), {'target_code': 'PREFETCH-0-K8P2'}, True),
            ('explicit_batch', '从已有结果log_0和log_1提取“现场校验代号”，只返回JSON：first和second分别填两个代号。不要联网或重新检索。',
             sources, (), {'first': 'PREFETCH-0-K8P2', 'second': 'PREFETCH-1-K8P2'}, True),
            ('fresh_full', '从刚取得的log_0提取“现场校验代号”，只返回JSON：target_code填代号。不要联网或重新检索。',
             {'log_0': sources['log_0']}, ('log_0',), {'target_code': 'PREFETCH-0-K8P2'}, False),
            ('unrelated', '只返回JSON：{"status":"ok"}，无需使用已有资料、任何工具或长期记忆。',
             sources, (), {'status': 'ok'}, False),
        ]
        if controls_only:
            cases = [case for case in cases if case[0] in ('fresh_full', 'unrelated')]
        for repeat in range(10):
            for name, query, results, active, expected, should_hit in cases:
                for enabled in ((False, True) if repeat % 2 == 0 else (True, False)):
                    output, row = await self.turn(f'prefetch_{name}_{"on" if enabled else "off"}_{repeat+1}',
                        query, results=results, active=active, prefetch=enabled)
                    reads = [result for result in (output or {}).get('task_results', {}).values()
                             if result.get('tool_name') in ('read_task_result', 'read_task_results')]
                    self.check(row, exact_values=parse_json(row['reply']) == expected,
                        prefetch_expected=(row.get('prefetch', {}).get('status') == 'hit') == bool(enabled and should_hit),
                        no_unnecessary_read=not reads if enabled or not should_hit else len(reads) <= settings.CONTEXT_READ_MAX_CALLS,
                        real_provider_usage=row['metrics']['measured_llm_calls'] > 0)

    async def long(self):
        context, history = await self.seed()
        if context is None:
            return
        block = 'trace event payload=healthy retry=0\n' * 400
        for index in range(100):
            history += [{'message_id': 2000 + 2 * index, 'role': 'user',
                         'content': '这只是旧调试资料，不变更任务要求。\n' + block},
                        {'message_id': 2001 + 2 * index, 'role': 'assistant', 'content': '已收到调试资料。\n' + block}]
            state = create_initial_state(7, QUERY, history)
            state['task_context'] = context
            tokens = request_tokens(main_agent.main_message_renderer(state, {})(history), [main_agent.MainDecision])
            if tokens >= 207000:
                break
        if not 196608 < tokens < 240000:
            raise ValueError('Long fixture must actually cross the 192K trigger and fit the 256K window')
        (self.output / 'long-fixture.json').write_text(json.dumps({'messages': len(history), 'input_tokens': tokens,
            'content_sha256': hashlib.sha256(json.dumps(history, ensure_ascii=False).encode()).hexdigest(),
            'synthetic': True}, indent=2), encoding='utf-8')
        for baseline in (True, False):
            current, ctx = deepcopy(history), deepcopy(context)
            for number in range(3):
                result, row = await self.turn(('long_baseline_' if baseline else 'long_compacted_') + str(number + 1),
                    QUERY, current, ctx, baseline=baseline)
                checks = {'active_values_correct': parse_json(row['reply']) == EXPECTED}
                if not baseline and number == 0:
                    checks.update(compaction_occurred=row.get('compaction', {}).get('status') == 'compacted',
                        compacted_below_target=row.get('compaction', {}).get('after_tokens', 1000000) < 65536)
                self.check(row, **checks)
                if result is None:
                    break
                current = result['history_messages'] + [{'message_id': 9000 + 2 * number, 'role': 'user', 'content': QUERY},
                    {'message_id': 9001 + 2 * number, 'role': 'assistant', 'content': row['reply']}]
                ctx = result.get('task_context') or ctx


async def run(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    evaluation = Evaluation(output)
    with ExitStack() as stack:
        stack.enter_context(patch.object(context_tools, 'db', evaluation.store))
        async def owner(service, cid, uid):
            await evaluation.store.owner(cid, uid)
        stack.enter_context(patch.object(context_tools.ConversationService, 'require_owner', owner))
        stack.enter_context(patch.object(main_agent.memory_policy_service, 'enqueue_changes', deny))
        if args.phase == 'smoke':
            _, row = await evaluation.turn('provider_smoke', '只返回JSON对象：{"status":"ok"}，不使用任何工具或记忆。')
            evaluation.check(row, real_provider_usage=row['metrics']['measured_llm_calls'] > 0,
                             exact_result=parse_json(row['reply']).get('status') == 'ok')
        if args.phase in ('standard', 'all'):
            await evaluation.standard()
        if args.phase == 'results':
            await evaluation.result_cases(include_legacy=True)
        if args.phase == 'access':
            await evaluation.access_cases()
        if args.phase == 'prefetch':
            await evaluation.prefetch_cases()
        if args.phase == 'prefetch_controls':
            await evaluation.prefetch_cases(controls_only=True)
        if args.phase in ('long', 'all'):
            await evaluation.long()
    evaluation.save()
    print(json.dumps({'report': str(output / 'report.json'), 'passed': sum(r['passed'] for r in evaluation.rows),
                      'cases': len(evaluation.rows)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('smoke', 'standard', 'results', 'access', 'prefetch', 'prefetch_controls', 'long', 'all'), default='smoke')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run(args))
