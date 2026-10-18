"""Bounded structured-decision repair data. Never persist model text or private inputs."""
import json
from pydantic import BaseModel, ValidationError
from langchain_core.exceptions import OutputParserException


class DecisionFormatError(ValueError):
    pass


def parse_decision(response, schema):
    if isinstance(response, dict) and {'raw', 'parsed', 'parsing_error'} <= response.keys():
        # include_raw preserves parser errors for diagnostics and one repair.
        error = response['parsing_error']
        if error is not None:
            if isinstance(error, (ValueError, OutputParserException)):
                raise error
            raise DecisionFormatError('模型没有返回合法的结构化动作')
        raw = response['raw']
        calls = getattr(raw, 'tool_calls', []) or []
        if len(calls) != 1 or calls[0].get('name') != schema.__name__:
            raise DecisionFormatError('一次只能返回一个 MainDecision 动作')
        if response['parsed'] is None:
            raise DecisionFormatError('模型没有返回可解析的动作')
        response = response['parsed']
    return schema.model_validate(response)


def contract_issues(exc, stage):
    """Paths/types and safe messages, without Pydantic's input or parser's raw text."""
    if isinstance(exc, ValidationError):
        return [{'path': '.'.join(str(p)[:60] for p in item['loc']) or '$',
                 'type': item['type'], 'message': item['msg'][:500]}
                for item in exc.errors(include_input=False, include_url=False)[:8]]
    message = ('结构化 JSON 或动作字段无法解析' if isinstance(exc, OutputParserException)
               else str(exc)[:500] if stage != 'parse' or isinstance(exc, DecisionFormatError)
               else '模型没有返回合法的结构化动作')
    return [{'path': stage, 'type': type(exc).__name__, 'message': message}]


def rejected_controls(response):
    """Feed the rejected controls back to the same model; do not repeat a long answer."""
    if isinstance(response, dict) and 'raw' in response:
        calls = getattr(response['raw'], 'tool_calls', []) or []
        response = calls[0].get('args') if len(calls) == 1 else response.get('parsed')
    if isinstance(response, BaseModel):
        response = response.model_dump()
    if not isinstance(response, dict):
        return None
    def bound(value, depth=0):
        if depth > 8:
            return '[超出修正上下文的嵌套限制]'
        if isinstance(value, dict):
            return {str(k): bound(v, depth + 1) for k, v in list(value.items())[:32]
                    if k not in ('reply', 'user_reply', 'result')}
        if isinstance(value, list):
            return [bound(v, depth + 1) for v in value[:80]]
        return value[:1000] if isinstance(value, str) else value
    controls = bound(response)
    if len(json.dumps(controls, ensure_ascii=False)) > 16000:
        return {'action': response.get('action'), 'notice': '控制字段过长，按具体错误和合法编号重建动作。'}
    return controls


def repair_data(state, response, issues):
    successful = {tid: {'citation_ids': [str(c['id']) for c in result.get('citations', [])]}
                  for tid, result in (state.get('task_results') or {}).items()
                  if result.get('status') == 'succeeded'}
    return {'kind': 'decision_contract_repair', 'errors': issues,
            'rejected_controls': rejected_controls(response), 'successful_tasks': successful,
            'reusable_previous_task_ids': list((state.get('previous_run') or {}).get('reusable_results', {}))}
