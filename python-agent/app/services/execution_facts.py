"""Server-derived execution facts; model prose never changes these facts."""
import re


def execution_facts(state):
    retrievals, drafts = [], []
    for tid, result in (state.get('task_results') or {}).items():
        if report := result.get('retrieval_report'):
            retrievals.append({'task_id': tid, 'status': result.get('status'),
                'platform': report.get('platform', {}).get('status', 'unknown'),
                'web': report.get('web', {}).get('status', 'unknown'),
                'rerank': report.get('platform', {}).get('rerank', {}).get('status', 'unknown')})
        if result.get('kind') == 'writing':
            drafts.append({'task_id': tid, 'saved': result.get('status') == 'succeeded'
                and bool(result.get('draft_article_id'))})
    previous = state.get('previous_run') or {}
    return {'retrievals': retrievals, 'drafts': drafts,
        'memory_write': state.get('memory_write_status') or 'not_submitted',
        'previous_run': {key: previous[key] for key in ('status', 'node', 'tasks', 'saved_draft_id') if key in previous},
        'notice': '状态仅证明实际执行；found不证明资料相关，empty不证明全平台不存在。'}


def execution_issues(text, facts):
    """Targeted assertions, not an attempt to understand all natural language."""
    # Quoted code is source data, not a claim that the application performed it.
    visible = re.sub(r'```.*?```|`[^`]*`', '', text, flags=re.S)
    issues = []
    web = {item['web'] for item in facts['retrievals']}
    completed = bool(web & {'found', 'empty'})
    patterns = (
        (r'(?:已|已经|成功|确实|刚刚)(?:经|完成|进行了|进行|通过|使用|调用|开启|启用)?(?:联网检索|联网搜索|搜索公开网页)', completed, '没有已完成的联网检索记录'),
        (r'(?:联网检索|联网搜索)(?:已经|已|确实)?(?:成功|完成|返回了|找到)', completed, '联网检索未完成'),
        (r'(?:草稿|文章)(?:已经|已)(?:成功)?保存|(?:已经|已)(?:成功)?保存(?:了)?(?:到草稿箱|草稿|文章)',
            any(item['saved'] for item in facts['drafts']), '没有草稿保存成功记录'),
        (r'(?:已经|已)(?:成功)?记住(?:了)?|记住了|记下了', facts['memory_write'] == 'succeeded', '长期记忆尚未确认写入成功'),
    )
    for pattern, supported, reason in patterns:
        if not supported and re.search(pattern, visible):
            issues.append(reason)
    if completed and re.search(r'(?:没有|未)(?:进行|执行|使用|调用|开启)?联网(?:检索|搜索)', visible):
        issues.append('实际已有完成的联网检索，不能声称未执行')
    return issues


def delivery_notices(state, citations):
    assessment = (state.get('main_decision') or {}).get('evidence_assessment') or {}
    notes = []
    audit = state.get('grounding_audit') or {}
    supplemented = (audit.get('lookup_status') == 'succeeded'
                    and audit.get('status') in ('verified', 'repaired'))
    if assessment.get('adequacy') == 'none' and not state.get('business_complete'):
        notes.append('初轮检索资料不足，本次已补充检索；具体可确认的内容见正文。' if supplemented else
                     '本次检索未找到足够相关资料；通用解释或建议不代表已通过本次检索验证。')
    if assessment.get('adequacy') == 'partial':
        notes.append('初轮资料只覆盖部分目标，本次已补充检索；具体范围见正文。' if supplemented else
                     '资料只支持部分目标，以上内容不代表完整结论。')
    if assessment.get('conflicts'):
        notes.append('所选资料存在冲突，相关结论需要结合版本和适用条件判断。')
    facts = execution_facts(state)
    web = {item['web'] for item in facts['retrievals']}
    if 'error' in web:
        notes.append('部分联网检索未完成，不能据此认定没有相关网页。')
    if any(c.get('contentScope') == 'search_excerpt' for c in citations):
        notes.append('网页依据来自搜索返回的摘要，尚未核验网页全文。')
    if facts['memory_write'] == 'pending':
        notes.append('长期记忆变更正在后台保存，结果可在记忆管理页查看。')
    elif facts['memory_write'] == 'failed':
        notes.append('长期记忆变更未能提交保存，本次回答仍按你的要求处理。')
    return notes
