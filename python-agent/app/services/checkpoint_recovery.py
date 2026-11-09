"""Conservative replay policy for pending graph work, never a write/approval retry."""
from app.graph.staged_plan import load_execution_plan
from app.services.evidence_verifier import verify_public_evidence
from app.services.tool_registry import tool_registry
from datetime import datetime, timedelta, timezone
from app.services.run_history import instant, PUBLIC_QUERY_TOOLS


async def validate_snapshot(snapshot, run, repository):
    pending = tuple(snapshot.next)
    if len(pending) != 1 or pending[0] not in ('main_agent', 'execute_tool', 'main_retrieve', 'main_delegate'):
        return False
    state = snapshot.values
    if any(state.get(key) for key in ('cancelled', 'business_complete', 'draft_article_id',
            'editor_context', 'editor_snapshot_id', 'draft_document', 'memory_sources',
            'memory_changes_queued', 'pending_memory_changes', 'memory_write_job_id')):
        return False
    if any(task.interrupts for task in snapshot.tasks):
        return False
    if any(state.get(key) != run[key] for key in ('run_id', 'user_id', 'conversation_id')):
        return False
    results = list((state.get('task_results') or {}).values())
    results.extend(((state.get('previous_run') or {}).get('reusable_results') or {}).values())
    if any(r.get('retrieval_target') in ('memory', 'drafts', 'editor') or r.get('memory_sources')
           or r.get('draft_document') for r in results):
        return False
    if any(r.get('status') == 'succeeded' and r.get('tool_name') in PUBLIC_QUERY_TOOLS for r in results):
        return False  # These observations do not retain enough resource identity to reauthorize.
    if pending[0] == 'main_agent':
        # Enqueue can have committed before the node output reached Redis. A fresh
        # model decision cannot safely reconstruct that already accepted batch.
        if await repository.has_memory_write(run['run_id']):
            return False
    else:
        actor = 'subagent' if pending[0] == 'main_delegate' else 'main'
        plan = load_execution_plan(state['plan'], actor)
        for task in plan.tasks:
            if task.retrieval_target in ('memory', 'drafts', 'editor'):
                return False
            if actor == 'subagent':
                if task.kind not in ('search', 'analysis'):
                    return False
            else:
                if task.kind not in ('search', 'tool'):
                    return False
                if task.tool_name and tool_registry.main_tool(task.tool_name).capability not in ('platform_read', 'web_search'):
                    return False
    citations = list(state.get('citations') or [])
    for result in results:
        citations.extend(result.get('citations') or [])
    citations.extend((state.get('delivery_evidence') or {}).get('citations') or [])
    if any(c.get('articleId') and not c.get('sourceHash') for c in citations):
        return False
    for result in [*results, {'citations': state.get('citations') or []},
                   state.get('delivery_evidence') or {}]:
        if any(not c.get('articleId') for c in result.get('citations') or []):
            # Never use recovery-updated updated_at to make an old web snapshot young.
            source_time = result.get('source_run_updated_at') or run.get('created_at')
            if not source_time or instant(source_time) < datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1):
                return False
    await verify_public_evidence(citations)
    return True
