"""Bounded, leased MySQL/ES reconciliation. Repairs reuse existing durable queues."""
import asyncio
import hashlib
import json
import logging
import re
from html import unescape
from uuid import uuid4
from time import monotonic
from app.clients.mysql_client import db
from app.clients.es_client import BaseEsClient
from app.services.durable_jobs import DurableJobs
from app.rpc.blog_client import maintenance

log=logging.getLogger(__name__)

def article_fingerprint(row):
    return tuple(row.get(k) for k in ('content','title','tags','category_id','user_id','status','deleted','required_level','update_time'))

def memory_fingerprint(row):
    return tuple(row.get(k) for k in ('content','user_id','memory_type','status','scope','scope_conversation_id','importance'))

def article_difference(row,source,chunks):
    public=row['status']==1 and row['deleted']==0
    if not public:return 'private_index' if source or chunks else None
    if not source:return 'missing_document'
    for field,column in [('title','title'),('content','content'),('summary','summary'),('tags','tags'),('categoryId','category_id')]:
        if str(source.get(field) or '')!=str(row.get(column) or ''):return 'document_version'
    if int(source.get('status',0))!=1:return 'document_visibility'
    if row['required_level']>0:return 'restricted_chunks' if chunks else None
    text=unescape(re.sub('<[^>]+>','',re.sub(r'<(script|style)\b[^>]*>.*?</\1>','',row['content'] or '',flags=re.S|re.I))).strip()
    if text and not chunks:return 'missing_chunks'
    expected=hashlib.sha256((row['content'] or '').encode()).hexdigest()
    if any(c.get('source_hash')!=expected or c.get('chunker_version')!='html-dom-v1' or c.get('title')!=row['title'] for c in chunks):return 'chunk_version'
    if len(chunks)>512:return 'excess_chunks'
    indices=sorted(c.get('chunk_index',-1) for c in chunks)
    if indices!=list(range(len(chunks))):return 'incomplete_chunks'
    if any(c.get('chunk_count') is not None and c['chunk_count']!=len(chunks) for c in chunks):return 'incomplete_chunks'
    return 'view_count' if int(source.get('viewCount') or 0)<row['view_count'] else None

def memory_difference(row,source):
    active=row['status']=='active' and row['memory_type']=='decision'
    if not active:return bool(source)
    if not source:return True
    return any(str(source.get(f) or '')!=str(row.get(c) or '') for f,c in
        [('content','content'),('user_id','user_id'),('memory_type','memory_type'),('scope','scope'),('scope_conversation_id','scope_conversation_id')])

class IndexReconciliation:
    BATCH=20
    def __init__(self,database=db,es=None):self.db=database;self.es=es
    async def claim(self):
        async with self.db.transaction():
            row=await self.db.fetch_one("""SELECT * FROM maintenance_cursor WHERE next_at<=UTC_TIMESTAMP(6)
                AND (lease_until IS NULL OR lease_until<=UTC_TIMESTAMP(6)) ORDER BY next_at,kind LIMIT 1 FOR UPDATE SKIP LOCKED""")
            if not row:return None
            task=dict(row._mapping);task['token']=str(uuid4())
            await self.db.execute("UPDATE maintenance_cursor SET lease_token=:t,lease_until=TIMESTAMPADD(SECOND,120,UTC_TIMESTAMP(6)) WHERE kind=:k",{'t':task['token'],'k':task['kind']})
            return task
    async def article_repair(self,prior,difference,aid=None):
        aid=aid or prior['article_id']
        return await maintenance('article_repair', target_id=aid, name=difference, expected=prior)
    async def memory_repair(self,prior,mid=None,uid=None):
        mid=mid or prior['memory_id']
        async with self.db.transaction():
            row=await self.db.fetch_one('SELECT * FROM user_memory WHERE memory_id=:id FOR UPDATE',{'id':mid})
            if prior and (not row or memory_fingerprint(dict(row._mapping))!=memory_fingerprint(prior)):return False
            if not prior and row:return False
            uid=prior['user_id'] if prior else uid
            # A JSON id match suppresses duplicate intents while a task is pending/dead.
            if await self.db.fetch_val("""SELECT COUNT(*) FROM agent_background_job WHERE kind='memory_index' AND user_id=:uid
                AND status IN ('pending','running','dead') AND (JSON_CONTAINS(JSON_EXTRACT(payload,'$.ids'),:mid)
                OR JSON_CONTAINS(JSON_EXTRACT(payload,'$.ids'),:number))""",{'uid':uid,'mid':json.dumps(str(mid)),'number':str(mid)}):return False
            await DurableJobs(self.db).enqueue('reconcile-memory:'+str(uuid4()),'memory_index',uid,None,{'ids':[str(mid)]})
            return True
    async def batch(self,task,es):
        kind,last=task['kind'],task['last_id'];scanned=repaired=0;cursor=last;started=monotonic()
        es=es.options(ignore_status=[404])
        if kind=='chunk_orphan':
            composite={'size':self.BATCH,'sources':[{'article':{'terms':{'field':'article_id'}}}]}
            if task.get('last_key'):composite['after']={'article':task['last_key']}
            response=await es.search(index='article_vectors',size=0,aggregations={'articles':{'composite':composite}})
            buckets=response.get('aggregations',{}).get('articles',{}).get('buckets',[])
            for bucket in buckets:
                key=bucket['key']['article'];task['last_key']=key;scanned+=1
                if not key.isdigit() or not 0<int(key)<2**63:continue
                current=await maintenance('article_lookup',target_id=int(key))
                if not current:repaired+=await self.article_repair(None,'orphan',int(key))
                elif current['status']!=1 or current['deleted']!=0 or current['required_level']>0:
                    repaired+=await self.article_repair(current,'restricted_chunks')
            more=len(buckets)==self.BATCH
            if not more:task['last_key']=None
            return 0,scanned,repaired,more
        if kind in ('article','memory'):
            key='article_id' if kind=='article' else 'memory_id'
            rows=await maintenance('article_scan',cursor=last) if kind=='article' else await self.db.fetch_all(
                'SELECT * FROM user_memory WHERE memory_id>:last ORDER BY memory_id LIMIT :size',{'last':last,'size':self.BATCH})
            for item in rows:
                if scanned and monotonic()-started>=10:break
                row=dict(item) if kind=='article' else dict(item._mapping);cursor=row[key];scanned+=1
                if kind=='article':
                    row=await maintenance('article_lookup',target_id=cursor)
                    if not row:continue
                index='article' if kind=='article' else 'user_memories'
                found=await es.get(index=index,id=str(cursor),source_excludes=['content_vector'])
                source=found.get('_source') if found.get('found') else None
                if kind=='article':
                    response=await es.search(index='article_vectors',query={'term':{'article_id':str(cursor)}},size=513,source_includes=['source_hash','chunker_version','chunk_index','chunk_count','title'])
                    chunks=[h['_source'] for h in response.get('hits',{}).get('hits',[])]
                    difference=article_difference(row,source,chunks)
                    if difference:repaired+=await self.article_repair(row,difference)
                elif memory_difference(row,source):repaired+=await self.memory_repair(row)
            more=len(rows)==self.BATCH or scanned<len(rows)
            return (cursor if more else 0),scanned,repaired,more
        # Scan ES as well, so hard-deleted MySQL records are not missed by the DB sweep.
        index,field=('article','articleId') if kind=='article_orphan' else ('user_memories','memory_id')
        response=await es.search(index=index,query={'range':{field:{'gt':last}}},sort=[{field:'asc'}],size=self.BATCH,source_includes=[field,'user_id'])
        hits=response.get('hits',{}).get('hits',[])
        for hit in hits:
            row=hit['_source'];cursor=int(row[field]);scanned+=1
            if str(hit['_id'])!=str(cursor):continue
            current=await maintenance('article_lookup',target_id=cursor) if kind=='article_orphan' else await self.db.fetch_one(
                'SELECT * FROM user_memory WHERE memory_id=:id',{'id':cursor})
            if current:continue
            if kind=='article_orphan':repaired+=await self.article_repair(None,'orphan',cursor)
            elif row.get('user_id'):repaired+=await self.memory_repair(None,cursor,int(row['user_id']))
        return (cursor if len(hits)==self.BATCH else 0),scanned,repaired,len(hits)==self.BATCH
    async def tick(self):
        task=await self.claim()
        if not task:return False
        client=self.es or BaseEsClient().client
        try:
            cursor,scanned,repaired,more=await asyncio.wait_for(self.batch(task,client.options(request_timeout=3)),80)
            await self.db.execute("""UPDATE maintenance_cursor SET last_id=:id,last_key=:key,scanned=scanned+:s,repaired=repaired+:r,
                last_finished_at=UTC_TIMESTAMP(6),next_at=TIMESTAMPADD(SECOND,:delay,UTC_TIMESTAMP(6)),last_error=NULL,lease_until=NULL,lease_token=NULL
                WHERE kind=:k AND lease_token=:t AND lease_until>UTC_TIMESTAMP(6)""",{'id':cursor,'key':task.get('last_key'),'s':scanned,'r':repaired,'delay':60 if more else 900,'k':task['kind'],'t':task['token']})
        except Exception as error:
            await self.db.execute("""UPDATE maintenance_cursor SET next_at=TIMESTAMPADD(SECOND,60,UTC_TIMESTAMP(6)),last_error=:e,lease_until=NULL,lease_token=NULL
                WHERE kind=:k AND lease_token=:t AND lease_until>UTC_TIMESTAMP(6)""",{'e':type(error).__name__[:64],'k':task['kind'],'t':task['token']})
            log.warning('索引对账待重试: kind=%s error=%s',task['kind'],type(error).__name__)
        finally:
            if not self.es:await client.close()
        return True

index_reconciliation=IndexReconciliation()
