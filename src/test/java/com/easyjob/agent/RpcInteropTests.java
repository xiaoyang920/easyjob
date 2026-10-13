package com.easyjob.agent;

import com.easyjob.agent.rpc.*;
import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentDraftService;
import com.easyjob.service.ArticleRevisionService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.net.ServerSocket;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Opt-in: actual Java Triple <-> Python grpcio, without production DB/LLM dependencies. */
@EnabledIfEnvironmentVariable(named="RPC_TEST_PYTHON", matches=".+")
class RpcInteropTests {
    private int freePort() throws Exception { try (var socket = new ServerSocket(0)) { return socket.getLocalPort(); } }
    @Test void nativeGrpcAndDubboTripleWorkInBothDirections() throws Exception {
        String python = System.getenv("RPC_TEST_PYTHON");
        int agentPort = freePort(), blogPort = freePort();
        var ready = Files.createTempFile("easyjob-rpc-", ".ready"); Files.delete(ready);
        var output = Files.createTempFile("easyjob-rpc-", ".log");
        var callbackOutput = Files.createTempFile("easyjob-rpc-callback-", ".log");
        var peer = new ProcessBuilder(python, "scripts/rpc-integration-peer.py", "server", ""+agentPort, ready.toString())
                .redirectErrorStream(true).redirectOutput(output.toFile()).start();
        try {
            for (int i=0; i<150 && !Files.exists(ready) && peer.isAlive(); i++) Thread.sleep(100);
            assertTrue(Files.exists(ready), () -> {
                try { return Files.readString(output); } catch (Exception e) { return "Python peer failed"; }
            });
            var revisions = mock(ArticleRevisionService.class);
            var drafts = mock(AgentDraftService.class);
            when(revisions.ownDrafts(7L,"中文")).thenReturn(List.of(Map.of("articleId",Long.toString(RpcTransportTests.BIG),"title","中文草稿")));
            when(revisions.ownDraft(7L,RpcTransportTests.BIG)).thenReturn(Map.of("id",RpcTransportTests.BIG,"editable",true,"empty",List.of()));
            when(drafts.save(eq(7L),any())).thenAnswer(invocation -> {
                AgentDraftService.DraftRequest draft = invocation.getArgument(1);
                if (draft.expectedLockVersion()!=0) throw new ResponseStatusException(HttpStatus.CONFLICT);
                return Map.of("articleId",Long.toString(draft.articleId()));
            });
            var auth = new AgentServiceAuth(RpcTransportTests.KEY);
            try (var runtime = new TripleRuntime(new BlogRpcProvider(auth,drafts,revisions),"127.0.0.1:"+agentPort,"127.0.0.1",blogPort)) {
                runtime.start();
                var client = new AgentRpcClient(runtime.agent(),auth);
                var body = new HashMap<String,java.lang.Object>();
                body.put("message","测试"); body.put("request_id",UUID.randomUUID().toString());
                body.put("origin_article_id",RpcTransportTests.BIG); body.put("image_paths",List.of());
                var reply = (Map<?,?>)client.post("/chat",7L,body);
                assertEquals("中文二进制 RPC",reply.get("reply"));
                assertEquals(Long.toString(RpcTransportTests.BIG),reply.get("conversationId"));
                var history = (Map<?,?>)((Map<?,?>)client.history(7L,42L,false,30,RpcTransportTests.BIG,null,null,null)).get("data");
                assertEquals(RpcTransportTests.BIG,history.get("id"));
                var frames = client.stream("/chat/stream",7L,body).collectList().block(Duration.ofSeconds(20));
                assertEquals(List.of("__ANSWER__:{\"type\":\"start\"}","","__REPLY__:中文\\n回复","[DONE]"),frames);
                assertEquals(409,assertThrows(ResponseStatusException.class, () -> client.post("/chat/42/cancel?user_id=7",7L,null)).getStatusCode().value());
                var wrong = new AgentRpcClient(runtime.agent(),new AgentServiceAuth("incorrect-service-key-but-long-enough"));
                assertEquals(401,assertThrows(ResponseStatusException.class, () -> wrong.post("/chat",7L,body)).getStatusCode().value());
                var callback = new ProcessBuilder(python,"scripts/rpc-integration-peer.py","callback",""+blogPort)
                        .redirectErrorStream(true).redirectOutput(callbackOutput.toFile()).start();
                try {
                    assertTrue(callback.waitFor(40,TimeUnit.SECONDS),"Python callback timed out");
                    assertEquals(0,callback.exitValue(),Files.readString(callbackOutput));
                } finally { stop(callback); }
                verify(drafts,times(2)).save(eq(7L),any());
            }
        } finally {
            Files.writeString(Path.of(ready + ".stop"), "stop");
            peer.waitFor(5,TimeUnit.SECONDS);
            stop(peer);
            cleanup(ready); cleanup(Path.of(ready + ".stop")); cleanup(output); cleanup(callbackOutput);
        }
    }
    private void cleanup(Path path) throws Exception {
        for (int i=0; i<20; i++) {
            try { Files.deleteIfExists(path); return; }
            catch (java.io.IOException e) { Thread.sleep(50); }
        }
        path.toFile().deleteOnExit(); // Antivirus/file handle release can lag on Windows.
    }
    private void stop(Process process) throws Exception {
        var children = process.descendants().toList();
        children.forEach(ProcessHandle::destroyForcibly);
        process.destroyForcibly(); process.waitFor(5,TimeUnit.SECONDS);
        for (var child : children) {
            try { child.onExit().get(5,TimeUnit.SECONDS); } catch (Exception ignored) { }
        }
    }
}
