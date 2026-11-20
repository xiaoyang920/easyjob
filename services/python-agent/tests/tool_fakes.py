"""Translate existing routing fixtures to the new wire contract without model calls."""
def retrieval_call(request):
    from app.models.main_tool import call_from_retrieval
    return call_from_retrieval(request)


def raw_retrieval_call(request):
    if request is None:
        return None
    data = dict(request)
    target = data.pop('target', 'knowledge')
    common = {key: data.pop(key) for key in ('task_id', 'required_skills') if key in data}
    instruction = data.pop('instruction', '')
    name = {'knowledge': 'search_knowledge', 'memory': 'read_memory',
            'drafts': 'read_draft', 'editor': 'read_editor'}.get(target, target)
    if target in ('knowledge', 'memory'):
        data['query'] = instruction
    elif target == 'editor':
        if 'editor_part' in data:
            data['part'] = data.pop('editor_part')
    elif target == 'drafts':
        ids = data.pop('article_ids', [])
        data['article_id'] = ids[0] if len(ids) == 1 else None
        if 'search_query' in data:
            data['keyword'] = data.pop('search_query')
    return {**common, 'name': name, 'args': data}
