package com.easyjob.agent.rpc;

import com.easyjob.rpc.v1.*;
import org.apache.dubbo.config.*;
import org.apache.dubbo.config.bootstrap.DubboBootstrap;

/** One application-scoped Dubbo runtime. Direct endpoints work without a registry. */
public final class TripleRuntime implements AutoCloseable {
    private final DubboBootstrap bootstrap = DubboBootstrap.newInstance();
    private final ReferenceConfig<AgentRpc> agent = new ReferenceConfig<>();
    private record Peer(ReferenceConfig<AgentRpc> reference, AgentRpc remote) {}
    private final RpcPeerPool<Peer> discovered = new RpcPeerPool<>(32, java.time.Duration.ofMinutes(5),
        this::createPeer, peer -> destroyPeer(peer.reference()));
    private final java.util.concurrent.ScheduledExecutorService reaper=java.util.concurrent.Executors.newSingleThreadScheduledExecutor(r -> {
        var thread=new Thread(r,"rpc-peer-reaper");thread.setDaemon(true);return thread;
    });
    private ServiceCatalog catalog;
    public TripleRuntime(BlogRpc provider, String target, String bind, int port) {
        var application = new ApplicationConfig("easyjob-blog");
        application.setQosEnable(false);
        application.setEnableFileCache(false);
        var protocol = new ProtocolConfig("tri", port);
        protocol.setHost(loopbackHost(bind));
        protocol.setThreads(32);
        protocol.setQueues(128);
        var blog = new ServiceConfig<BlogRpc>();
        blog.setInterface(BlogRpc.class); blog.setRef(provider);
        blog.setRegister(false);
        agent.setInterface(AgentRpc.class);
        var endpoint = org.apache.dubbo.common.URL.valueOf("tri://" + target);
        agent.setUrl(endpoint.setHost(loopbackHost(endpoint.getHost())).toString());
        agent.setCheck(false); agent.setRetries(0); agent.setTimeout(310_000);
        agent.setCluster("failfast");
        agent.setMethods(java.util.stream.Stream.of("cancel", "runStatus", "runOverview", "conversationRun",
                "conversations", "conversation", "messages", "questions", "deleteConversation", "memory",
                "editProfile", "editMemory", "deleteMemory", "serviceQuery").map(name -> {
            var method = new MethodConfig(); method.setName(name); method.setTimeout(20_000); method.setRetries(0);
            return method;
        }).toList());
        bootstrap.application(application).registry(new RegistryConfig("N/A"))
                .protocol(protocol).service(blog);
    }
    public void start() {
        if(catalog==null || !catalog.enabled()) bootstrap.reference(agent);bootstrap.start();
        reaper.scheduleWithFixedDelay(() -> {
            if(catalog!=null && catalog.enabled()) discovered.reconcile(catalog.healthyTargets());
        },5,5,java.util.concurrent.TimeUnit.SECONDS);
    }
    private Peer createPeer(String endpoint) {
        var ref=new ReferenceConfig<AgentRpc>();ref.setInterface(AgentRpc.class);
        var url=org.apache.dubbo.common.URL.valueOf("tri://"+endpoint);
        ref.setUrl(url.setHost(loopbackHost(url.getHost())).toString());
        ref.setCheck(false);ref.setRetries(0);ref.setCluster("failfast");ref.setTimeout(310000);
        ref.setMethods(agent.getMethods());bootstrap.reference(ref);
        try { return new Peer(ref,ref.get()); }
        catch(RuntimeException failure) { destroyPeer(ref);throw failure; }
    }
    private void destroyPeer(ReferenceConfig<AgentRpc> reference) {
        try { reference.destroy(); }
        finally { bootstrap.getApplicationModel().getDefaultModule().getConfigManager().removeConfig(reference); }
    }
    public void catalog(ServiceCatalog value) { catalog=value; }
    public AgentRpc agent() {
        if(catalog==null || !catalog.enabled()) return agent.get();
        return (AgentRpc)java.lang.reflect.Proxy.newProxyInstance(AgentRpc.class.getClassLoader(),new Class<?>[]{AgentRpc.class},(proxy,method,args) -> {
            if(method.getDeclaringClass()==java.lang.Object.class) return method.invoke(this,args);
            var identity=(Identity)args[0].getClass().getMethod("getIdentity").invoke(args[0]);
            String endpoint=catalog.agentTarget(identity.getUserId());
            discovered.reconcile(catalog.healthyTargets());
            var lease=discovered.acquire(endpoint);
            var locallyCancelled=new java.util.concurrent.atomic.AtomicBoolean();
            boolean streaming=args.length>1 && args[args.length-1] instanceof org.apache.dubbo.common.stream.StreamObserver<?>;
            if(streaming) {
                var observer=(org.apache.dubbo.common.stream.StreamObserver<java.lang.Object>)args[args.length-1];
                args=args.clone();
                args[args.length-1]=new org.apache.dubbo.common.stream.StreamObserver<java.lang.Object>() {
                    public void onNext(java.lang.Object value) { try { observer.onNext(value); } catch(Throwable error) { lease.close();throw error; } }
                    public void onError(Throwable error) {
                        // Per-call cancellation/deadlines do not invalidate a
                        // connection shared with other running streams.
                        if(shouldInvalidate(error,locallyCancelled.get())) lease.invalidate();
                        try { observer.onError(error); } finally { lease.close(); }
                    }
                    public void onCompleted() { try { observer.onCompleted(); } finally { lease.close(); } }
                };
                var cancellation=org.apache.dubbo.rpc.RpcContext.getCancellationContext();
                if(cancellation!=null) cancellation.addListener(context -> {
                    locallyCancelled.set(true);lease.close();
                });
            }
            try { return method.invoke(lease.value().remote(),args); }
            catch(java.lang.reflect.InvocationTargetException e) {
                if(shouldInvalidate(e.getCause(),locallyCancelled.get())) lease.invalidate();
                lease.close();throw e.getCause();
            }
            catch(Throwable error) {
                if(shouldInvalidate(error,locallyCancelled.get())) lease.invalidate();
                lease.close();throw error;
            }
            finally { if(!streaming) lease.close(); }
        });
    }
    static boolean shouldInvalidate(Throwable error,boolean locallyCancelled) {
        if(locallyCancelled || error instanceof java.util.concurrent.CancellationException) return false;
        if(error instanceof org.apache.dubbo.rpc.RpcException rpc) return !rpc.isBiz() && !rpc.isTimeout();
        return true;
    }
    @Override public void close() { reaper.shutdownNow();discovered.close();bootstrap.destroy(); }
    static String loopbackHost(String host) {
        // Dubbo 3.3 treats IPv4 loopback as unspecified and rewrites it to a NIC IP.
        // The IPv4-mapped form resolves to the same IPv4 socket without that rewrite.
        if ("localhost".equalsIgnoreCase(host)) return "::ffff:127.0.0.1";
        return host.startsWith("127.") ? "::ffff:" + host : host;
    }
}
