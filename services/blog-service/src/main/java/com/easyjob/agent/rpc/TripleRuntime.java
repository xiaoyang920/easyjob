package com.easyjob.agent.rpc;

import com.easyjob.rpc.v1.*;
import org.apache.dubbo.config.*;
import org.apache.dubbo.config.bootstrap.DubboBootstrap;
import com.easyjob.rpc.v1.AgentRpc;
import com.easyjob.rpc.v1.BlogRpc;
import com.easyjob.rpc.v1.Identity;
import org.apache.dubbo.common.URL;
import org.apache.dubbo.config.ApplicationConfig;
import org.apache.dubbo.config.ProtocolConfig;
import org.apache.dubbo.config.ReferenceConfig;
import org.apache.dubbo.config.ServiceConfig;

/** One application-scoped Dubbo runtime. Direct endpoints work without a registry. */
public final class TripleRuntime implements AutoCloseable {
    private final DubboBootstrap bootstrap = DubboBootstrap.newInstance();
    private final ReferenceConfig<AgentRpc> agent = new ReferenceConfig<>();
    private record Peer(ReferenceConfig<AgentRpc> reference, AgentRpc remote) {}
    private final RpcPeerPool<Peer> discovered = new RpcPeerPool<>(32, java.time.Duration.ofMinutes(5),
        this::createPeer, peer -> destroyPeer(peer.reference()));
    private final java.util.concurrent.ScheduledExecutorService reaper=java.util.concurrent.Executors.newSingleThreadScheduledExecutor(r -> {
        Thread thread=new Thread(r,"rpc-peer-reaper");thread.setDaemon(true);return thread;
    });
    private ServiceCatalog catalog;
    public TripleRuntime(BlogRpc provider, String target, String bind, int port) {
        ApplicationConfig application = new ApplicationConfig("easyjob-blog");
        application.setQosEnable(false);
        application.setEnableFileCache(false);
        ProtocolConfig protocol = new ProtocolConfig("tri", port);
        protocol.setHost(loopbackHost(bind));
        protocol.setThreads(32);
        protocol.setQueues(128);
        ServiceConfig<BlogRpc> blog = new ServiceConfig<BlogRpc>();
        blog.setInterface(BlogRpc.class); blog.setRef(provider);
        blog.setRegister(false);
        agent.setInterface(AgentRpc.class);
        URL endpoint = org.apache.dubbo.common.URL.valueOf("tri://" + target);
        agent.setUrl(endpoint.setHost(loopbackHost(endpoint.getHost())).toString());
        agent.setCheck(false); agent.setRetries(0); agent.setTimeout(20_000);
        agent.setCluster("failfast");
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
        ReferenceConfig<AgentRpc> ref=new ReferenceConfig<AgentRpc>();ref.setInterface(AgentRpc.class);
        URL url=org.apache.dubbo.common.URL.valueOf("tri://"+endpoint);
        ref.setUrl(url.setHost(loopbackHost(url.getHost())).toString());
        ref.setCheck(false);ref.setRetries(0);ref.setCluster("failfast");ref.setTimeout(20_000);
        bootstrap.reference(ref);
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
            Identity identity=(Identity)args[0].getClass().getMethod("getIdentity").invoke(args[0]);
            String endpoint=catalog.agentTarget(identity.getUserId());
            discovered.reconcile(catalog.healthyTargets());
            RpcPeerPool<Peer>.Lease lease=discovered.acquire(endpoint);
            try { return method.invoke(lease.value().remote(),args); }
            catch(java.lang.reflect.InvocationTargetException e) {
                if(shouldInvalidate(e.getCause())) lease.invalidate();
                lease.close();throw e.getCause();
            }
            catch(Throwable error) {
                if(shouldInvalidate(error)) lease.invalidate();
                lease.close();throw error;
            }
            finally { lease.close(); }
        });
    }
    static boolean shouldInvalidate(Throwable error) {
        if(error instanceof java.util.concurrent.CancellationException) return false;
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
