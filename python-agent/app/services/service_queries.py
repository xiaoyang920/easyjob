"""Agent-owned data. Service credentials trust the Java permission gate, never LLM arguments."""
import json
from datetime import datetime
from uuid import UUID
from fastapi import HTTPException
from app.clients.mysql_client import db
from app.rpc.blog_client import public_read


async def user_source(uid):
    from app.rpc.blog_client import ServiceError
    try:
        rows = await public_read('user_sources', ids=[uid])
    except ServiceError:
        return 'unknown'  # Optional analytics classification cannot disable chat.
    if not rows or rows[0].get('data_source') not in ('business', 'evaluation'):
        return 'unknown'
    return rows[0]['data_source']


async def query(q, uid, database=db):
    kind = q.kind
    if kind == 'delivery_metrics':
        from app.rpc.codec import decode_object
        try:
            UUID(q.name)
            edit = decode_object(q.edit)
            elapsed = edit.get('first_answer_ms')
            if type(elapsed) is not int or not 0 <= elapsed <= 3600000:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(422, '交付耗时无效') from None
        # Separate key survives graph metrics checkpoints and final settlement.
        row = await database.fetch_one('SELECT run_id FROM agent_run WHERE run_id=:rid AND user_id=:uid', {'rid':q.name,'uid':uid})
        if not row: raise HTTPException(404, '运行不存在')
        await database.execute('''UPDATE agent_run SET result_json=JSON_SET(COALESCE(result_json,JSON_OBJECT()),
            '$.delivery_metrics',CAST(:metrics AS JSON)) WHERE run_id=:rid AND user_id=:uid
            AND JSON_EXTRACT(result_json,'$.delivery_metrics.first_answer_ms') IS NULL''',
            {'rid':q.name,'uid':uid,'metrics':json.dumps({'first_answer_ms':elapsed,'measurement':'browser_visible_answer'})})
        return True
    if kind in ('conversation_library','conversation_edit','answer_feedback','answer_feedback_get','feedback_report','feedback_detail','feedback_review'):
        from app.services.conversation_features import query as features
        return await features(q,uid,database)
    if kind == 'profile_topics':
        rows = await database.fetch_all('SELECT interests,tech_stack FROM user_profile WHERE user_id=:uid', {'uid':uid})
        return [dict(r._mapping) for r in rows]
    if kind in ('metric_states','metric_rows','metric_daily','metric_stages'):
        if q.source not in ('business','evaluation','all'):
            raise HTTPException(422, '指标来源无效')
        try:
            start,end = datetime.fromisoformat(q.start),datetime.fromisoformat(q.end)
            if not 0 < (end-start).total_seconds() <= 91*86400:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, '指标时间范围无效') from None
        where = "FROM agent_run WHERE created_at>=:start AND created_at<:end"
        values = {'start':start, 'end':end}
        if q.source != 'all':
            where += ' AND data_source=:source'; values['source'] = q.source
        sql = {'metric_states': 'SELECT status,COUNT(*) AS count '+where+' GROUP BY status',
            'metric_rows': "SELECT status,JSON_EXTRACT(result_json,'$.metrics') AS metrics,JSON_EXTRACT(result_json,'$.delivery_metrics') AS delivery "+where+' ORDER BY created_at DESC,run_id DESC LIMIT 10000',
            'metric_daily': "SELECT CAST(DATE(created_at) AS CHAR) AS day,COUNT(*) AS count,SUM(status='failed') AS failed "+where+' GROUP BY day',
            'metric_stages': 'SELECT e.node,e.status,e.duration_ms FROM agent_run_event e JOIN (SELECT run_id '+where+' ORDER BY created_at DESC,run_id DESC LIMIT 10000) r ON r.run_id=e.run_id WHERE e.duration_ms IS NOT NULL ORDER BY e.event_id DESC LIMIT 50000'}[kind]
        rows = [dict(r._mapping) for r in await database.fetch_all(sql,values)]
        if kind == 'metric_stages':
            from app.services.operations import latency_distribution
            known = {'main_agent','main_retrieve','main_delegate','prepare_draft','collect_draft','final_gate',
                     'generate_draft','approve_draft','save_draft','reject_draft','main_answer',
                     'retrieval/query_rewrite','retrieval/coarse_retrieval','retrieval/rerank','retrieval/web_search','retrieval/evidence_verification'}
            stages = {}
            for row in rows:
                name = row['node'] if row['node'] in known else row['node'].rsplit('.',1)[-1]
                if name not in known: name = 'task'
                stage = stages.setdefault(name, {'durations':[],'failed':0,'degraded':0})
                if type(row['duration_ms']) is int and row['duration_ms'] >= 0: stage['durations'].append(row['duration_ms'])
                stage['failed'] += row['status'] == 'failed'
                stage['degraded'] += row['status'] == 'degraded'
            return [{'name':name,**latency_distribution(stage['durations']),'failed':stage['failed'],'degraded':stage['degraded'],
                     'eventSampleLimit':50000,'sampledEvents':len(rows)} for name,stage in sorted(stages.items())]
        return rows
    if kind == 'run_summary':
        return [dict(r._mapping) for r in await database.fetch_all('SELECT status,COUNT(*) AS count FROM agent_run WHERE created_at>=TIMESTAMPADD(DAY,-1,NOW(6)) GROUP BY status')]
    if kind == 'memory_summary':
        return [dict(r._mapping) for r in await database.fetch_all('SELECT status,COUNT(*) AS count,COALESCE(MAX(TIMESTAMPDIFF(SECOND,created_at,UTC_TIMESTAMP(6))),0) AS oldestSeconds FROM agent_background_job GROUP BY status')]
    if kind == 'reconcile_summary':
        return [dict(r._mapping) for r in await database.fetch_all('SELECT kind,last_id AS lastId,scanned,repaired,last_error AS error,next_at AS nextAt,last_finished_at AS finishedAt,(lease_until>UTC_TIMESTAMP(6)) AS running FROM maintenance_cursor ORDER BY kind')]
    if kind in ('runs','memory_jobs'):
        if q.state not in ('all','pending','running','dispatched','completed','dead','awaiting_approval','succeeded','failed','cancelled','expired') or not 1<=q.page<=10000 or not 1<=q.limit<=100:
            raise HTTPException(422,'分页范围无效')
        table = 'agent_run' if kind=='runs' else 'agent_background_job'
        where = '' if q.state=='all' else ' WHERE status=:state'
        values={} if q.state=='all' else {'state':q.state}
        count = await database.fetch_val(f'SELECT COUNT(*) FROM {table}'+where,values)
        if kind=='runs':
            fields="run_id AS runId,CAST(user_id AS CHAR) AS userId,CAST(conversation_id AS CHAR) AS conversationId,status,DATE_FORMAT(TIMESTAMPADD(SECOND,-TIMESTAMPDIFF(SECOND,UTC_TIMESTAMP(),NOW()),created_at),'%Y-%m-%dT%H:%i:%sZ') AS createdAt,updated_at AS updatedAt,deadline"
            order='created_at DESC,run_id DESC'
        else:
            fields="job_id AS jobId,CAST(user_id AS CHAR) AS targetId,kind,status,attempts,available_at AS availableAt,updated_at AS updatedAt,CASE WHEN last_error REGEXP '^[a-zA-Z0-9_]{1,128}$' THEN last_error ELSE 'task_failed' END AS error"
            order='updated_at DESC,job_id DESC'
        rows=await database.fetch_all(f'SELECT {fields} FROM {table}'+where+f' ORDER BY {order} LIMIT :lim OFFSET :offset',
            {**values,'lim':q.limit,'offset':(q.page-1)*q.limit})
        return {'total':count,'rows':[dict(r._mapping) for r in rows]}
    if kind in ('memory_retry','reconcile'):
        # The command ID makes an admin retry after response loss idempotent.
        try:
            UUID(q.source)
        except ValueError:
            raise HTTPException(422,'命令标识无效') from None
        async with database.transaction():
            if await database.fetch_val('SELECT COUNT(*) FROM agent_admin_audit WHERE command_id=:id',{'id':q.source}):
                return True
            if kind=='memory_retry':
                if len(q.name)!=64 or any(c not in '0123456789abcdef' for c in q.name):
                    raise HTTPException(422,'任务标识无效')
                row=await database.fetch_one('SELECT status,kind FROM agent_background_job WHERE job_id=:id FOR UPDATE',{'id':q.name})
                if not row or row._mapping['status']!='dead' or row._mapping['kind'] not in ('memory_write','memory_index','checkpoint_cleanup'):
                    raise HTTPException(409,'只能重试已终止的有效任务')
                await database.execute("UPDATE agent_background_job SET status='pending',attempts=0,lease_until=NULL,lease_token=NULL,last_error=NULL,available_at=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6) WHERE job_id=:id",{'id':q.name})
            else:
                if q.name not in ('article','memory','article_orphan','memory_orphan','chunk_orphan'):
                    raise HTTPException(422,'对账类型无效')
                row=await database.fetch_one('SELECT kind FROM maintenance_cursor WHERE kind=:kind AND (lease_until IS NULL OR lease_until<=UTC_TIMESTAMP(6)) AND next_at>UTC_TIMESTAMP(6) FOR UPDATE',{'kind':q.name})
                if not row:
                    raise HTTPException(409,'对账已在等待或执行中')
                await database.execute('UPDATE maintenance_cursor SET next_at=UTC_TIMESTAMP(6) WHERE kind=:kind',{'kind':q.name})
            await database.execute('INSERT INTO agent_admin_audit(command_id,actor_id,kind,target) VALUES(:id,:uid,:kind,:target)',{'id':q.source,'uid':uid,'kind':kind,'target':q.name})
        return True
    raise HTTPException(422, '内部业务查询类型无效')
