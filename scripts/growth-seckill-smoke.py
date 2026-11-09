"""Disposable local concurrency/fault checks. Never changes a real user's coins."""
import asyncio, json, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4
import httpx, jwt, yaml
from redis.asyncio import Redis
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from evaluation.context_extended_live import identity, login

async def main():
    checks=[];fixtures=[];activities=[];clients=[];sids=[]
    redis=Redis(host=settings.REDIS_HOST,port=settings.REDIS_PORT,db=settings.REDIS_DB,password=settings.REDIS_PASSWORD or None,decode_responses=True)
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)});print(('PASS ' if value else 'FAIL ')+name,flush=True)
        assert value,name
    async def until(work,predicate,seconds=25):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            value=await work()
            if predicate(value):return value
            await asyncio.sleep(.25)
        raise AssertionError('Timed out waiting for asynchronous effect')
    async def post(client,path,data=None):return (await client.post('/api/growth'+path,json=data)).json()
    async def activity(stock=1,pay=120):
        now=datetime.now(timezone.utc)
        result=await post(clients[0],'/admin/activities',{'title':'smoke-'+uuid4().hex[:8],'stock':stock,'startsAt':(now-timedelta(seconds=5)).isoformat(),'endsAt':(now+timedelta(minutes=10)).isoformat(),'paySeconds':pay})
        assert result['code']==200,result.get('message')
        aid=result['data']['activityId'];activities.append(aid)
        assert (await post(clients[0],f'/admin/activities/{aid}/activate'))['code']==200
        return aid
    async def grab(index,aid):
        r=await post(clients[index],f'/activities/{aid}/reservations',{'requestId':str(uuid4())})
        assert r['code']==200,r.get('message')
        rid=r['data']['orderId']
        await until(lambda:db.fetch_one('SELECT * FROM growth_order WHERE order_id=:id',{'id':rid}),lambda r:bool(r))
        return rid
    def key(aid,suffix):return f'growth:{{{aid}}}:{suffix}'
    await db.connect()
    try:
        for index in range(9):
            fixture=await identity();fixtures.append(fixture)
            await db.execute('UPDATE user_info SET current_coin_count=10,total_coin_count=10,role=:role WHERE user_id=:uid',{'role':2 if index==0 else 1,'uid':fixture['user_id']})
            client=httpx.AsyncClient(base_url='http://127.0.0.1:8090',timeout=20,trust_env=False);clients.append(client)
            for attempt in range(30):
                try:
                    await login(client,fixture);break
                except httpx.HTTPStatusError as error:
                    if error.response.status_code!=429 or attempt==29:raise
                    await asyncio.sleep(2)
            sids.append(jwt.decode(client.headers['Authorization'][7:],options={'verify_signature':False})['sid'])
        async def gateway_ready():return (await clients[0].get('/api/growth/activities')).json().get('code')
        await until(gateway_ready,lambda code:code==200)
        check('non_admin_cannot_create_activity',(await post(clients[1],'/admin/activities',{}))['code']==403)
        aid=await activity(3)
        started=time.monotonic()
        replies=await asyncio.gather(*(post(clients[i],f'/activities/{aid}/reservations',{'requestId':str(uuid4())}) for i in range(1,9) for _ in range(10)))
        burst_ms=round((time.monotonic()-started)*1000)
        rows=await until(lambda:db.fetch_all('SELECT * FROM growth_order WHERE activity_id=:a',{'a':aid}),lambda r:len(r)==3)
        check('80_concurrent_requests_only_three_orders',len(rows)==3 and len({r['user_id'] for r in rows})==3)
        check('redis_and_mysql_stock_never_negative',await redis.get(key(aid,'stock'))=='0' and await db.fetch_val('SELECT available_stock FROM growth_activity WHERE activity_id=:a',{'a':aid})==0)
        check('duplicate_requests_return_same_order',all(len({r['data']['orderId'] for r in replies if r['code']==200 and r['data']['orderId']==o['order_id']})==1 for o in rows))
        by_uid={f['user_id']:i for i,f in enumerate(fixtures)}
        paid=rows[0];payer=by_uid[paid['user_id']];oid=paid['order_id']
        payments=await asyncio.gather(*(post(clients[payer],f'/orders/{oid}/pay') for _ in range(20)))
        check('20_duplicate_payments_idempotent',all(r['code']==200 and r['data']['state']=='PAID' for r in payments))
        check('charged_once',await db.fetch_val('SELECT current_coin_count FROM user_info WHERE user_id=:u',{'u':paid['user_id']})==0 and await db.fetch_val('SELECT COUNT(*) FROM coin_ledger WHERE order_id=:o',{'o':oid})==1)
        progress=await db.fetch_one('SELECT * FROM user_reading_progress WHERE user_id=:u',{'u':paid['user_id']})
        check('growth_once_without_fabricating_reading',progress['total_millis']==0 and progress['purchased_millis']==1800000 and await db.fetch_val('SELECT COUNT(*) FROM growth_ledger WHERE order_id=:o',{'o':oid})==1)
        check('foreign_order_payment_rejected',(await post(clients[0],f'/orders/{oid}/pay'))['code']==404)
        poor=rows[1];poor_index=by_uid[poor['user_id']]
        await db.execute('UPDATE user_info SET current_coin_count=0 WHERE user_id=:u',{'u':poor['user_id']})
        check('insufficient_balance_keeps_pending',(await post(clients[poor_index],f"/orders/{poor['order_id']}/pay"))['code']==409 and await db.fetch_val('SELECT state FROM growth_order WHERE order_id=:o',{'o':poor['order_id']})=='PENDING')
        losers=[i for i in range(1,9) if fixtures[i]['user_id'] not in {r['user_id'] for r in rows}]
        spender=losers[0];a1=await activity();a2=await activity();o1=await grab(spender,a1);o2=await grab(spender,a2)
        results=await asyncio.gather(post(clients[spender],f'/orders/{o1}/pay'),post(clients[spender],f'/orders/{o2}/pay'))
        check('different_orders_cannot_overspend',sum(r['code']==200 and r['data']['state']=='PAID' for r in results)==1 and await db.fetch_val('SELECT current_coin_count FROM user_info WHERE user_id=:u',{'u':fixtures[spender]['user_id']})==0)
        pending_id=await db.fetch_val("SELECT order_id FROM growth_order WHERE user_id=:u AND state='PENDING' AND activity_id IN (:a,:b)",{'u':fixtures[spender]['user_id'],'a':a1,'b':a2})
        await db.execute('UPDATE user_info SET current_coin_count=10 WHERE user_id=:u',{'u':fixtures[spender]['user_id']})
        await db.execute("INSERT INTO growth_ledger(user_id,order_id,business_type,delta_millis) VALUES(:u,:o,'PURCHASE',1800000)",{'u':fixtures[spender]['user_id'],'o':pending_id})
        failure=await post(clients[spender],f'/orders/{pending_id}/pay')
        check('mid_transaction_failure_rolls_back_debit',failure['code']!=200 and await db.fetch_val('SELECT current_coin_count FROM user_info WHERE user_id=:u',{'u':fixtures[spender]['user_id']})==10 and await db.fetch_val('SELECT COUNT(*) FROM coin_ledger WHERE order_id=:o',{'o':pending_id})==0 and await db.fetch_val('SELECT purchased_millis FROM user_reading_progress WHERE user_id=:u',{'u':fixtures[spender]['user_id']})==1800000)
        await db.execute('DELETE FROM growth_ledger WHERE order_id=:o',{'o':pending_id})
        expiry=await activity(pay=10);timeout_id=await grab(losers[1],expiry)
        await until(lambda:db.fetch_val('SELECT state FROM growth_order WHERE order_id=:o',{'o':timeout_id}),lambda s:s=='CLOSED')
        await until(lambda:redis.get(key(expiry,'stock')),lambda n:n=='1')
        check('timeout_closes_and_restores_both_stocks',await db.fetch_val('SELECT available_stock FROM growth_activity WHERE activity_id=:a',{'a':expiry})==1)
        lua=(ROOT/'src/main/resources/growth/release.lua').read_text()
        for _ in range(3):await redis.eval(lua,4,key(expiry,'ready'),key(expiry,'stock'),key(expiry,'reservations'),key(expiry,'released'),expiry,timeout_id)
        check('duplicate_compensation_restores_once',await redis.get(key(expiry,'stock'))=='1')
        check('closed_order_cannot_pay',(await post(clients[losers[1]],f'/orders/{timeout_id}/pay'))['code']==409)
        # Re-deliver the original broker payload to prove database consumer idempotency.
        config=yaml.safe_load((ROOT/'src/main/resources/application.yml').read_text(encoding='utf-8')).get('spring',{}).get('rabbitmq',{})
        config.update(yaml.safe_load((ROOT/'temp/application-runtime.yml').read_text(encoding='utf-8')).get('spring',{}).get('rabbitmq',{}))
        receipt=await redis.hget(key(aid,'reservations'),oid)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:15672',auth=(config.get('username','guest'),config.get('password','guest')),trust_env=False) as management:
            response=await management.post('/api/exchanges/%2F/growth.orders/publish',json={'properties':{'content_type':'application/json','delivery_mode':2},'routing_key':'growth.orders.create','payload':receipt,'payload_encoding':'string'})
            response.raise_for_status();check('duplicate_broker_event_routed',response.json()['routed'])
        await asyncio.sleep(1)
        check('duplicate_consumer_does_not_deduct_stock_twice',await db.fetch_val('SELECT available_stock FROM growth_activity WHERE activity_id=:a',{'a':aid})==0 and await db.fetch_val('SELECT COUNT(*) FROM growth_order WHERE activity_id=:a',{'a':aid})==3)
        audit=(await clients[0].get('/api/growth/admin/activities/'+aid+'/audit')).json()
        check('admin_audit_database_and_redis_agree',audit['code']==200 and audit['data']['databaseStockConsistent'] and audit['data']['redisStock']=='0')
        paused=await activity()
        check('admin_can_pause',(await post(clients[0],f'/admin/activities/{paused}/pause'))['code']==200)
        check('paused_activity_rejects_new_claims',(await post(clients[losers[2]],f'/activities/{paused}/reservations',{'requestId':str(uuid4())}))['code'] in (409,503))
        check('consistent_activity_can_resume',(await post(clients[0],f'/admin/activities/{paused}/resume'))['code']==200)
        check('non_admin_cannot_pause',(await post(clients[1],f'/admin/activities/{paused}/pause'))['code']==403)
        # Simulate loss of one Redis user claim; SQL uniqueness must release the second reservation.
        collision=await activity(stock=2)
        original=await grab(losers[2],collision)
        await redis.hdel(key(collision,'users'),str(fixtures[losers[2]]['user_id']))
        duplicate=await post(clients[losers[2]],f'/activities/{collision}/reservations',{'requestId':str(uuid4())})
        check('duplicate_claim_readmitted_after_cache_loss',duplicate['code']==200 and duplicate['data']['orderId']!=original)
        await until(lambda:redis.get(key(collision,'stock')),lambda n:n=='1')
        check('unique_buyer_collision_releases_extra_reservation',await db.fetch_val('SELECT COUNT(*) FROM growth_order WHERE activity_id=:a',{'a':collision})==1 and await redis.get(key(collision,'stock'))=='1')
        lookup=(await clients[losers[2]].get('/api/growth/activities/'+collision+'/reservations/'+duplicate['data']['orderId'])).json()
        check('duplicate_claim_resolves_original_order',lookup['code']==200 and lookup['data']['orderId']==original)
        lost=await activity();await redis.delete(key(lost,'ready'),key(lost,'stock'))
        check('missing_redis_state_fails_closed',(await post(clients[losers[2]],f'/activities/{lost}/reservations',{'requestId':str(uuid4())}))['code']==503)
        check('active_activity_not_silently_reinitialized',(await post(clients[0],f'/admin/activities/{lost}/activate'))['code']==503)
        check('lost_state_cannot_resume_without_reconciliation',(await post(clients[0],f'/admin/activities/{lost}/pause'))['code']==200 and (await post(clients[0],f'/admin/activities/{lost}/resume'))['code']==409)
        report={'passed':len(checks),'burst_requests':80,'burst_ms':burst_ms,'checks':checks}
        (ROOT/'temp/growth-smoke-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='checks'}),flush=True)
    finally:
        # Stop fixture admission before removing its exact rows; leave unrelated activities alone.
        for fixture in fixtures:
            for row in await db.fetch_all('SELECT activity_id FROM growth_activity WHERE created_by=:u',{'u':fixture['user_id']}):
                if row['activity_id'] not in activities:activities.append(row['activity_id'])
        for aid in activities:
            await db.execute("UPDATE growth_activity SET state='PAUSED' WHERE activity_id=:a",{'a':aid})
        for fixture in fixtures:
            uid=fixture['user_id']
            for table in ('coin_ledger','growth_ledger'):await db.execute(f'DELETE FROM {table} WHERE user_id=:u',{'u':uid})
            await db.execute('DELETE FROM user_reading_progress WHERE user_id=:u',{'u':uid})
        for aid in activities:
            await db.execute('DELETE FROM growth_outbox WHERE activity_id=:a',{'a':aid});await db.execute('DELETE FROM growth_order WHERE activity_id=:a',{'a':aid});await db.execute('DELETE FROM growth_activity WHERE activity_id=:a',{'a':aid})
            keys=[k async for k in redis.scan_iter(match=f'growth:{{{aid}}}:*')]
            if keys:await redis.delete(*keys)
        for sid in sids:await redis.delete('auth:v2:session:'+sid)
        for fixture in fixtures:
            uid=fixture['user_id'];await redis.delete('auth:v2:devices:'+str(uid))
            await db.execute('DELETE FROM auth_audit WHERE actor_id=:u OR target_id=:u',{'u':uid});await db.execute('DELETE FROM auth_outbox WHERE user_id=:u',{'u':uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:u AND email=:e',{'u':uid,'e':fixture['email']})
        for client in clients:await client.aclose()
        await redis.aclose();await db.disconnect()

if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as error:
        print('Smoke failed:',type(error).__name__,str(error) if isinstance(error,AssertionError) else 'inspect service logs',flush=True);raise SystemExit(1)
