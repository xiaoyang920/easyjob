"""Real gateway/Auth/Blog/Agent checks with disposable accounts; no model or email calls."""
import asyncio,hashlib,json,secrets,statistics,sys,time
from datetime import datetime,timezone
from pathlib import Path
import httpx,jwt
from redis.asyncio import Redis
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.config import settings

async def main():
    checks=[];ids=[];sids=set();emails=[];password='Auth-test-'+secrets.token_hex(12)
    started=datetime.now(timezone.utc).isoformat()
    redis=Redis(host=settings.REDIS_HOST,port=settings.REDIS_PORT,db=settings.REDIS_DB,password=settings.REDIS_PASSWORD or None,decode_responses=True)
    def expect(name,condition):
        checks.append({'name':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    def auth(token):return {'Authorization':'Bearer '+token}
    await db.connect()
    try:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8090',timeout=15,trust_env=False,follow_redirects=False) as admin,httpx.AsyncClient(base_url='http://127.0.0.1:8090',timeout=15,trust_env=False,follow_redirects=False) as user:
            response=await admin.get('/api/article/list',params={'page':1,'size':1});expect('anonymous_article_read',response.status_code==200)
            response=await admin.get('/api/account/sessions');expect('protected_requires_login',response.status_code==401)
            response=await admin.get('/api/account/sessions',headers={'X-User-Id':'1','X-Easyjob-Identity':'forged'});expect('forged_identity_headers_rejected',response.status_code==401)
            response=await admin.get('/api/auth/jwks');keys=response.json()['keys'];expect('jwks_contains_public_keys_only',len(keys)>=1 and all('d' not in key for key in keys))
            tokens=[]
            for index,client in enumerate((admin,user)):
                tag=secrets.token_hex(5);email=f'auth-smoke-{tag}@example.invalid';emails.append(email);code='123456'
                await redis.set('auth:v2:code:login:'+hashlib.sha256(email.encode()).hexdigest(),hashlib.sha256((email+':'+code).encode()).hexdigest(),ex=600)
                response=await client.post('/api/auth/register',json={'email':email,'password':password,'nickName':'auth-'+tag,'code':code})
                expect('register_'+str(index),response.status_code==200)
                data=response.json()['data'];ids.append(int(data['userId']));token=data['token'];tokens.append(token);sids.add(jwt.decode(token,options={'verify_signature':False})['sid'])
                expect('rs256_token_'+str(index),jwt.get_unverified_header(token)['alg']=='RS256')
                expect('http_only_refresh_cookie_'+str(index),'httponly' in response.headers.get('set-cookie','').lower())
            # Grant admin only to this disposable fixture through direct setup SQL.
            await db.execute('UPDATE user_info SET role=2 WHERE user_id=:uid',{'uid':ids[0]})
            a,b=tokens
            response=await user.post('/api/auth/login',json={'email':emails[1],'password':'incorrect'});expect('wrong_password_rejected',response.status_code==401)
            response=await user.get('/api/account/sessions',headers=auth(b));expect('authenticated_account_request',response.status_code==200)
            response=await user.post('/api/auth/refresh',headers={'X-Auth-Refresh':'1','Authorization':'Bearer expired'});expect('refresh_uses_cookie_with_expired_access',response.status_code==200)
            b=response.json()['data']['token']
            response=await user.post('/api/auth/refresh');expect('refresh_requires_csrf_marker',response.status_code==403)
            response=await user.get(f'/api/user/space/{ids[1]}',headers=auth(b))
            expect('profile_read_with_restricted_database_user',response.status_code==200 and response.json()['data']['email']==emails[1])
            response=await admin.get(f'/api/user/space/{ids[1]}')
            expect('anonymous_profile_hides_email',response.status_code==200 and response.json()['data'].get('email') is None)
            response=await admin.get('/api/article/list',headers={'Authorization':'Bearer invalid'})
            expect('invalid_optional_identity_rejected',response.status_code==401)
            before=dict(await db.fetch_one('SELECT password,role,status,auth_version FROM user_info WHERE user_id=:uid',{'uid':ids[1]}))
            response=await user.put('/api/user/update',headers=auth(b),json={'nickName':'auth-updated-'+secrets.token_hex(3),'personIntroduction':'disposable integration fixture','role':2,'status':0,'password':'forged-password'})
            expect('profile_update_with_restricted_database_user',response.status_code==200 and response.json()['code']==200)
            after=dict(await db.fetch_one('SELECT password,role,status,auth_version FROM user_info WHERE user_id=:uid',{'uid':ids[1]}))
            expect('profile_update_cannot_change_credentials_or_role',before==after)
            for name,path in [('drafts','/api/article/drafts'),('private_chat','/api/chat/conversations'),('social_contacts','/api/social/contacts'),('notifications','/api/notification/unread-count')]:
                response=await user.get(path,headers=auth(b))
                expect(name+'_with_restricted_database_user',response.status_code==200 and response.json()['code']==200)
            response=await user.get('/api/agent/conversations',headers=auth(b));expect('gateway_blog_agent_delegation',response.status_code==200)
            async with httpx.AsyncClient(timeout=5,trust_env=False) as direct:
                response=await direct.get('http://127.0.0.1:8080/api/agent/conversations',headers=auth(b));expect('direct_blog_bypass_rejected',response.status_code==401)
                response=await direct.post('http://127.0.0.1:8081/internal/auth/session/check',json={'userId':str(ids[1]),'sid':'a'*64,'version':0});expect('internal_auth_requires_service_identity',response.status_code==401)
            # Real socket revocation checks the active connection, not only a new request.
            import websockets
            async with websockets.connect('ws://127.0.0.1:8090/ws/chat?token='+b,open_timeout=10) as socket:
                await asyncio.wait_for(socket.recv(),5)
                response=await user.post('/api/auth/logout',headers={'X-Auth-Refresh':'1'});expect('logout_success',response.status_code==200)
                try:
                    while True:await asyncio.wait_for(socket.recv(),8)
                except websockets.exceptions.ConnectionClosed:expect('logout_closes_existing_websocket',True)
            response=await user.get('/api/account/sessions',headers=auth(b));expect('revoked_access_rejected',response.status_code==401)
            response=await user.post('/api/auth/refresh',headers={'X-Auth-Refresh':'1'});expect('logout_cannot_refresh_back',response.status_code==401)
            response=await user.post('/api/auth/login',json={'email':emails[1],'password':password});expect('password_login',response.status_code==200);b=response.json()['data']['token'];sids.add(jwt.decode(b,options={'verify_signature':False})['sid'])
            # Two simultaneous devices; revoke only the second device.
            async with httpx.AsyncClient(base_url='http://127.0.0.1:8090',trust_env=False,timeout=15) as other:
                response=await other.post('/api/auth/login',json={'email':emails[1],'password':password});expect('second_device_login',response.status_code==200);c=response.json()['data']['token'];sid=jwt.decode(c,options={'verify_signature':False})['sid'];sids.add(sid)
                response=await user.delete('/api/account/sessions/'+sid,headers=auth(b));expect('revoke_one_device',response.status_code==200)
                expect('other_device_rejected',(await other.get('/api/account/sessions',headers=auth(c))).status_code==401)
                expect('current_device_retained',(await user.get('/api/account/sessions',headers=auth(b))).status_code==200)
            security=(await admin.get(f'/api/admin/accounts/{ids[1]}/security',headers=auth(a))).json()['data']
            response=await admin.put(f'/api/admin/accounts/{ids[1]}/security',headers=auth(a),json={'expectedVersion':security['version'],'role':1,'status':0,'commandId':__import__('uuid').uuid4().hex[:8]+'-'+str(__import__('uuid').uuid4())[9:],'reason':'disposable integration fixture'})
            expect('admin_can_disable_fixture',response.status_code==200)
            expect('disabled_token_rejected',(await user.get('/api/account/sessions',headers=auth(b))).status_code==401)
            expect('disabled_account_cannot_login',(await user.post('/api/auth/login',json={'email':emails[1],'password':password})).status_code==401)
            security=(await admin.get(f'/api/admin/accounts/{ids[1]}/security',headers=auth(a))).json()['data']
            response=await admin.put(f'/api/admin/accounts/{ids[1]}/security',headers=auth(a),json={'expectedVersion':security['version'],'role':1,'status':1,'commandId':str(__import__('uuid').uuid4()),'reason':'restore disposable fixture'})
            expect('admin_can_restore_fixture',response.status_code==200)
            response=await user.post('/api/auth/login',json={'email':emails[1],'password':password});expect('restored_account_login',response.status_code==200);b=response.json()['data']['token'];sids.add(jwt.decode(b,options={'verify_signature':False})['sid'])
            expect('old_version_cannot_return',(await user.get('/api/account/sessions',headers=auth(c))).status_code==401)
            samples=[]
            for _ in range(100):
                start=time.perf_counter();response=await user.get('/api/agent/conversations',headers=auth(b));samples.append((time.perf_counter()-start)*1000)
                if response.status_code!=200:raise AssertionError('warm_request_failed_'+str(response.status_code))
            expect('100_authenticated_warm_requests',True)
            newer=password+'x'
            response=await user.put('/api/account/password',headers=auth(b),json={'currentPassword':password,'newPassword':newer});expect('password_change_success',response.status_code==200)
            expect('password_change_revokes_previous_access',(await user.get('/api/agent/conversations',headers=auth(b))).status_code==401)
            expect('previous_password_rejected',(await user.post('/api/auth/login',json={'email':emails[1],'password':password})).status_code==401)
            response=await user.post('/api/auth/login',json={'email':emails[1],'password':newer});expect('new_password_login',response.status_code==200);b=response.json()['data']['token'];sids.add(jwt.decode(b,options={'verify_signature':False})['sid'])
            async with user.stream('GET','/api/notification/stream',headers=auth(b)) as stream:
                expect('notification_sse_connected',stream.status_code==200)
                lines=stream.aiter_lines();await asyncio.wait_for(anext(lines),5)
                response=await user.post('/api/auth/logout',headers={'X-Auth-Refresh':'1'});expect('logout_with_sse_connected',response.status_code==200)
                async def drained():
                    async for _ in lines:pass
                await asyncio.wait_for(drained(),8);expect('logout_closes_notification_sse',True)
            email=emails[1];code='654321';digest=hashlib.sha256(email.encode()).hexdigest()
            await redis.set('auth:v2:code:login:'+digest,hashlib.sha256((email+':'+code).encode()).hexdigest(),ex=600)
            response=await user.post('/api/auth/login-by-email',json={'email':email,'code':code})
            expect('email_code_login',response.status_code==200)
            b=response.json()['data']['token'];sids.add(jwt.decode(b,options={'verify_signature':False})['sid'])
            await redis.set('auth:v2:code:reset:'+digest,hashlib.sha256((email+':'+code).encode()).hexdigest(),ex=600)
            reset_password=newer+'y'
            response=await user.post('/api/auth/password/reset',json={'email':email,'code':code,'password':reset_password})
            expect('password_reset_with_verification_code',response.status_code==200)
            expect('password_reset_revokes_existing_session',(await user.get('/api/account/sessions',headers=auth(b))).status_code==401)
            expect('password_before_reset_rejected',(await user.post('/api/auth/login',json={'email':email,'password':newer})).status_code==401)
            response=await user.post('/api/auth/login',json={'email':email,'password':reset_password})
            expect('reset_password_can_login',response.status_code==200)
            sids.add(jwt.decode(response.json()['data']['token'],options={'verify_signature':False})['sid'])
            report={'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),'passed':len(checks),'checks':checks,'warm_requests':{'count':100,'p50_ms':round(statistics.median(samples),2),'p95_ms':round(sorted(samples)[94],2)},'model_calls':0,'emails_sent':0}
            (ROOT/'temp/unified-auth-smoke-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':len(checks),'warm_requests':report['warm_requests'],'model_calls':0,'emails_sent':0},ensure_ascii=False))
    finally:
        for sid in sids:await redis.delete('auth:v2:session:'+sid)
        for uid in ids:
            await redis.delete('auth:v2:devices:'+str(uid))
            await redis.delete('easyjob:userSpaceInfo:'+str(uid))
            await db.execute('DELETE FROM auth_outbox WHERE user_id=:uid',{'uid':uid});await db.execute('DELETE FROM auth_audit WHERE target_id=:uid OR actor_id=:uid',{'uid':uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid',{'uid':uid})
        for email in emails:
            digest=hashlib.sha256(email.encode()).hexdigest()
            for purpose in ('login','reset'):await redis.delete('auth:v2:code:'+purpose+':'+digest,'auth:v2:code:'+purpose+':'+digest+':attempts')
        await redis.aclose();await db.disconnect()
if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as error:print('Unified auth smoke failed:',type(error).__name__,str(error) if isinstance(error,AssertionError) else 'inspect sanitized service logs');raise SystemExit(1)
