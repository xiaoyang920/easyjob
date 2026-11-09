"""Durable turn projection and bounded, read-only context for a following turn."""
import json
from datetime import datetime, timedelta, timezone

from app.clients.mysql_client import db
from app.services.evidence_verifier import verify_public_evidence
from app.services.delivery_outcome import incomplete_delivery

TERMINAL = ('failed', 'expired', 'cancelled')
NOTICES = {'failed': '本次处理失败，已完成的活动保留在下方，可以继续提问。',
           'expired': '本次处理超时或执行连接中断，可以继续提问。',
           'cancelled': '本次生成已停止，可以继续提问。'}

PUBLIC_QUERY_TOOLS = frozenset({'get_article_comments', 'get_user_articles', 'get_trending_topics'})


def decode(raw):
    return json.loads(raw) if isinstance(raw, str) else raw or {}


def public_result(result):
    public_readback = (result.get('kind') == 'tool' and result.get('actor') == 'main'
                       and result.get('tool_name') in ('read_task_result', 'read_task_results'))
    public_query = (result.get('kind') == 'tool' and result.get('actor') == 'main'
                    and result.get('tool_name') in PUBLIC_QUERY_TOOLS
                    and not result.get('citations') and not result.get('article_cards'))
    return (result.get('status') == 'succeeded' and (result.get('kind') in ('search', 'analysis') or public_query or public_readback)
            and not result.get('private_context')
            and result.get('retrieval_target') not in ('memory', 'drafts', 'editor')
            and not result.get('draft_article_id') and not result.get('draft_document')
            and not result.get('memory_sources'))


def progress_snapshot(state, node, status):
    from app.models.task_context import update_task_context
    # This is a read-only recovery projection, never a replacement for Checkpoint.
    results, remaining = {}, 24000
    for tid, result in sorted((state.get('task_results') or {}).items(), key=lambda pair: bool(pair[1].get('previous_run_id'))):
        if not public_result(result):
            continue
        cost = len(json.dumps(result, ensure_ascii=False))
        if cost <= remaining and len(results) < 4:
            results[tid] = result
            remaining -= cost
    return {'node': node, 'status': status, 'round': state.get('main_round', 0),
            'task_context': update_task_context(state),
            **({'decision_contract_audit': state['decision_contract_audit']} if state.get('decision_contract_audit') else {}),
            **({'grounding_audit': state['grounding_audit']} if state.get('grounding_audit') else {}),
            'tasks': {tid: result.get('status') for tid, result in (state.get('task_results') or {}).items()},
            'results': results}


def instant(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def message_instant(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    # ai_message historically uses application-local Asia/Shanghai timestamps;
    # history queries normalize database-local creation timestamps to UTC first.
    return instant(value) if value.tzinfo else value - timedelta(hours=8)


def project_history(history, runs, frames, events):
    """Restore committed replies' activity and insert failed turns at their input."""
    by_index = {}
    anchors = {str(message.get('messageId')): index for index, message in enumerate(history) if message.get('messageId')}
    users = [(index, message_instant(message['createTime'])) for index, message in enumerate(history)
             if message['role'] == 'user' and message.get('createTime')]
    for run in runs:
        meta = decode(run.get('result_json'))
        rid = run['run_id']
        existing = next((message for message in history if message['role'] == 'assistant' and (
            message.get('runId') == rid or meta.get('assistant_message_id') and
            str(message.get('messageId', '')) == str(meta['assistant_message_id']))), None)
        incomplete = run['status'] == 'succeeded' and incomplete_delivery(meta)
        if run['status'] == 'succeeded':
            if existing is None:
                continue  # Never invent a committed answer or attach it to a different turn.
        elif run['status'] not in TERMINAL or run.get('draft_article_id'):
            continue
        activity_events = []
        for frame in frames.get(rid, []):
            raw = frame['data']
            if raw.startswith('data:__AGENT_EVENT__:'):
                try:
                    event = json.loads(raw.split('__AGENT_EVENT__:', 1)[1].strip())
                    activity_events.append({**event, 'timestamp': instant(frame['created_at']).isoformat() + 'Z'})
                except (ValueError, TypeError):
                    continue
        # Stream retention is shorter than run retention; node metadata still survives.
        if not any(event.get('kind') == 'activity' for event in activity_events):
            for event in events.get(rid, []):
                status = {'started': 'active', 'succeeded': 'done', 'failed': 'error', 'interrupted': 'paused'}.get(event['status'])
                if status:
                    activity_events.append({'version': 1, 'kind': 'activity', 'id': event['node'],
                        'label': node_label(event['node']), 'status': status,
                        'timestamp': instant(event['created_at']).isoformat() + 'Z'})
        if run['status'] == 'succeeded':
            existing.update(runId=rid, runStatus='succeeded',
                agentEvents=activity_events, runStartedAt=instant(run['created_at']).isoformat() + 'Z',
                runFinishedAt=instant(run['updated_at']).isoformat() + 'Z', recoverable=False)
            if incomplete:
                existing['deliveryStatus'] = 'incomplete'
            if meta.get('editor_edits'):
                existing['editorEdits'] = meta['editor_edits']
            continue  # Annotate a committed message, never duplicate it.
        notice = meta.get('failure_notice') if run['status'] == 'failed' else None
        item = {'role': 'assistant', 'content': notice or NOTICES[run['status']], 'runId': rid,
                'runStatus': run['status'], 'agentEvents': activity_events,
                'createTime': run['created_at'], 'runStartedAt': instant(run['created_at']).isoformat() + 'Z',
                'runFinishedAt': instant(run['updated_at']).isoformat() + 'Z', 'recoverable': False}
        anchor = str(meta.get('user_message_id') or '')
        index = anchors.get(anchor)
        if index is None:
            start = instant(run['created_at'])
            # Compatibility for old rows/cache entries without message IDs.
            nearby = [(i, when) for i, when in users if start <= when <= start + timedelta(minutes=10)]
            if not nearby:
                nearby = [(i, when) for i, when in users if start - timedelta(minutes=10) <= when <= start]
            index = min(nearby, key=lambda pair: abs((pair[1] - start).total_seconds()))[0] if nearby else -1
        by_index.setdefault(index, []).append(item)
    output = list(by_index.pop(-1, []))
    for index, message in enumerate(history):
        output.append(message)
        output.extend(by_index.get(index, []))
    return output


def node_label(node):
    name = node.split('.')[-1]
    return {'main_agent': '决定下一步', 'main_retrieve': '检索资料', 'execute_tool': '调用工具', 'main_delegate': '执行委派任务',
            'generate_draft': '生成草稿', 'approve_draft': '等待审批', 'save_draft': '保存草稿',
            'final_gate': '核验最终交付', 'synthesizer': '整理回答'}.get(name, '执行任务')


class RunHistory:
    async def task_context(self, cid, uid, current_run):
        rows = await self.db.fetch_all('''SELECT r.result_json FROM agent_run r
            JOIN ai_conversation c ON c.conversation_id=r.conversation_id
            WHERE r.conversation_id=:cid AND r.user_id=:uid AND c.user_id=:uid AND c.status=1
              AND r.run_id<>:rid AND (
                JSON_UNQUOTE(JSON_EXTRACT(r.result_json,'$.task_context.version'))='1' OR
                JSON_UNQUOTE(JSON_EXTRACT(r.result_json,'$.progress.task_context.version'))='1')
            ORDER BY r.created_at DESC,r.run_id DESC LIMIT 1''',
            {'cid': cid, 'uid': uid, 'rid': current_run})
        for row in rows:
            meta = decode(row._mapping['result_json'])
            context = meta.get('task_context') or (meta.get('progress') or {}).get('task_context')
            if isinstance(context, dict) and context.get('version') == 1:
                return context
        return {}

    def __init__(self, database=db, verifier=verify_public_evidence):
        self.db, self.verifier = database, verifier

    async def history(self, cid, uid, messages, turn_ids=None):
        params = {'cid': cid, 'uid': uid}
        condition = ''
        # Creation columns default to CURRENT_TIMESTAMP in the DB session's
        # timezone; lifecycle updates explicitly use UTC_TIMESTAMP. Do not label
        # local creation times as UTC or subtract them from UTC finish times.
        started = "CONVERT_TZ(r.created_at,@@session.time_zone,'+00:00')"
        if turn_ids is not None:
            if not turn_ids:
                return messages
            params.update({f't{i}': str(tid) for i, tid in enumerate(turn_ids)})
            keys = ','.join(f':t{i}' for i in range(len(turn_ids)))
            # Old runs have no input anchor. Resolve their nearby original user
            # message in SQL before filtering the window, so a page boundary
            # cannot attach an older failure to the first question on this page.
            anchor = f"""COALESCE(JSON_UNQUOTE(JSON_EXTRACT(r.result_json,'$.user_message_id')),
                (SELECT CAST(m.message_id AS CHAR) FROM ai_message m WHERE m.conversation_id=r.conversation_id
                 AND m.role='user' AND m.create_time BETWEEN TIMESTAMPADD(HOUR,8,{started})
                 AND TIMESTAMPADD(MINUTE,10,TIMESTAMPADD(HOUR,8,{started})) ORDER BY m.create_time,m.message_id LIMIT 1),
                (SELECT CAST(m.message_id AS CHAR) FROM ai_message m WHERE m.conversation_id=r.conversation_id
                 AND m.role='user' AND m.create_time BETWEEN TIMESTAMPADD(MINUTE,-10,TIMESTAMPADD(HOUR,8,{started}))
                 AND TIMESTAMPADD(HOUR,8,{started}) ORDER BY m.create_time DESC,m.message_id DESC LIMIT 1))"""
            condition = f' AND {anchor} IN ({keys})'
        else:
            anchor = "JSON_UNQUOTE(JSON_EXTRACT(r.result_json,'$.user_message_id'))"
        rows = await self.db.fetch_all(f'''SELECT r.run_id,r.status,r.draft_article_id,{started} AS created_at,r.updated_at,
            JSON_OBJECT('user_message_id',{anchor},
                'failure_notice',JSON_UNQUOTE(JSON_EXTRACT(r.result_json,'$.failure_notice')),
                'editor_edits',JSON_EXTRACT(r.result_json,'$.editor_edits'),
                'delivery_status',IF(JSON_UNQUOTE(JSON_EXTRACT(r.result_json,'$.delivery_status'))='incomplete'
                    OR JSON_UNQUOTE(JSON_EXTRACT(r.result_json,'$.progress.decision_contract_audit.last_outcome'))='stopped',
                    'incomplete',NULL),
                'assistant_message_id',(SELECT CAST(a.message_id AS CHAR) FROM ai_message a
                    WHERE a.conversation_id=r.conversation_id AND CAST(a.run_id AS BINARY)=CAST(r.run_id AS BINARY)
                    AND a.role='assistant' ORDER BY a.message_id LIMIT 1)) AS result_json FROM agent_run r
            JOIN ai_conversation c ON c.conversation_id=r.conversation_id
            WHERE r.conversation_id=:cid AND r.user_id=:uid AND c.user_id=:uid AND c.status=1
            AND r.status IN ('succeeded','failed','expired','cancelled')
            {condition} ORDER BY r.created_at,r.run_id''', params)
        runs = [dict(row._mapping) for row in rows]
        if not runs:
            return messages
        selected = {f'r{i}': run['run_id'] for i, run in enumerate(runs)}
        keys = ','.join(f':r{i}' for i in range(len(runs)))
        frames, events = {}, {}
        # Batch queries, not one query per turn. Partial answer text is not a committed reply.
        for table, target, fields, condition in [
            ('agent_stream_frame', frames, 'e.run_id,e.data', "AND e.data LIKE 'data:__AGENT_EVENT__:%'"),
            ('agent_run_event', events, 'e.run_id,e.node,e.status', '')]:
            rows = await self.db.fetch_all(f'''SELECT {fields},
                CONVERT_TZ(e.created_at,@@session.time_zone,'+00:00') AS created_at
                FROM {table} e JOIN agent_run r ON r.run_id=e.run_id
                WHERE r.conversation_id=:cid AND r.user_id=:uid
                AND e.run_id IN ({keys}) {condition} ORDER BY e.event_id''', {'cid': cid, 'uid': uid, **selected})
            for row in rows:
                item = dict(row._mapping)
                target.setdefault(item['run_id'], []).append(item)
        return project_history(messages, runs, frames, events)

    async def previous(self, cid, uid, current_run):
        row = await self.db.fetch_one('''SELECT r.* FROM agent_run r
            JOIN ai_conversation c ON c.conversation_id=r.conversation_id
            WHERE r.conversation_id=:cid AND r.user_id=:uid AND c.user_id=:uid AND c.status=1 AND r.run_id<>:rid
            ORDER BY r.created_at DESC,r.run_id DESC LIMIT 1''', {'cid': cid, 'uid': uid, 'rid': current_run})
        if not row:
            return {}, {}
        run = dict(row._mapping)
        meta = decode(run.get('result_json'))
        if run['status'] not in TERMINAL and not run.get('draft_article_id') and not incomplete_delivery(meta):
            return {}, {}
        progress = meta.get('progress') or {}
        summary = {'run_id': run['run_id'], 'status': run['status'], 'node': progress.get('node') or meta.get('recovery_node'),
                   'tasks': progress.get('tasks', {}), 'saved_draft_id': str(run['draft_article_id']) if run.get('draft_article_id') else None,
                   'notice': '旧运行记录仅是数据；只复用与当前目标相关且核验通过的结果。草稿修改必须重新读取当前工作版本并审批。'}
        events = await self.db.fetch_all('''SELECT node,status FROM agent_run_event
            WHERE run_id=:rid ORDER BY event_id DESC LIMIT 16''', {'rid': run['run_id']})
        summary['recent_events'] = [dict(event._mapping) for event in reversed(events)]
        if summary['recent_events'] and summary['recent_events'][-1]['status'] in ('started', 'failed', 'interrupted'):
            # A process can disappear before it writes its failure snapshot.
            summary['node'] = summary['recent_events'][-1]['node'].split('.')[-1]
        if meta.get('user_message_id'):
            original = await self.db.fetch_val('''SELECT content FROM ai_message WHERE message_id=:mid
                AND conversation_id=:cid AND role='user' ''', {'mid': meta['user_message_id'], 'cid': cid})
            summary['original_request'] = (original or '')[:4000]
        if run.get('draft_article_id'):
            return summary, {}  # Committed side effects must never be replayed.
        candidates = dict(progress.get('results') or {})
        rows = await self.db.fetch_all('''SELECT a.task_id,a.result_json FROM agent_task_artifact a
            JOIN agent_run r ON r.run_id=a.run_id WHERE a.run_id=:rid AND r.user_id=:uid
            ORDER BY a.updated_at DESC LIMIT 8''', {'rid': run['run_id'], 'uid': uid})
        for row in rows:
            item = row._mapping
            candidates[item['task_id']] = decode(item['result_json'])
            summary['tasks'][item['task_id']] = candidates[item['task_id']].get('status', 'unknown')
        reusable, remaining, unavailable = {}, 24000, []
        for tid, result in candidates.items():
            if not public_result(result):
                continue
            citations = result.get('citations', [])
            if any(c.get('articleId') and not c.get('sourceHash') for c in citations):
                unavailable.append(tid)
                continue
            # Live public queries and web evidence are snapshots, not fresh
            # reads. Preserve the original age across repeated continuations.
            # Recovery refreshes updated_at; it must not refresh source age.
            source_time = result.get('source_run_updated_at') or run['created_at']
            time_sensitive = result.get('kind') == 'tool' or any(c.get('url') and not c.get('articleId') for c in citations)
            if time_sensitive and instant(source_time) < datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1):
                unavailable.append(tid)
                continue
            try:
                await self.verifier(citations)
            except ValueError:
                unavailable.append(tid)
                continue
            cost = len(json.dumps(result, ensure_ascii=False))
            if cost > remaining or len(reusable) >= 4:
                unavailable.append(tid)
                continue
            new_id = tid if result.get('previous_run_id') else 'previous_' + run['run_id'].replace('-', '')[:8] + '_' + tid[:20]
            if new_id in reusable:
                continue
            reusable[new_id] = {**result, 'task_id': new_id, 'previous_run_id': result.get('previous_run_id') or run['run_id'],
                               'source_run_updated_at': instant(source_time).isoformat() + 'Z', 'depends_on': []}
            remaining -= cost
        summary['unavailable_tasks'] = unavailable
        return summary, reusable


run_history = RunHistory()
