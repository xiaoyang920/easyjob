package com.easyjob.agent.rpc;

import com.easyjob.rpc.v1.*;
import org.apache.dubbo.config.*;
import org.apache.dubbo.config.bootstrap.DubboBootstrap;

/** One application-scoped Dubbo runtime. Direct endpoints work without a registry. */
public final class TripleRuntime implements AutoCloseable {
    private final DubboBootstrap bootstrap = DubboBootstrap.newInstance();
    private final ReferenceConfig<AgentRpc> agent = new ReferenceConfig<>();
    private final java.util.Map<String,ReferenceConfig<AgentRpc>> discovered = new java.util.LinkedHashMap<>();
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
    public void start() { if(catalog==null || !catalog.enabled()) bootstrap.reference(agent);bootstrap.start(); }
    public void catalog(ServiceCatalog value) { catalog=value; }
    public AgentRpc agent() {
        if(catalog==null || !catalog.enabled()) return agent.get();
        return (AgentRpc)java.lang.reflect.Proxy.newProxyInstance(AgentRpc.class.getClassLoader(),new Class<?>[]{AgentRpc.class},(proxy,method,args) -> {
            if(method.getDeclaringClass()==java.lang.Object.class) return method.invoke(this,args);
            var identity=(Identity)args[0].getClass().getMethod("getIdentity").invoke(args[0]);
            String endpoint=catalog.agentTarget(identity.getUserId());
            AgentRpc peer;
            synchronized(discovered) {
                var ref=discovered.get(endpoint);
                if(ref==null) {
                    if(discovered.size()>=32) throw new IllegalStateException("RPC endpoint pool full");
                    ref=new ReferenceConfig<>(); ref.setInterface(AgentRpc.class);
                    var url=org.apache.dubbo.common.URL.valueOf("tri://"+endpoint);
                    ref.setUrl(url.setHost(loopbackHost(url.getHost())).toString());
                    ref.setCheck(false);ref.setRetries(0);ref.setCluster("failfast");ref.setTimeout(310000);
                    ref.setMethods(agent.getMethods());bootstrap.reference(ref);discovered.put(endpoint,ref);
                }
                peer=ref.get();
            }
            try { return method.invoke(peer,args); }
            catch(java.lang.reflect.InvocationTargetException e) { throw e.getCause(); }
        });
    }
    @Override public void close() { synchronized(discovered) { discovered.values().forEach(ReferenceConfig::destroy); } bootstrap.destroy(); }
    static String loopbackHost(String host) {
        // Dubbo 3.3 treats IPv4 loopback as unspecified and rewrites it to a NIC IP.
        // The IPv4-mapped form resolves to the same IPv4 socket without that rewrite.
        if ("localhost".equalsIgnoreCase(host)) return "::ffff:127.0.0.1";
        return host.startsWith("127.") ? "::ffff:" + host : host;
    }
}
