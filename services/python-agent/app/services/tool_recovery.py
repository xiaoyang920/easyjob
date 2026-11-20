"""Read-only tool validation and bounded repair; permissions never come from the model."""
import asyncio
from dataclasses import dataclass
import json

import httpx
from fastapi import HTTPException
from jsonschema import validators
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError


@dataclass(frozen=True)
class ToolPolicy:
    read_only: bool
    capability: str = 'platform_read'


class ToolTaskError(RuntimeError):
    """A safe, recoverable task failure. Raw provider exceptions are not public data."""
    def __init__(self, code, message, *, tool='', repair_attempts=0):
        super().__init__(message)
        self.report = {'code': code, 'message': message, 'tool': tool, 'repair_attempts': repair_attempts}


class ToolInputError(ValueError):
    """Explicit safe input error raised by a tool before any business operation."""
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def _local_refs_only(value):
    if isinstance(value, dict):
        for key in ('$ref', '$dynamicRef', '$recursiveRef'):
            if key in value and (not isinstance(value[key], str) or not value[key].startswith('#')):
                raise ValueError('工具参数 Schema 不允许自动读取外部引用')
        for child in value.values():
            _local_refs_only(child)
    elif isinstance(value, list):
        for child in value:
            _local_refs_only(child)


def argument_issues(tool, args):
    if not isinstance(args, dict):
        return [{'field': '$', 'message': '参数必须是 JSON 对象'}]
    # Check before conversion too: converters may otherwise resolve or reject
    # external references before our validator sees the schema.
    if isinstance(tool.args_schema, dict):
        _local_refs_only(tool.args_schema)
    schema = convert_to_openai_tool(tool)['function']['parameters']
    _local_refs_only(schema)
    schema = {**schema, 'additionalProperties': schema.get('additionalProperties', False)}
    validator = validators.validator_for(schema)
    validator.check_schema(schema)
    issues = []
    for error in validator(schema).iter_errors(args):
        # JSON Schema's normal error message can contain the rejected value.
        path = '.'.join(str(p) for p in error.absolute_path) or '$'
        if error.validator == 'required':
            missing = [name for name in error.validator_value if name not in error.instance]
            issues.extend({'field': name, 'message': '缺少必填参数'} for name in missing)
        else:
            expected = {'type': f'参数类型应为 {error.validator_value}', 'additionalProperties': '包含未声明的参数',
                        'minLength': '参数文本过短', 'maxLength': '参数文本过长',
                        'minimum': '参数小于允许下限', 'maximum': '参数超过允许上限',
                        'enum': '参数值不在允许范围', 'pattern': '参数格式不符合要求'}.get(error.validator, '参数不符合 Schema')
            issues.append({'field': path, 'message': expected})
        if len(issues) >= 8:
            break
    if tool.name in ('web_search', 'search_articles', 'search_articles_by_knn'):
        query = args.get('query')
        if isinstance(query, str) and not query.strip():
            issues.append({'field': 'query', 'message': '搜索词不能为空'})
        if tool.name == 'web_search' and isinstance(query, str) and len(query.strip()) > 128:
            issues.append({'field': 'query', 'message': '搜索词不能超过128个字符，请保留筛选条件并精简'})
    return issues[:8]


def error_message(call, code, issues, available):
    return ToolMessage(tool_call_id=call['id'], name=call['name'], status='error',
        content=json.dumps({'ok': False, 'error': {'code': code, 'fields': issues,
            'available_tools': available}, 'instruction': '仅修正失败的只读调用；成功结果已保留，不扩大权限。'}, ensure_ascii=False))


def success_text(result, limit=3000):
    if isinstance(result, ToolMessage):
        if result.status == 'error':
            raise ToolTaskError('TOOL_REPORTED_ERROR', '工具返回失败状态，未将其当作成功结果')
        result = result.content
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + '\n...[结果已截断]'


async def invoke_read_only(tool, call, config, timeout):
    try:
        # Full ToolCall preserves IDs for tools using InjectedToolCallId.
        return success_text(await asyncio.wait_for(tool.ainvoke(
            {'type': 'tool_call', 'name': call['name'], 'args': call['args'], 'id': call['id']}, config=config), timeout))
    except (PermissionError, HTTPException, ToolInputError, ValidationError):
        raise
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise PermissionError('工具服务拒绝访问，禁止自动修正权限') from None
        raise ToolTaskError('TOOL_HTTP_ERROR', '工具服务请求失败', tool=tool.name) from None
    except (TimeoutError, httpx.RequestError, ConnectionError) as exc:
        if getattr(exc, 'status_code', None) in (401, 403):
            raise PermissionError('工具服务拒绝访问，禁止自动修正权限') from None
        raise ToolTaskError('TOOL_UNAVAILABLE', '工具连接失败或超时', tool=tool.name) from None
    except ToolException:
        raise ToolTaskError('TOOL_EXECUTION_FAILED', '工具执行未完成', tool=tool.name) from None
