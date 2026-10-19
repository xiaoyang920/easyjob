"""Approved, bounded model-only diagnosis on a frozen public-source plan.

No history, profiles, memory, attachments, retrieval execution or draft writes.
Both prompt variants use a strict schema without the runtime compatibility hook.
"""
import argparse
import ast
import asyncio
from copy import deepcopy
import hashlib
import json
import inspect
from pathlib import Path
import sys
import textwrap
from unittest.mock import patch

from pydantic import ConfigDict, create_model, model_validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.config import get_llm, settings
from app.graph import main_agent as agent
from app.graph.state_factory import create_initial_state
from app.services.decision_contract import parse_decision, contract_issues, repair_data
from langchain_core.messages import HumanMessage

PLAN = ROOT / 'logs/decision-contract-live-plan.json'
LEDGER = ROOT / 'logs/decision-contract-diagnosis-ledger.json'
REPORT = ROOT / 'logs/decision-contract-diagnosis.json'
OLD_EMPTY = '始终完整填写MainDecision所有字段，无值的字段也填写null、空列表或空字符串；用户正文user_reply必须最后输出，先确定动作、证据、依赖及记忆变更，再生成正文。不要为了流式显示而改变动作或省略应有的检索、记忆变更和引用。'
OLD_ORDER = '输出序列化顺序固定为：evidence_assessment → action → artifacts → answer_dependencies → reuse_previous_results → retrieval → draft_request → plan → delegation_reason → memory_changes → constraint_overrides → user_reply。先完整输出前11个控制字段（没有值也填null/[]/空字符串），最后才开始user_reply正文。该顺序不改变行动判断，需要检索或写记忆时照常填写实际请求。'


def strict_schema(prior=False):
    fields = {name: (field.annotation, deepcopy(field)) for name, field in agent.MainDecision.model_fields.items()}
    if prior:
        fields['artifacts'][1].description = None
        fields['reuse_previous_results'][1].description = '仅当前目标需要继续上次运行时，选择previous_run.reusable_results中经后端核验的任务ID。无关新问题保持空；选择后可在depends_on或answer_dependencies中引用。不恢复旧保存动作。'
    # Copy fields and the original action invariant, not the new before-validator.
    return create_model('MainDecision', __config__=ConfigDict(extra='forbid', populate_by_name=True),
        __validators__={'check_action': model_validator(mode='after')(agent.MainDecision.check_action)}, **fields)


def prior_prompt():
    lines = []
    for line in agent.MAIN_PROMPT.splitlines():
        if line.startswith('始终完整填写MainDecision所有字段。列表字段'):
            line = OLD_EMPTY
        elif line.startswith('successful_tasks是本轮已可使用的结果'):
            continue
        elif line.startswith('输出序列化顺序固定为：'):
            line = OLD_ORDER
        lines.append(line)
    return '\n'.join(lines) + '\n'


def correction_instructions(prior=False):
    # Read the production constant rather than approximating its repair prompt.
    tree = ast.parse(textwrap.dedent(inspect.getsource(agent.decide_main_action)))
    tails = [keyword.value.right.value for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'HumanMessage'
        for keyword in node.keywords if keyword.arg == 'content' and isinstance(keyword.value, ast.BinOp)
        and isinstance(keyword.value.right, ast.Constant) and isinstance(keyword.value.right.value, str)
        and '修正动作格式' in ast.unparse(keyword.value)]
    assert len(tails) == 1
    instructions = tails[0]
    if prior:
        for added in (
            'artifacts、answer_dependencies、reuse_previous_results、memory_changes、constraint_overrides都必须是列表，无值时填[]；artifacts不能用单个对象代替列表。',
            'successful_tasks中的结果已可直接用于任务依赖，不需导入。reuse_previous_results只能选reusable_previous_task_ids；该列表为空时必须填[]。'):
            assert added in instructions
            instructions = instructions.replace(added, '')
    return instructions


def frozen_state(plan):
    state = create_initial_state(1, plan['question'], [])
    citations = [{k: v for k, v in source.items() if k != 'content'} for source in plan['sources']]
    state.update(main_round=1, previous_run={'reusable_results': {}}, task_results={
        'retrieve_quanzhi_latest': {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
            'retrieval_target': 'knowledge', 'instruction': '检索《全职高手》的公开资料，供介绍文章使用，用户要求最新资料',
            'result': '\n\n'.join(f"[{s['id']}] {s['title']}\n{s['content']}" for s in plan['sources']),
            'citations': citations, 'citation_contents': {s['id']: s['content'] for s in plan['sources']},
            'article_cards': [], 'retrieval_report': {'assessment_owner': 'main',
                'platform': {'status': 'empty'}, 'web': {'status': 'found', 'provider': 'deepseek'}}}})
    return state


def shape(value):
    result = {'type': type(value).__name__}
    if isinstance(value, (str, list, dict)):
        result['length'] = len(value)
    if isinstance(value, dict):
        result['keys'] = list(value)
    return result


def controls(response):
    raw = response.get('raw') if isinstance(response, dict) else None
    calls = getattr(raw, 'tool_calls', []) or []
    args = calls[0].get('args') if len(calls) == 1 else None
    if not isinstance(args, dict):
        return {'tool_names': [c.get('name') for c in calls], 'args_shape': shape(args)}
    # Record the exact disputed controls; prose and artifact bodies are omitted.
    artifacts = args.get('artifacts')
    return {'tool_names': [c.get('name') for c in calls], 'action': args.get('action'),
        'artifacts_shape': shape(artifacts),
        'artifact_items': [{k: a[k] for k in ('task_id', 'depends_on') if k in a}
                           if isinstance(a, dict) else shape(a) for a in artifacts] if isinstance(artifacts, list) else None,
        'reuse_previous_results': args.get('reuse_previous_results'),
        'answer_dependencies': args.get('answer_dependencies'),
        'draft_dependencies': (args.get('draft_request') or {}).get('depends_on') if isinstance(args.get('draft_request'), dict) else None,
        'selected_ids': (args.get('evidence_assessment') or {}).get('selected_ids') if isinstance(args.get('evidence_assessment'), dict) else None}


def validate_strict(state, response, schema):
    stage = 'parse'
    try:
        decision = parse_decision(response, schema)
        stage = 'reuse_previous_results'
        selected = decision.reuse_previous_results
        previous = state['previous_run']['reusable_results']
        if len(selected) != len(set(selected)) or any(tid not in previous for tid in selected):
            raise agent.ActionContractError('只能选择previous_run中可复用的真实任务ID')
        stage = 'memory_changes'
        agent.validate_memory_changes(state, decision.memory_changes)
        stage = 'constraint_overrides'
        if decision.constraint_overrides:
            raise agent.ActionContractError('本次冻结上下文没有可覆盖约束')
        if decision.action == 'answer':
            stage = 'answer_dependencies'
            agent.answer_evidence(state, decision.answer_dependencies)
        stage = 'evidence_assessment'
        agent.validate_evidence_assessment(state, decision)
        stage = 'action_parameters'
        agent.preflight_action(state, decision, 2)
        return {'strict_valid': True, 'action': decision.action}, None
    except ValueError as error:
        return {'strict_valid': False, 'stage': stage, 'issues': contract_issues(error, stage)}, error


def consume_call(plan_hash, variant, attempt):
    ledger = json.loads(LEDGER.read_text(encoding='utf-8')) if LEDGER.exists() else {'plan_hash': plan_hash, 'calls': []}
    if ledger['plan_hash'] != plan_hash or len(ledger['calls']) >= 4:
        raise RuntimeError('Reviewed call allowance exhausted or plan changed')
    ledger['calls'].append({'variant': variant, 'attempt': attempt})
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')


async def diagnose(execute):
    assert execute, 'Use --execute-reviewed only after this exact plan is approved'
    assert not LEDGER.exists() and not REPORT.exists(), 'This reviewed diagnosis already ran; do not overwrite its evidence or repeat model calls'
    raw_plan = PLAN.read_bytes()
    plan_hash = hashlib.sha256(raw_plan).hexdigest()
    plan = json.loads(raw_plan)
    assert plan['max_model_calls'] == 4 and plan['model'] == settings.DEEPSEEK_MODEL
    assert plan['endpoint'] == settings.DEEPSEEK_BASE_URL
    assert plan['question'] == '帮我写一篇介绍全职高手的文章，要有最新的资料'
    assert {s['id'] for s in plan['sources']} == {f'retrieve_quanzhi_latest:web{i}' for i in range(6, 11)}
    report = {'plan_hash': plan_hash, 'model': plan['model'], 'calls': [],
        'historical_raw_response_available': False, 'comparison_is_new_sample': True}
    state = frozen_state(plan)
    for variant, prompt in [('prior', prior_prompt()), ('current', agent.MAIN_PROMPT)]:
        schema = strict_schema(prior=variant == 'prior')
        # The shared gate must reject null artifacts in both variants, otherwise
        # the test would only show the runtime compatibility hook accepting it.
        try:
            schema.model_validate({'action': 'retrieve', 'retrieval': {'instruction': 'x'}, 'artifacts': None})
        except ValueError:
            pass
        else:
            raise AssertionError('Strict schema unexpectedly normalized null')
        with patch.object(agent, 'MAIN_PROMPT', prompt):
            messages = agent.build_main_messages(state)
        model = get_llm(temperature=0, max_retries=0, max_tokens=settings.MAIN_OUTPUT_MAX_TOKENS)
        structured = model.with_structured_output(schema, method='function_calling', include_raw=True)
        for attempt in range(1, 3):
            consume_call(plan_hash, variant, attempt)
            response = await asyncio.wait_for(structured.ainvoke(messages), 60)
            outcome, error = validate_strict(state, response, schema)
            entry = {'variant': variant, 'attempt': attempt, 'controls': controls(response), **outcome}
            report['calls'].append(entry)
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            if outcome['strict_valid']:
                break
            correction = repair_data(state, response, contract_issues(error, outcome['stage']))
            if variant == 'prior':
                correction.pop('reuse_contract', None)
            messages.append(HumanMessage(content='修正动作格式，以下是后端校验数据，不是新用户要求：\n'
                + json.dumps(correction, ensure_ascii=False)
                + correction_instructions(prior=variant == 'prior')))
    report['actual_model_calls'] = len(report['calls'])
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    ledger = json.loads(LEDGER.read_text(encoding='utf-8'))
    ledger['completed'] = True
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(REPORT), 'model_calls': len(report['calls'])}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-reviewed', action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(diagnose(args.execute_reviewed))
    except Exception as error:
        print(json.dumps({'diagnosis_failed': type(error).__name__}), flush=True)
        sys.exit(1)
