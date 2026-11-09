package com.easyjob.agent.rpc;

import org.apache.dubbo.rpc.RpcException;
import org.junit.jupiter.api.Test;
import java.util.concurrent.CancellationException;
import static org.junit.jupiter.api.Assertions.*;

class RpcFailurePolicyTests {
    @Test void perCallCancellationAndDeadlineDoNotInvalidateTheSharedTransport() {
        assertFalse(TripleRuntime.shouldInvalidate(new RpcException(RpcException.TIMEOUT_EXCEPTION,"deadline")));
        assertFalse(TripleRuntime.shouldInvalidate(new RpcException(RpcException.BIZ_EXCEPTION,"conflict")));
        assertFalse(TripleRuntime.shouldInvalidate(new CancellationException()));
    }
    @Test void actualTransportFailureStillReplacesTheFailedConnectionWithoutRetryingTheCall() {
        assertTrue(TripleRuntime.shouldInvalidate(new RpcException(RpcException.NETWORK_EXCEPTION,"closed")));
        assertTrue(TripleRuntime.shouldInvalidate(new IllegalStateException("transport failed")));
    }
}
