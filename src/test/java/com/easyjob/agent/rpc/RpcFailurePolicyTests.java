package com.easyjob.agent.rpc;

import org.apache.dubbo.rpc.RpcException;
import org.junit.jupiter.api.Test;
import java.util.concurrent.CancellationException;
import static org.junit.jupiter.api.Assertions.*;

class RpcFailurePolicyTests {
    @Test void cancelledSubscriberAndPerCallDeadlineDoNotInvalidateTheSharedTransport() {
        assertFalse(TripleRuntime.shouldInvalidate(new RpcException(RpcException.TIMEOUT_EXCEPTION,"deadline"),false));
        assertFalse(TripleRuntime.shouldInvalidate(new RpcException(RpcException.BIZ_EXCEPTION,"conflict"),false));
        assertFalse(TripleRuntime.shouldInvalidate(new CancellationException(),false));
        assertFalse(TripleRuntime.shouldInvalidate(new IllegalStateException("late callback"),true));
    }
    @Test void actualTransportFailureStillReplacesTheFailedConnectionWithoutRetryingTheCall() {
        assertTrue(TripleRuntime.shouldInvalidate(new RpcException(RpcException.NETWORK_EXCEPTION,"closed"),false));
        assertTrue(TripleRuntime.shouldInvalidate(new IllegalStateException("transport failed"),false));
    }
}
