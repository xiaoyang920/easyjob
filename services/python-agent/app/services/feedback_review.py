"""Explicit admin feedback inspection. Called only behind Java's feedback permissions.

The report lists metadata. This endpoint opens only the reported turn, never a
whole conversation, model reasoning, tool arguments, or unrelated messages.
"""
from uuid import UUID, uuid4
from fastapi import HTTPException
from app.rpc.codec import decode_object


def as_dict(row): return dict(row._mapping) if row else None


async def query(q, actor, database):
    try: UUID(q.name)
    except (ValueError, TypeError): raise HTTPException(422, '运行标识无效') from None
    if q.kind == 'feedback_review':
        edit = decode_object(q.edit)
        state, note, version, command, generation = (edit.get(k) for k in ('state','note','version','commandId','generation'))
        if state not in ('pending','resolved') or not isinstance(note,str) or len(note)>1000 or type(version) is not int or version<0:
            raise HTTPException(422,'处理内容无效')
        if state=='resolved' and not note.strip(): raise HTTPException(422,'请填写处理说明')
        try: UUID(command); UUID(generation)
        except (ValueError, TypeError, AttributeError): raise HTTPException(422,'命令标识无效') from None
        async with database.transaction():
            row = as_dict(await database.fetch_one('SELECT user_id,review_state,review_version,feedback_generation FROM agent_answer_feedback WHERE run_id=:rid FOR UPDATE',{'rid':q.name}))
            if not row: raise HTTPException(404,'反馈已撤回或不存在')
            previous = as_dict(await database.fetch_one('SELECT run_id,actor_id,to_state,note,expected_version,feedback_generation FROM agent_feedback_review_log WHERE command_id=:command',{'command':command}))
            if previous:
                if previous != {'run_id':q.name,'actor_id':actor,'to_state':state,'note':note.strip(),'expected_version':version,'feedback_generation':generation}:
                    raise HTTPException(409,'命令标识已用于其他操作')
                return {'version':version+1,'state':state}
            if row['review_version']!=version or row['feedback_generation']!=generation: raise HTTPException(409,'反馈已更新，请重新打开后处理')
            await database.execute('''UPDATE agent_answer_feedback SET review_state=:state,review_note=:note,
                handled_by=:actor,handled_at=UTC_TIMESTAMP(6),review_version=review_version+1
                WHERE run_id=:rid AND user_id=:uid AND review_version=:version''',
                {'state':state,'note':note.strip(),'actor':actor,'rid':q.name,'uid':row['user_id'],'version':version})
            await database.execute('''INSERT INTO agent_feedback_review_log(command_id,run_id,user_id,actor_id,from_state,to_state,note,expected_version,feedback_generation)
                VALUES(:command,:rid,:uid,:actor,:before,:state,:note,:version,:generation)''',
                {'command':command,'rid':q.name,'uid':row['user_id'],'actor':actor,'before':row['review_state'],'state':state,'note':note.strip(),'version':version,'generation':generation})
        return {'version':version+1,'state':state}
    row = as_dict(await database.fetch_one('''SELECT f.*,CAST(r.conversation_id AS CHAR) AS conversation_id,r.status AS run_status,r.data_source,
        r.created_at AS run_created_at,JSON_UNQUOTE(JSON_EXTRACT(r.result_json,'$.user_message_id')) AS input_message_id,c.status AS conversation_status
        FROM agent_answer_feedback f JOIN agent_run r ON r.run_id=f.run_id AND r.user_id=f.user_id
        LEFT JOIN ai_conversation c ON c.conversation_id=r.conversation_id AND c.user_id=r.user_id WHERE f.run_id=:rid''',{'rid':q.name}))
    if not row: raise HTTPException(404,'反馈已撤回或不存在')
    await database.execute('INSERT INTO agent_admin_audit(command_id,actor_id,kind,target) VALUES(:command,:actor,:kind,:target)',
        {'command':str(uuid4()),'actor':actor,'kind':'feedback_view','target':q.name})
    question, answer = None, None
    values = {'cid':int(row['conversation_id']),'rid':q.name}
    if row['conversation_status']==1:
        if row.get('input_message_id') and str(row['input_message_id']).isdigit():
            question = as_dict(await database.fetch_one("SELECT LEFT(content,100000) AS content,CHAR_LENGTH(content)>100000 AS truncated,create_time FROM ai_message WHERE conversation_id=:cid AND message_id=:mid AND role='user'",{'cid':values['cid'],'mid':int(row['input_message_id'])}))
        answer = as_dict(await database.fetch_one("SELECT LEFT(content,100000) AS content,CHAR_LENGTH(content)>100000 AS truncated,create_time FROM ai_message WHERE conversation_id=:cid AND run_id=:rid AND role='assistant' ORDER BY message_id DESC LIMIT 1",values))
    events = [as_dict(r) for r in await database.fetch_all('SELECT event_id,node,status,duration_ms,created_at FROM agent_run_event WHERE run_id=:rid ORDER BY event_id DESC LIMIT 100',{'rid':q.name})]
    history = [as_dict(r) for r in await database.fetch_all('SELECT CAST(actor_id AS CHAR) AS actor_id,from_state,to_state,note,created_at FROM agent_feedback_review_log WHERE run_id=:rid AND user_id=:uid ORDER BY created_at DESC,command_id DESC LIMIT 20',{'rid':q.name,'uid':row['user_id']})]
    row.pop('input_message_id',None)
    row['user_id'] = str(row['user_id'])
    if row.get('handled_by') is not None: row['handled_by'] = str(row['handled_by'])
    return {'feedback':row,'question':question,'answer':answer,'events':list(reversed(events)),'history':history}
