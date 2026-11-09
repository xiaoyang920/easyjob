"""Four-round acceptance: real isolated infrastructure, multi-JVM load and crash recovery.

Only owns resources named easyjob-growth-lab-<tag> / easyjob_growth_lab_<tag>.
Does not restart production services or write their data. Secrets stay in ignored temp/.
"""
import argparse,asyncio,collections,hashlib,json,os,re,secrets,socket,subprocess,sys,time,zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
import httpx,jwt,pymysql,yaml
from redis.asyncio import Redis
from redis.exceptions import RedisError
from growth_lab_support import RemoteProxy,process_sample,percentiles
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.config import settings

JAVA='D:/jdk/bin/java.exe'
DOCKER='C:/Program Files/Docker/Docker/resources/bin/docker.exe'

def free_port():
    with socket.socket() as connection:connection.bind(('127.0.0.1',0));return connection.getsockname()[1]


class Lab:
    def __init__(self):
        self.tag=secrets.token_hex(4);self.prefix='easyjob-growth-lab-'+self.tag
        self.schema='easyjob_growth_lab_'+self.tag;self.account='ej_growth_lab_'+self.tag
        self.folder=ROOT/'temp'/self.prefix;self.folder.mkdir()
        self.password=secrets.token_urlsafe(32);self.rabbit_password=secrets.token_urlsafe(32);self.service_key=secrets.token_urlsafe(48)
        self.ports={name:free_port() for name in ('redis','rabbit','management','auth','gateway','one','two')}
        self.processes={};self.logs=[];self.containers=[];self.proxies=[];self.checks=[];self.report={'run_id':self.tag,'scope':'isolated local gateway + real Auth + two production-growth JVM hosts','profiles':[],'faults':[]}
        self.sql=None;self.redis=None;self.client=None;self.management=None;self.redis_proxy=None;self.rabbit_proxy=None
        self.database_created=False;self.account_created=False
        self.owner_marker=self.folder/'owner.json'
        self.owner_marker.write_text(json.dumps({'owner':'growth-four-rounds','tag':self.tag,'schema':self.schema,'prefix':self.prefix}),encoding='utf-8')
    async def docker(self,*args):
        result=await asyncio.to_thread(subprocess.run,[DOCKER,*args],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError('Docker '+args[0]+' failed; inspect local lab state')
        return result.stdout.strip()
    def execute(self,sql,args=()):
        with self.sql.cursor() as cursor:cursor.execute(sql,args);return cursor.rowcount
    def rows(self,sql,args=()):
        with self.sql.cursor(pymysql.cursors.DictCursor) as cursor:cursor.execute(sql,args);return cursor.fetchall()
    def scalar(self,sql,args=()):
        with self.sql.cursor() as cursor:cursor.execute(sql,args);row=cursor.fetchone();return row[0] if row else None
    def save(self):
        (self.folder/'report.json').write_text(json.dumps(self.report|{'checks':self.checks},ensure_ascii=False,indent=2),encoding='utf-8')
    def check(self,name,value,**details):
        item={'name':name,'passed':bool(value),**details};self.checks.append(item);self.save()
        print(('PASS ' if value else 'FAIL ')+name,flush=True)
        if not value:raise AssertionError(name)
    async def until(self,work,predicate=lambda x:bool(x),timeout=60):
        end=time.monotonic()+timeout;last=None
        while time.monotonic()<end:
            try:last=await work() if asyncio.iscoroutinefunction(work) else work()
            except (httpx.HTTPError,OSError,ConnectionError,RedisError):last=None
            if predicate(last):return last
            await asyncio.sleep(.2)
        raise AssertionError('Timed out waiting for lab condition')
    def launch(self,name,config,kind='blog'):
        log=(self.folder/(name+'.log')).open('a',encoding='utf-8');self.logs.append(log)
        options=[JAVA,'-Xms48m','-Xmx256m','-XX:ActiveProcessorCount=2','-Duser.timezone=Asia/Shanghai']
        if kind=='blog':
            cp=(ROOT/'target/growth-lab-classpath.txt').read_text().strip()
            classpath=(str(ROOT/'target/growth-build/test-classes')+';'+str(ROOT/'target/growth-build/classes')+';'+cp).replace('\\','/')
            argfile=self.folder/(name+'-classpath.args')
            argfile.write_text('-cp\n"'+classpath+'"\ncom.easyjob.growth.GrowthLabApplication\n',encoding='utf-8')
            options+=['@'+str(argfile)]
        else:
            jar=ROOT/('auth-service/target/easyjob-auth-0.0.1-SNAPSHOT.jar' if kind=='auth' else 'gateway/target/easyjob-gateway-0.0.1-SNAPSHOT.jar')
            options+=['-jar',str(jar)]
        options+=['--spring.config.location='+config.as_uri()]
        process=subprocess.Popen(options,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes[name]=process;return process
    async def healthy(self,name):
        self.report['phase']='health:'+name;self.save()
        async def probe():
            if self.processes[name].poll() is not None:raise AssertionError('Lab process exited: '+name)
            response=await self.client.get(f'http://127.0.0.1:{self.ports[name]}/actuator/health')
            return response.status_code==200
        await self.until(probe,timeout=120)
        print('HEALTHY '+name,flush=True)
    async def prepare(self):
        assert settings.MYSQL_HOST in ('127.0.0.1','localhost'), 'Lab requires local MySQL'
        self.sql=pymysql.connect(host=settings.MYSQL_HOST,port=settings.MYSQL_PORT,user=settings.MYSQL_USER,password=settings.MYSQL_PASSWORD,autocommit=True)
        self.execute('CREATE DATABASE `'+self.schema+'` CHARACTER SET utf8mb4')
        self.database_created=True
        self.execute('USE `'+self.schema+'`')
        for table in ('user_info','reading_level_rule','user_reading_progress','reading_session','user_reading_daily','growth_activity','growth_order','coin_ledger','growth_ledger','growth_outbox','auth_audit','auth_outbox'):
            self.execute(f'CREATE TABLE `{table}` LIKE `{settings.MYSQL_DB}`.`{table}`')
        self.execute(f'INSERT INTO reading_level_rule SELECT * FROM `{settings.MYSQL_DB}`.reading_level_rule')
        self.execute("CREATE USER %s@'localhost' IDENTIFIED BY %s",(self.account,self.password))
        self.account_created=True
        self.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON `'+self.schema+"`.* TO %s@'localhost'",(self.account,))
        with self.sql.cursor() as cursor:
            cursor.executemany("INSERT INTO user_info(user_id,email,nick_name,password,status,role,auth_version,join_time,current_coin_count,total_coin_count,sex,theme,article_count,follower_count,following_count,data_source) VALUES(%s,%s,%s,'lab-no-password-login',1,%s,0,NOW(),100,100,2,1,0,0,0,'evaluation')",[(i,f'lab-{i}@example.invalid',f'lab-{i}',2 if i==1 else 1) for i in range(1,1501)])
        await self.docker('run','-d','--name',self.prefix+'-redis','--label','easyjob.growth-lab='+self.tag,'--memory','192m','-p',f"127.0.0.1:{self.ports['redis']}:6379",'redis:7.4','redis-server','--appendonly','yes','--appendfsync','always','--maxmemory','128mb','--maxmemory-policy','noeviction')
        self.containers.append(self.prefix+'-redis')
        rabbit_env=self.folder/'rabbit.env';rabbit_env.write_text('RABBITMQ_DEFAULT_USER=growthlab\nRABBITMQ_DEFAULT_PASS='+self.rabbit_password+'\nRABBITMQ_SERVER_ADDITIONAL_ERL_ARGS=+S 2:2\n')
        await self.docker('run','-d','--name',self.prefix+'-rabbit','--label','easyjob.growth-lab='+self.tag,'--memory','384m','--env-file',str(rabbit_env),'-p',f"127.0.0.1:{self.ports['rabbit']}:5672",'-p',f"127.0.0.1:{self.ports['management']}:15672",'rabbitmq:4.1-management')
        self.containers.append(self.prefix+'-rabbit')
        self.redis=Redis(port=self.ports['redis'],decode_responses=True,socket_timeout=2,socket_connect_timeout=2)
        self.client=httpx.AsyncClient(timeout=15,trust_env=False,limits=httpx.Limits(max_connections=320,max_keepalive_connections=320))
        self.management=httpx.AsyncClient(base_url=f"http://127.0.0.1:{self.ports['management']}",auth=('growthlab',self.rabbit_password),timeout=3,trust_env=False)
        async def redis_up():return await self.redis.ping()
        async def rabbit_up():return (await self.management.get('/api/overview')).status_code==200
        await self.until(redis_up);await self.until(rabbit_up,timeout=120)
        self.redis_proxy=RemoteProxy(self.ports['redis'],self.folder,'redis-proxy');self.rabbit_proxy=RemoteProxy(self.ports['rabbit'],self.folder,'rabbit-proxy');self.proxies=[self.redis_proxy,self.rabbit_proxy]
        redis_proxy_port=await self.redis_proxy.start();rabbit_proxy_port=await self.rabbit_proxy.start()
        self.processes['redis-proxy']=self.redis_proxy.process;self.processes['rabbit-proxy']=self.rabbit_proxy.process
        # Generate ephemeral test keys; never copy a production private key.
        import runpy
        runpy.run_path(str(ROOT/'scripts/generate-auth-keys.py'))['generate'](self.folder/'keys')
        auth_key=json.loads((self.folder/'keys/auth-private.json').read_text());self.auth_key=jwt.PyJWK.from_dict(auth_key).key;self.auth_kid=auth_key['kid']
        self.tokens={};pipe=self.redis.pipeline()
        for uid in range(1,1501):
            now=int(time.time());sid=hashlib.sha256((self.tag+':'+str(uid)).encode()).hexdigest()
            claims={'iss':'easyjob-auth','aud':'easyjob-api','sub':str(uid),'sid':sid,'ver':0,'iat':now,'nbf':now-1,'exp':now+7200,'jti':str(uuid4()),'token_use':'access','kind':'user'}
            self.tokens[uid]=jwt.encode(claims,self.auth_key,algorithm='RS256',headers={'kid':self.auth_kid})
            pipe.set('auth:v2:session:'+sid,json.dumps({'uid':uid,'ver':0,'deadline':int(time.time()*1000)+7200000,'createdAt':int(time.time()*1000),'userAgent':'isolated-growth-lab'}),ex=7200)
        await pipe.execute()
        ds={'url':f'jdbc:mysql://127.0.0.1:{settings.MYSQL_PORT}/{self.schema}?serverTimezone=GMT%2B8&useSSL=false&allowPublicKeyRetrieval=true&characterEncoding=utf8','username':self.account,'password':self.password,'hikari':{'maximum-pool-size':10,'minimum-idle':2}}
        common={'datasource':ds,'data':{'redis':{'host':'127.0.0.1','port':redis_proxy_port,'database':0,'timeout':'2s','connect-timeout':'2s'}},'rabbitmq':{'host':'127.0.0.1','port':rabbit_proxy_port,'username':'growthlab','password':self.rabbit_password,'publisher-confirm-type':'correlated','publisher-returns':True,'connection-timeout':'2s','requested-heartbeat':5},'cloud':{'consul':{'enabled':False,'discovery':{'enabled':False}}}}
        exclusions=[]
        for jar in (ROOT/'target/growth-lab-classpath.txt').read_text().strip().split(';'):
            if any(s in Path(jar).name for s in ('spring-ai','dubbo-spring-boot','spring-cloud-starter-alibaba')):
                try:
                    with zipfile.ZipFile(jar) as archive:
                        for entry in ('META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports',):
                            if entry in archive.namelist():exclusions.extend(line.strip() for line in archive.read(entry).decode().splitlines() if line.strip() and not line.startswith('#'))
                except OSError:pass
        for name in ('one','two'):
            config={'server':{'address':'127.0.0.1','port':self.ports[name]},'spring':common|{'profiles':{'active':'growth-lab'},'autoconfigure':{'exclude':exclusions}},'mybatis-plus':{'mapper-locations':'classpath:/mapper/ReadingGrowthMapper.xml'},'easyjob':{'auth':{'enabled':True,'gateway-public-key-file':str(self.folder/'keys/gateway-public.json')}},'lab':{'directory':str(self.folder),'instance':name},'management':{'endpoints':{'web':{'exposure':{'include':'health'}}}},'logging':{'level':{'root':'WARN','com.easyjob.growth':'INFO'}},'springdoc':{'api-docs':{'enabled':False}}}
            path=self.folder/(name+'.yml');path.write_text(yaml.safe_dump(config),encoding='utf-8');self.launch(name,path)
        auth_config={'server':{'address':'127.0.0.1','port':self.ports['auth']},'spring':common|{'data':{'redis':{'host':'127.0.0.1','port':self.ports['redis'],'database':0,'timeout':'2s'}},'rabbitmq':common['rabbitmq']|{'port':self.ports['rabbit']},'mail':{'host':'127.0.0.1','port':1,'username':'unused','password':'unused'}},'auth':{'issuer':'easyjob-auth','private-key-file':str(self.folder/'keys/auth-private.json'),'gateway-public-key-file':str(self.folder/'keys/gateway-public.json'),'service-key':self.service_key},'logging':{'level':{'root':'WARN'}}}
        auth_config['management']={'health':{'mail':{'enabled':False}},'endpoints':{'web':{'exposure':{'include':'health'}}}}
        path=self.folder/'auth.yml';path.write_text(yaml.safe_dump(auth_config),encoding='utf-8');self.launch('auth',path,'auth')
        gw={'server':{'address':'127.0.0.1','port':self.ports['gateway']},'spring':{'data':{'redis':{'host':'127.0.0.1','port':self.ports['redis'],'database':0,'timeout':'2s'}},'cloud':{'consul':{'enabled':False,'discovery':{'enabled':False}},'discovery':{'client':{'simple':{'instances':{'growth-lab':[{'uri':f'http://127.0.0.1:{self.ports[n]}'} for n in ('one','two')]}}}},'gateway':{'httpclient':{'connect-timeout':2000,'response-timeout':'20s'},'routes':[{'id':'growth-lab','uri':'lb://growth-lab','predicates':['Path=/api/growth/**,/api/reading/**']}]}}},'easyjob':{'jwt':{'secret-key':secrets.token_urlsafe(64)},'gateway':{'api-per-minute':20000,'auth-per-minute':20,'ai-per-minute':12},'auth':{'enabled':True,'base-url':f"http://127.0.0.1:{self.ports['auth']}",'jwks-uri':f"http://127.0.0.1:{self.ports['auth']}/api/auth/jwks",'issuer':'easyjob-auth','service-key':self.service_key,'gateway-private-key-file':str(self.folder/'keys/gateway-private.json')}},'management':{'endpoints':{'web':{'exposure':{'include':'health'}}}},'logging':{'level':{'root':'WARN'}}}
        gw['logging']['level']['com.easyjob.gateway.RequestTraceFilter']='INFO'
        path=self.folder/'gateway.yml';path.write_text(yaml.safe_dump(gw),encoding='utf-8');self.launch('gateway',path,'gateway')
        for name in ('one','two','auth','gateway'):await self.healthy(name)
        self.report['phase']='gateway-admission';self.save();await self.until(self.ready)
        self.report['environment']={'logical_cpus':os.cpu_count(),'jvm_heap_mb_each':256,'jvm_processor_count_each':2,'mysql_shared_host':True,'mysql_schema_isolated':True,'redis_aof':'always','broker':'RabbitMQ 4.1 classic durable queues','capacity_gateway_api_limit':20000,'capacity_gateway_ip_limit':60000,'production_limits_unchanged':True,'gateway_authentication':'real JWT verification + real Auth online session check; synthetic sessions only for fixture setup'}
        self.save();print('Isolated environment ready: '+self.tag,flush=True)
    async def request(self,method,path,uid=1,body=None,timing=None):
        trace_start=time.monotonic()
        async def trace(event,info):
            # Only retain event times, never HTTP headers, credentials or payloads.
            if timing is not None and event=='http11.send_request_headers.started':timing.setdefault('before_send_ms',(time.monotonic()-trace_start)*1000)
        options={'extensions':{'trace':trace}} if timing is not None else {}
        response=await self.client.request(method,f"http://127.0.0.1:{self.ports['gateway']}/api/growth"+path,headers={'Authorization':'Bearer '+self.tokens[uid]},json=body,**options)
        data=response.json();return data,response
    async def ready(self):return (await self.request('GET','/activities'))[0].get('code')==200
    async def activity(self,stock=1,pay=600):
        now=datetime.now(timezone.utc);data,_=await self.request('POST','/admin/activities',body={'title':'lab-'+uuid4().hex[:8],'stock':stock,'startsAt':(now-timedelta(seconds=1)).isoformat(),'endsAt':(now+timedelta(hours=1)).isoformat(),'paySeconds':pay})
        assert data['code']==200,data.get('message');aid=data['data']['activityId']
        data,_=await self.request('POST',f'/admin/activities/{aid}/activate');assert data['code']==200
        return aid
    async def grab(self,aid,uid):
        data,_=await self.request('POST',f'/activities/{aid}/reservations',uid,{'requestId':str(uuid4())});assert data['code']==200,data.get('message');return data['data']['orderId']
    def key(self,aid,suffix):return 'growth:{'+aid+'}:'+suffix
    async def queue(self):
        r=await self.management.get('/api/queues/%2F/growth.orders.create')
        if r.status_code!=200:return {}
        d=r.json();return {'ready':d.get('messages_ready',0),'unacked':d.get('messages_unacknowledged',0),'messages':d.get('messages',0)}
    async def consistent(self,aid):
        async def state():
            data,_=await self.request('GET',f'/admin/activities/{aid}/audit')
            if data.get('code')!=200:return None
            d=data['data'];return d if d['databaseStockConsistent'] and not d['missingReceipts'] and d['pendingEffects']==0 and d['unconfirmedReservations']==0 and d['redisStock']==str(d['activity']['availableStock']) else None
        return await self.until(state,timeout=120)
    async def load(self,requests,concurrency,stock=200):
        self.report['phase']=f'load:{requests}:{concurrency}';self.save()
        aid=await self.activity(stock);semaphore=asyncio.Semaphore(concurrency);latencies=[];codes=collections.Counter();instances=collections.Counter();samples=[];stop=asyncio.Event();timings=[]
        before={name:process_sample(p.pid) for name,p in self.processes.items() if p.poll() is None}
        before['load-generator']=process_sample(os.getpid())
        started=time.monotonic()
        async def observe():
            while not stop.is_set():
                try:
                    q=await self.queue();q['stream']=await self.redis.xlen(self.key(aid,'events'));q['processes']={name:process_sample(p.pid) for name,p in self.processes.items() if p.poll() is None};q['processes']['load-generator']=process_sample(os.getpid());samples.append(q)
                except (httpx.HTTPError,OSError):pass
                await asyncio.sleep(.25)
        task=asyncio.create_task(observe())
        async def send(index):
            async with semaphore:
                begin=time.monotonic()
                try:
                    trace_timing={}
                    data,response=await self.request('POST',f'/activities/{aid}/reservations',100+index%1000,{'requestId':str(uuid4())},trace_timing)
                    codes[str(data.get('code',response.status_code))]+=1;instances[response.headers.get('X-Growth-Lab-Instance','none')]+=1
                    timings.append({'trace':response.headers.get('X-Request-Id'),'client_ms':(time.monotonic()-begin)*1000,'dispatch_ms':float(response.headers['X-Growth-Lab-Dispatch-Ms']) if 'X-Growth-Lab-Dispatch-Ms' in response.headers else None,**trace_timing})
                except (httpx.HTTPError,ValueError):codes['transport_error']+=1
                latencies.append((time.monotonic()-begin)*1000)
        try:
            await asyncio.gather(*(send(i) for i in range(requests)));http_elapsed=time.monotonic()-started
            print('LOAD_HTTP '+json.dumps({'codes':dict(codes),'instances':dict(instances),'orders':self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,)),'stream':await self.redis.xlen(self.key(aid,'events'))}),flush=True)
            self.report['phase']+=':settle';self.save()
            await self.until(lambda:self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,)),lambda n:n>=stock,timeout=120)
            self.check(f'load_{requests}_{concurrency}_no_extra_orders',self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,))==stock)
            self.report['phase']+=':audit';self.save()
            await self.consistent(aid);settled=time.monotonic()-started
        finally:stop.set();await task
        after={name:process_sample(p.pid) for name,p in self.processes.items() if p.poll() is None}
        after['load-generator']=process_sample(os.getpid())
        metrics={'requests':requests,'concurrency':concurrency,'stock':stock,'http_seconds':round(http_elapsed,3),'request_throughput_rps':round(requests/http_elapsed,2),'settled_seconds':round(settled,3),'settled_orders_per_second':round(stock/settled,2),'response_codes':dict(codes),'instances':dict(instances),**percentiles(latencies),
                 'peak_queue_ready':max((s.get('ready',0) for s in samples),default=0),'peak_queue_unacked':max((s.get('unacked',0) for s in samples),default=0),'peak_stream_backlog':max((s.get('stream',0) for s in samples),default=0),'process_resources':{}}
        for name in after:
            cpu=after[name].get('cpu_seconds',0)-before.get(name,{}).get('cpu_seconds',0)
            metrics['process_resources'][name]={'cpu_seconds':round(cpu,2),'cpu_percent_one_core':round(cpu/settled*100,2),'peak_rss_mb':max((s.get('processes',{}).get(name,{}).get('rss_mb',0) for s in samples),default=0),'peak_private_mb':max((s.get('processes',{}).get(name,{}).get('private_mb',0) for s in samples),default=0)}
        gateway_times={match[0]:float(match[1]) for match in re.findall(r'edge_request trace=([a-f0-9-]+).*?duration_ms=(\d+)',(self.folder/'gateway.log').read_text(encoding='utf-8',errors='replace'))}
        matched=[dict(row,gateway_ms=gateway_times[row['trace']]) for row in timings if row['trace'] in gateway_times and row['dispatch_ms'] is not None]
        metrics['timing_breakdown']={'matched_requests':len(matched),'business_dispatch':percentiles([r['dispatch_ms'] for r in matched]),'gateway_including_auth_and_upstream':percentiles([r['gateway_ms'] for r in matched]),'client_minus_gateway_observed':percentiles([max(0,r['client_ms']-r['gateway_ms']) for r in matched]),'slow_request_samples':sorted(matched,key=lambda r:r['client_ms'],reverse=True)[:5]}
        sent=[r for r in matched if 'before_send_ms' in r]
        metrics['timing_breakdown']['client_before_headers_send']=percentiles([r['before_send_ms'] for r in sent])
        metrics['timing_breakdown']['client_after_headers_send']=percentiles([r['client_ms']-r['before_send_ms'] for r in sent])
        self.report['profiles'].append(metrics)
        self.check(f'load_{requests}_{concurrency}_stock_and_unique_users',self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,))==stock and self.scalar('SELECT COUNT(DISTINCT user_id) FROM growth_order WHERE activity_id=%s',(aid,))==stock)
        self.check(f'load_{requests}_{concurrency}_both_instances_served',instances['one']>0 and instances['two']>0)
        self.check(f'load_{requests}_{concurrency}_no_system_errors',set(codes).issubset({'200','409','429'}),response_codes=dict(codes))
        print('PROFILE '+json.dumps(metrics),flush=True)
    async def faults(self):
        # Gate only in test source: kill the exact JVM after the real transaction returns, before production ACK.
        aid=await self.activity();uid=2
        self.redis_proxy.mode_set('normal')
        # Hold the forwarder at the TCP boundary while choosing the reservation ID.
        self.rabbit_proxy.mode_set('cut');rid=await self.grab(aid,uid)
        gate=self.folder/'hold-after-commit';gate.write_text(rid)
        self.rabbit_proxy.mode_set('normal')
        marker=self.folder/'committed-before-ack'
        await self.until(lambda:marker.exists(),timeout=60)
        value=marker.read_text().strip();committed,pid=value.split(':');pid=int(pid)
        self.check('consumer_transaction_committed_before_ack',committed==rid and self.scalar('SELECT state FROM growth_order WHERE order_id=%s',(rid,))=='PENDING')
        victim=next(name for name,p in self.processes.items() if p.pid==pid);self.processes[victim].kill();await asyncio.to_thread(self.processes[victim].wait)
        gate.unlink(missing_ok=True)
        async def redelivered():return (self.folder/'redeliveries.log').exists() and rid in (self.folder/'redeliveries.log').read_text()
        await self.until(redelivered)
        self.check('killed_consumer_redelivered_to_other_instance',self.scalar('SELECT COUNT(*) FROM growth_order WHERE order_id=%s',(rid,))==1 and self.scalar('SELECT available_stock FROM growth_activity WHERE activity_id=%s',(aid,))==0)
        self.launch(victim,self.folder/(victim+'.yml'));await self.healthy(victim)
        await self.consistent(aid)
        # Redis process SIGKILL + restart with the same AOF; sessions and accepted receipts must survive.
        aid=await self.activity(10);self.rabbit_proxy.mode_set('cut')
        ids=[await self.grab(aid,uid) for uid in range(10,20)]
        self.check('redis_restart_fixture_unmaterialized',self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,))==0)
        await self.docker('kill','--signal=KILL',self.prefix+'-redis');await self.docker('start',self.prefix+'-redis')
        async def redis_up():return await self.redis.ping()
        await self.until(redis_up)
        self.check('redis_aof_preserved_receipts_and_stream',await self.redis.hlen(self.key(aid,'reservations'))==10 and await self.redis.xlen(self.key(aid,'events'))==10 and await self.redis.get(self.key(aid,'stock'))=='0')
        self.rabbit_proxy.mode_set('normal');await self.until(lambda:self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,)),lambda n:n==10);await self.consistent(aid)
        self.check('redis_restart_backlog_recovered_once',self.scalar('SELECT COUNT(DISTINCT order_id) FROM growth_order WHERE activity_id=%s',(aid,))==10)
        # Actual broker restart; Redis accepts an intent during downtime and relay catches up.
        aid=await self.activity(10);await self.docker('stop','-t','5',self.prefix+'-rabbit')
        ids=[await self.grab(aid,uid) for uid in range(20,30)]
        await asyncio.sleep(4)
        self.check('mq_down_preserves_pending_intents',await self.redis.xlen(self.key(aid,'events'))==10 and self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,))==0)
        await self.docker('start',self.prefix+'-rabbit')
        async def broker_up():return (await self.management.get('/api/overview')).status_code==200
        await self.until(broker_up,timeout=120);await self.until(lambda:self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,)),lambda n:n==10,timeout=90);await self.consistent(aid)
        self.check('mq_restart_intents_materialized_once',self.scalar('SELECT available_stock FROM growth_activity WHERE activity_id=%s',(aid,))==0)
        # Paused admission must still settle accepted intents and allow compensation.
        aid=await self.activity(4);self.rabbit_proxy.mode_set('cut')
        for uid in range(35,39):await self.grab(aid,uid)
        result,_=await self.request('POST',f'/admin/activities/{aid}/pause');assert result['code']==200
        self.rabbit_proxy.mode_set('normal')
        await self.until(lambda:self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,)),lambda n:n==4,timeout=90)
        await self.consistent(aid)
        self.check('paused_activity_compensation_converges',self.scalar("SELECT COUNT(*) FROM growth_order WHERE activity_id=%s AND state='REJECTED'",(aid,))==4 and await self.redis.get(self.key(aid,'stock'))=='4')
        result,_=await self.request('POST',f'/admin/activities/{aid}/resume');self.check('paused_activity_can_resume_after_compensation',result['code']==200)
        # Drop the server->publisher direction: broker can accept a publish but confirmation cannot reach caller.
        aid=await self.activity(5);self.rabbit_proxy.mode_set('drop_confirm')
        ids=[await self.grab(aid,uid) for uid in range(30,35)];await asyncio.sleep(5)
        self.check('lost_publisher_confirm_keeps_stream_intent',await self.redis.xlen(self.key(aid,'events'))==5)
        self.rabbit_proxy.mode_set('normal');await self.until(lambda:self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,)),lambda n:n==5,timeout=90);await self.consistent(aid)
        self.check('network_confirm_loss_recovers_without_double_stock',self.scalar('SELECT available_stock FROM growth_activity WHERE activity_id=%s',(aid,))==0)
        aid=await self.activity();self.redis_proxy.mode_set('cut')
        result,_=await self.request('POST',f'/activities/{aid}/reservations',40,{'requestId':str(uuid4())})
        self.check('redis_network_partition_fails_closed',result['code']!=200)
        self.redis_proxy.mode_set('normal');await self.healthy('one');await self.healthy('two');await self.until(self.ready)
        rid=await self.grab(aid,40);await self.until(lambda:self.scalar('SELECT COUNT(*) FROM growth_order WHERE order_id=%s',(rid,)))
        await self.consistent(aid);self.check('redis_network_restored_admission_recovers',True)
        await self.races()
    async def races(self):
        late=await self.activity();late_id=await self.grab(late,45)
        await self.until(lambda:self.scalar('SELECT COUNT(*) FROM growth_order WHERE order_id=%s',(late_id,)))
        lock=pymysql.connect(host=settings.MYSQL_HOST,port=settings.MYSQL_PORT,user=self.account,password=self.password,database=self.schema,autocommit=False)
        try:
            with lock.cursor() as cursor:
                cursor.execute('SELECT order_id FROM growth_order WHERE order_id=%s FOR UPDATE',(late_id,))
                cursor.execute('UPDATE growth_order SET expires_at=DATE_ADD(NOW(3),INTERVAL 500000 MICROSECOND) WHERE order_id=%s',(late_id,))
            waiting=asyncio.create_task(self.request('POST',f'/orders/{late_id}/pay',45))
            await asyncio.sleep(.9);lock.commit();await waiting
        finally:lock.close()
        await self.consistent(late)
        self.check('payment_lock_wait_crossing_deadline_cannot_charge',self.scalar('SELECT state FROM growth_order WHERE order_id=%s',(late_id,))=='CLOSED' and self.scalar('SELECT COUNT(*) FROM coin_ledger WHERE order_id=%s',(late_id,))==0)
        aid=await self.activity(60);ids=[]
        for uid in range(50,110):ids.append((uid,await self.grab(aid,uid)))
        await self.until(lambda:self.scalar('SELECT COUNT(*) FROM growth_order WHERE activity_id=%s',(aid,)),lambda n:n==60)
        # Before/after the deadline: launch concurrent pay requests while the real expiry worker runs.
        self.execute('UPDATE growth_order SET expires_at=DATE_ADD(NOW(3),INTERVAL 600000 MICROSECOND) WHERE activity_id=%s',(aid,))
        async def pay(uid,rid,delay):
            await asyncio.sleep(delay)
            return (await self.request('POST',f'/orders/{rid}/pay',uid))[0]
        await asyncio.gather(*(pay(uid,rid,0 if i<20 else .55 if i<40 else .70) for i,(uid,rid) in enumerate(ids) for _ in range(3)))
        await self.until(lambda:self.scalar("SELECT COUNT(*) FROM growth_order WHERE activity_id=%s AND state='PENDING'",(aid,)),lambda n:n==0)
        await self.consistent(aid)
        rows=self.rows("SELECT o.order_id,o.user_id,o.state,u.current_coin_count,(SELECT COUNT(*) FROM coin_ledger l WHERE l.order_id=o.order_id) AS charges,(SELECT COUNT(*) FROM growth_ledger l WHERE l.order_id=o.order_id) AS credits FROM growth_order o JOIN user_info u ON u.user_id=o.user_id WHERE o.activity_id=%s",(aid,))
        paid=sum(r['state']=='PAID' for r in rows);closed=sum(r['state']=='CLOSED' for r in rows)
        self.check('pay_expiry_race_has_both_terminal_outcomes',paid>0 and closed>0,paid=paid,closed=closed)
        self.check('pay_expiry_race_no_double_charge_or_paid_release',all((r['state']=='PAID' and r['charges']==1 and r['credits']==1 and r['current_coin_count']==90) or (r['state']=='CLOSED' and r['charges']==0 and r['credits']==0 and r['current_coin_count']==100) for r in rows) and self.scalar('SELECT available_stock FROM growth_activity WHERE activity_id=%s',(aid,))==closed)
    async def cleanup(self):
        for proxy in self.proxies:
            try:await proxy.close()
            except Exception:pass
        for process in self.processes.values():
            if process.poll() is None:process.terminate()
        for process in self.processes.values():
            try:await asyncio.to_thread(process.wait,10)
            except subprocess.TimeoutExpired:process.kill();await asyncio.to_thread(process.wait)
        for stream in self.logs:stream.close()
        for connection in (self.client,self.management,self.redis):
            if connection:
                try:await connection.aclose()
                except Exception:pass
        # Verify exact ownership before deleting anything. Never select production names.
        owner=json.loads(self.owner_marker.read_text())
        assert owner=={'owner':'growth-four-rounds','tag':self.tag,'schema':self.schema,'prefix':self.prefix}
        for name in self.containers:
            assert name in (self.prefix+'-redis',self.prefix+'-rabbit')
            label=await self.docker('inspect','--format','{{ index .Config.Labels "easyjob.growth-lab" }}',name)
            assert label==self.tag
            await self.docker('rm','-f','-v',name)
        if self.sql:
            assert re.fullmatch('easyjob_growth_lab_[a-f0-9]{8}',self.schema)
            assert re.fullmatch('ej_growth_lab_[a-f0-9]{8}',self.account)
            if self.database_created:self.execute('DROP DATABASE `'+self.schema+'`')
            if self.account_created:self.execute("DROP USER %s@'localhost'",(self.account,))
            self.sql.close()
        self.report['cleanup']='owned processes, containers, database and account removed';self.save()
        # Retain evidence, remove ephemeral credentials from the ignored run folder.
        for name in ('one.yml','two.yml','auth.yml','gateway.yml','rabbit.env'):(self.folder/name).unlink(missing_ok=True)
        for file in (self.folder/'keys').glob('*private.json'):file.unlink()


async def main(args):
    lab=Lab();print('LAB '+lab.folder.as_posix(),flush=True)
    try:
        await lab.prepare()
        profiles=[tuple(map(int,p.split(':'))) for p in args.profile] if args.profile else ((1000,32),(10000,256)) if args.latency_only else ((1000,32),(5000,128),(10000,256))
        if any(n<200 or n>20000 or c<1 or c>512 for n,c in profiles):raise ValueError('Profile must be requests 200..20000 and concurrency 1..512')
        for count,concurrency in profiles:
            await lab.load(count,concurrency)
        if not args.latency_only:await lab.faults()
        lab.report['latency_only']=args.latency_only;lab.report['status']='passed';lab.save()
    except Exception as error:
        if lab.database_created:
            try:
                lab.report['diagnostic']={'orders':lab.rows('SELECT state,COUNT(*) AS n FROM growth_order GROUP BY state'),'effects':lab.rows('SELECT delivered,event_type,COUNT(*) AS n FROM growth_outbox GROUP BY delivered,event_type')}
                if lab.client:
                    activities=lab.rows('SELECT activity_id FROM growth_activity ORDER BY created_at DESC LIMIT 1')
                    if activities:lab.report['diagnostic']['audit']=(await lab.request('GET','/admin/activities/'+activities[0]['activity_id']+'/audit'))[0]
            except Exception:pass
        lab.report['status']='failed';lab.report['error_type']=type(error).__name__;lab.report['failure']=str(error) if isinstance(error,AssertionError) else 'Inspect bounded lab logs';lab.save()
        print('LAB FAILED '+lab.report['failure'],flush=True);raise
    finally:await lab.cleanup()
    print('LAB PASSED '+str(len(lab.checks))+' checks; report '+str(lab.folder/'report.json'),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--latency-only',action='store_true');parser.add_argument('--profile',action='append',help='requests:concurrency');arguments=parser.parse_args()
    try:asyncio.run(main(arguments))
    except Exception:raise SystemExit(1)
