"""Owner-scoped conversation library and explicit delivery feedback; never LLM context."""
from uuid import UUID
from fastapi import HTTPException
from app.clients.mysql_client import db
from app.rpc.codec import decode_object

def pagination(q):
    if not 1<=q.page<=10000 or not 1<=q.limit<=100:raise HTTPException(422,'分页范围无效')
    return {'limit':q.limit,'offset':(q.page-1)*q.limit}

async def query(q,uid,database=db):
    if q.kind=='conversation_library':
        from app.services.conversation import ConversationService,_to_camel_dict
        if q.state not in ('all','general','article') or len(q.name)>80:raise HTTPException(422,'搜索条件无效')
        values={'uid':uid,**pagination(q)};where='c.user_id=:uid AND c.status=1'
        if q.state=='general':where+=' AND c.origin_article_id IS NULL'
        if q.state=='article':where+=' AND c.origin_article_id IS NOT NULL AND c.message_count>0'
        if q.name.strip():
            values['keyword']='%'+q.name.strip().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
            where+=" AND (c.title LIKE :keyword ESCAPE '!' OR EXISTS(SELECT 1 FROM ai_message m WHERE m.conversation_id=c.conversation_id AND m.content LIKE :keyword ESCAPE '!'))"
        total=await database.fetch_val('SELECT COUNT(*) FROM ai_conversation c WHERE '+where,{'uid':uid,**({'keyword':values['keyword']} if 'keyword' in values else {})})
        rows=[dict(r._mapping) for r in await database.fetch_all('SELECT c.* FROM ai_conversation c WHERE '+where+' ORDER BY c.is_pinned DESC,c.update_time DESC,c.conversation_id DESC LIMIT :limit OFFSET :offset',values)]
        await ConversationService._enrich_origins(rows)
        # These maps bypass Java's entity serializers. Keep Snowflake identifiers
        # as strings at the browser boundary, including values beyond 2**53.
        for row in rows:
            for key in ('conversation_id','user_id','origin_article_id'):
                if row.get(key) is not None:row[key]=str(row[key])
        return {'rows':[_to_camel_dict(r) for r in rows],'total':total}
    if q.kind=='conversation_edit':
        try:cid=int(q.name)
        except ValueError:raise HTTPException(422,'会话标识无效') from None
        if not 0<cid<2**63:raise HTTPException(422,'会话标识无效')
        edit=decode_object(q.edit)
        if not set(edit)&{'title','pinned'} or set(edit)-{'title','pinned','version'} or not isinstance(edit.get('version'),int) or isinstance(edit.get('version'),bool):raise HTTPException(422,'修改参数无效')
        if 'title' in edit and (not isinstance(edit['title'],str) or not 1<=len(edit['title'].strip())<=80):raise HTTPException(422,'标题需要1至80个字')
        if 'pinned' in edit and not isinstance(edit['pinned'],bool):raise HTTPException(422,'置顶参数无效')
        async with database.transaction():
            row=await database.fetch_one('SELECT title,is_pinned,metadata_version FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid AND status=1 FOR UPDATE',{'cid':cid,'uid':uid})
            if not row:raise HTTPException(404,'会话不存在或无权访问')
            row=dict(row._mapping)
            if row['metadata_version']!=edit['version']:raise HTTPException(409,'会话已修改，请刷新后重试')
            await database.execute('UPDATE ai_conversation SET title=:title,is_pinned=:pin,metadata_version=metadata_version+1 WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':uid,'title':edit.get('title',row['title']).strip() if edit.get('title',row['title']) else None,'pin':int(edit.get('pinned',bool(row['is_pinned'])))})
        return {'version':edit['version']+1}
    if q.kind in ('answer_feedback','answer_feedback_get'):
        try:UUID(q.name)
        except ValueError:raise HTTPException(422,'运行标识无效') from None
        async with database.transaction():
            run=await database.fetch_one("SELECT r.status FROM agent_run r JOIN ai_conversation c ON c.conversation_id=r.conversation_id AND c.user_id=r.user_id WHERE r.run_id=:rid AND r.user_id=:uid AND c.status=1 FOR UPDATE",{'rid':q.name,'uid':uid})
            if not run:raise HTTPException(404,'运行不存在或无权访问')
            run=dict(run._mapping)
            if q.kind=='answer_feedback':
                edit=decode_object(q.edit);rating=edit.get('rating');reason=edit.get('reason','');comment=edit.get('comment','')
                if rating not in ('helpful','problem','') or reason not in ('','irrelevant','incorrect','citation','incomplete','other') or not isinstance(comment,str) or len(comment)>500:raise HTTPException(422,'反馈内容无效')
                if run['status']!='succeeded':raise HTTPException(409,'回答尚未完成')
                if rating=='':await database.execute('DELETE FROM agent_answer_feedback WHERE run_id=:rid AND user_id=:uid',{'rid':q.name,'uid':uid})
                else:await database.execute("""INSERT INTO agent_answer_feedback(run_id,user_id,rating,reason,comment) VALUES(:rid,:uid,:rating,:reason,:comment)
                    ON DUPLICATE KEY UPDATE rating=VALUES(rating),reason=VALUES(reason),comment=VALUES(comment),updated_at=UTC_TIMESTAMP(6)""",{'rid':q.name,'uid':uid,'rating':rating,'reason':reason if rating=='problem' else '','comment':comment.strip()})
            row=await database.fetch_one('SELECT rating,reason,comment,updated_at FROM agent_answer_feedback WHERE run_id=:rid AND user_id=:uid',{'rid':q.name,'uid':uid})
        return dict(row._mapping) if row else None
    if q.kind=='feedback_report':
        if q.source not in ('business','evaluation','all'):raise HTTPException(422,'指标来源无效')
        values=pagination(q)
        where='' if q.source=='all' else ' WHERE r.data_source=:source'
        if q.source!='all':values['source']=q.source
        rows=await database.fetch_all('SELECT f.run_id,f.rating,f.reason,f.created_at,f.updated_at,r.data_source FROM agent_answer_feedback f JOIN agent_run r ON r.run_id=f.run_id'+where+' ORDER BY f.updated_at DESC,f.run_id LIMIT :limit OFFSET :offset',values)
        counts=await database.fetch_all('SELECT f.rating,f.reason,COUNT(*) AS count FROM agent_answer_feedback f JOIN agent_run r ON r.run_id=f.run_id'+where+' GROUP BY f.rating,f.reason',{} if q.source=='all' else {'source':q.source})
        return {'rows':[dict(r._mapping) for r in rows],'counts':[dict(r._mapping) for r in counts]}
    raise HTTPException(422,'查询类型无效')
