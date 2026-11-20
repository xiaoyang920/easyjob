"""Bounded structured-decision repair data. Never persist model text or private inputs."""
import json
from pydantic import BaseModel, ValidationError
from langchain_core.exceptions import OutputParserException


class DecisionFormatError(ValueError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def parse_decision(response, schema, *, json_mode=False):
    if json_mode:
        raw = response['raw']
        content = getattr(raw, 'content', None)
        finish_reason = (getattr(raw, 'response_metadata', None) or {}).get('finish_reason')
        if (not isinstance(content, str) or not content.strip() or finish_reason not in (None, 'stop')
                or getattr(raw, 'tool_calls', None) or getattr(raw, 'invalid_tool_calls', None)):
            raise DecisionFormatError('invalid_json_response', '模型没有返回完整的 JSON 动作')
        # Validate the original content. The SDK's JSON parser can complete partial objects.
        return schema.model_validate_json(content)

    if isinstance(response, dict) and {'raw', 'parsed', 'parsing_error'} <= response.keys():
        # include_raw preserves parser errors for diagnostics and one repair.
        error = response['parsing_error']
        if error is not None:
            if isinstance(error, (ValueError, OutputParserException)):
                raise error
            raise DecisionFormatError('parser_error', '模型没有返回合法的结构化动作')
        raw = response['raw']
        calls = getattr(raw, 'tool_calls', []) or []
        if len(calls) != 1 or calls[0].get('name') != schema.__name__:
            reason = 'wrong_tool_name' if len(calls) == 1 else 'unexpected_tool_call_count'
            raise DecisionFormatError(reason, '一次只能返回一个 MainDecision 动作')
        if response['parsed'] is None:
            raise DecisionFormatError('missing_parsed_decision', '模型没有返回可解析的动作')
        response = response['parsed']
    return schema.model_validate(response)


def decision_response_diagnostics(response, schema):
    """Describe the response envelope without logging content or tool arguments."""
    if not isinstance(response, dict) or 'raw' not in response:
        return {'has_raw_response': False}

    raw = response['raw']
    calls = getattr(raw, 'tool_calls', None) or []
    metadata = getattr(raw, 'response_metadata', None) or {}
    finish_reason = metadata.get('finish_reason')
    if finish_reason is not None and finish_reason not in (
        'stop', 'tool_calls', 'function_call', 'length', 'content_filter', 'insufficient_system_resource',
    ):
        finish_reason = 'unknown'
    usage = getattr(raw, 'usage_metadata', None) or {}
    output_details = usage.get('output_token_details') or {}
    token_usage = {
        'input_tokens': usage.get('input_tokens'),
        'output_tokens': usage.get('output_tokens'),
        'reasoning_tokens': output_details.get('reasoning'),
    }
    parser_error = response.get('parsing_error')
    return {
        'has_raw_response': raw is not None,
        'has_content': bool(getattr(raw, 'content', None)),
        'tool_calls': len(calls),
        'matching_tool_calls': sum(call.get('name') == schema.__name__ for call in calls),
        'invalid_tool_calls': len(getattr(raw, 'invalid_tool_calls', None) or []),
        'parsed': response.get('parsed') is not None,
        'parser_error': type(parser_error).__name__ if parser_error is not None else None,
        'finish_reason': finish_reason,
        **{key: value for key, value in token_usage.items() if type(value) is int},
    }


def contract_issues(exc, stage):
    """Paths/types and safe messages, without Pydantic's input or parser's raw text."""
    if isinstance(exc, ValidationError):
        return [{'path': '.'.join(str(p)[:60] for p in item['loc']) or '$',
                 'type': item['type'], 'message': item['msg'][:500],
                 **({'input_type': type(item.get('input')).__name__} if item['type'].endswith('_type') else {})}
                for item in exc.errors(include_url=False)[:8]]
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
                    if k not in ('reply', 'user_reply', 'result', 'progress_note')}
        if isinstance(value, list):
            return [bound(v, depth + 1) for v in value[:80]]
        return value[:1000] if isinstance(value, str) else value
    controls = bound(response)
    if len(json.dumps(controls, ensure_ascii=False)) > 16000:
        return {'action': response.get('action'), 'notice': '控制字段过长，按具体错误和合法编号重建动作。'}
    return controls


def rejection_snapshot(state, response, issues):
    """Precise control shapes and trusted ID relations, without model prose."""
    import hashlib
    if isinstance(response, dict) and 'raw' in response:
        calls = getattr(response['raw'], 'tool_calls', []) or []
        response = calls[0].get('args') if len(calls) == 1 else None
    if isinstance(response, BaseModel):
        response = response.model_dump()
    if not isinstance(response, dict):
        return {'response_type': type(response).__name__}
    previous = (state.get('previous_run') or {}).get('reusable_results', {})
    current = state.get('task_results') or {}
    citation_ids = {str(c['id']) for result in current.values() for c in result.get('citations', [])}
    def describe(value):
        result = {'type': type(value).__name__}
        if isinstance(value, (dict, list, str)):
            result['length'] = len(value)
        return result
    snapshot = {}
    fields = {issue.get('path', '').split('.')[0] for issue in issues}
    if '$' in fields:
        fields.update({'action', 'user_reply', 'artifacts', 'answer_dependencies', 'editor_edits',
                       'tool_call', 'draft_request', 'plan', 'delegation_reason'})
    for field in sorted(fields & {'artifacts', 'answer_dependencies', 'reuse_previous_results',
                                  'memory_changes', 'constraint_overrides', 'evidence_assessment',
                                  'action', 'user_reply', 'editor_edits', 'tool_call', 'draft_request',
                                  'plan', 'delegation_reason'}):
        if field not in response:
            snapshot[field] = {'present': False}
            continue
        value = response[field]
        entry = {'present': True, **describe(value)}
        if value is None:
            entry['value'] = None
        if field == 'action' and isinstance(value, str) and value in ('answer', 'call_tool', 'delegate', 'write_draft'):
            entry['value'] = value
        if field in ('reuse_previous_results', 'answer_dependencies') and isinstance(value, list):
            refs = []
            for item in value[:32]:
                relation = ('previous_reusable_task' if isinstance(item, str) and item in previous else
                    'current_successful_task' if isinstance(item, str) and current.get(item, {}).get('status') == 'succeeded' else
                    'current_failed_task' if isinstance(item, str) and item in current else
                    'citation_not_task' if isinstance(item, str) and item in citation_ids else 'unknown')
                # Unknown strings might contain prose. Keep only their type and
                # hash; exact IDs are retained only when present in trusted state.
                refs.append({'relation': relation, **({'id': item} if relation != 'unknown' else {
                    'type': type(item).__name__, 'hash': hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()})})
            entry['references'] = refs
            entry['allowed_previous_ids'] = sorted(previous)[:32]
        snapshot[field] = entry
    return snapshot


def repair_data(state, response, issues):
    successful = {tid: {'citation_ids': [str(c['id']) for c in result.get('citations', [])]}
                  for tid, result in (state.get('task_results') or {}).items()
                  if result.get('status') == 'succeeded'}
    assessment_rules = {
        'selected_ids_required_for_every_action': True,
        'none': {'selected_ids': 'empty', 'conflicts': 'empty'},
        'partial': {'selected_ids': 'nonempty', 'conflicts': 'only_selected_distinct_sources'},
        'sufficient': {'selected_ids': 'nonempty', 'missing_aspects': 'empty', 'conflicts': 'empty'},
        'missing_information': '若仍有预算且缺口可检索，选择call_tool进行有针对性的检索；格式修复不要求改成answer。',
    }
    return {'kind': 'decision_contract_repair', 'errors': issues,
            'rejected_controls': rejected_controls(response), 'successful_tasks': successful,
            'evidence_assessment_contract': assessment_rules,
            'reuse_contract': {'current_successful_task_ids': list(successful),
                'current_tasks_already_available': True,
                'empty_previous_list_means_no_import': True},
            'reusable_previous_task_ids': list((state.get('previous_run') or {}).get('reusable_results', {}))}
