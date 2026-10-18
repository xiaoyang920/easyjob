package com.easyjob.agent.rpc;

import org.junit.jupiter.api.Test;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

class RpcPeerPoolTests {
    @Test void failedConnectionIsReplacedAtSameHealthyAddressWithoutReplayingWork() {
        var creates=new AtomicInteger();var disposed=new ArrayList<Integer>();
        try(var pool=new RpcPeerPool<Integer>(2,Duration.ofMinutes(5),target -> creates.incrementAndGet(),disposed::add)) {
            var failed=pool.acquire("agent:50051");assertEquals(1,failed.value());
            failed.invalidate();failed.close();
            pool.reconcile(List.of("agent:50051"));
            try(var next=pool.acquire("agent:50051")) { assertEquals(2,next.value()); }
            assertEquals(List.of(1),disposed);
            assertEquals(2,creates.get());
        }
        assertEquals(List.of(1,2),disposed);
    }
    @Test void invalidTransportCannotBeRevivedWhileOtherCallsAreDraining() {
        var creates=new AtomicInteger();var disposed=new ArrayList<Integer>();
        try(var pool=new RpcPeerPool<Integer>(2,Duration.ofMinutes(5),target -> creates.incrementAndGet(),disposed::add)) {
            var first=pool.acquire("agent");var ongoing=pool.acquire("agent");
            assertEquals(1,first.value());assertEquals(1,ongoing.value());
            first.invalidate();first.close();pool.reconcile(List.of("agent"));
            assertTrue(disposed.isEmpty());
            assertThrows(IllegalStateException.class,() -> pool.acquire("agent"));
            ongoing.close();assertEquals(List.of(1),disposed);
            try(var next=pool.acquire("agent")) { assertEquals(2,next.value()); }
            first.invalidate();first.close();ongoing.invalidate();ongoing.close();
            assertEquals(List.of(1),disposed); // Late callbacks never close it twice.
        }
        assertEquals(List.of(1,2),disposed);
    }
    @Test void lateStreamFailureAfterCancellationRetiresTheIdlePeerOnce() {
        var disposed=new ArrayList<String>();
        try(var pool=new RpcPeerPool<String>(2,Duration.ofMinutes(5),target -> target,disposed::add)) {
            var cancelled=pool.acquire("agent");cancelled.value();cancelled.close();
            cancelled.invalidate();cancelled.invalidate();
            assertEquals(List.of("agent"),disposed);assertEquals(0,pool.size());
        }
        assertEquals(List.of("agent"),disposed);
    }
    @Test void endpointChurnBeyondCapacityClosesWithdrawnPeers() {
        var closed=new ArrayList<String>();
        try(var pool=new RpcPeerPool<String>(4,Duration.ofMinutes(5),s -> s,closed::add)) {
            for(int i=0;i<100;i++) {
                String endpoint="peer-"+i;
                pool.reconcile(List.of(endpoint));
                try(var lease=pool.acquire(endpoint)) { assertEquals(endpoint,lease.value()); }
                assertEquals(1,pool.size());
            }
        }
        assertEquals(100,closed.size());assertEquals(100,new HashSet<>(closed).size());
    }
    @Test void withdrawalAndShutdownDrainActiveCallsAndCloseExactlyOnce() {
        var closed=new ArrayList<String>();var pool=new RpcPeerPool<String>(2,Duration.ZERO,s -> s,closed::add);
        var active=pool.acquire("old");active.value();pool.reconcile(List.of("new"));
        assertTrue(closed.isEmpty());
        try(var next=pool.acquire("new")) { next.value(); }
        pool.close();assertEquals(List.of("new"),closed);
        active.close();active.close();assertEquals(List.of("new","old"),closed);
        assertThrows(IllegalStateException.class,() -> pool.acquire("other"));
    }
    @Test void capacityEvictsIdleButNeverActiveCallsAndIdleTtlWorks() {
        var tick=new AtomicLong();var closed=new ArrayList<String>();
        try(var pool=new RpcPeerPool<String>(1,Duration.ofNanos(10),s -> s,closed::add,tick::get)) {
            var first=pool.acquire("a");first.value();
            assertThrows(IllegalStateException.class,() -> pool.acquire("b"));
            first.close();
            try(var second=pool.acquire("b")) { second.value(); }
            assertEquals(List.of("a"),closed);
            tick.set(11);pool.reconcile(List.of("b"));assertEquals(List.of("a","b"),closed);
        }
    }
    @Test void initializationIsSingleFlightAndDoesNotBlockOtherEndpoints() throws Exception {
        var started=new CountDownLatch(1);var release=new CountDownLatch(1);var creates=new AtomicInteger();
        try(var pool=new RpcPeerPool<String>(4,Duration.ofMinutes(5),target -> {
            creates.incrementAndGet();if(target.equals("slow")) { started.countDown();try { release.await(); } catch(InterruptedException e){throw new RuntimeException(e);} }return target;
        },s -> {});var executor=Executors.newVirtualThreadPerTaskExecutor()) {
            var one=executor.submit(() -> { try(var lease=pool.acquire("slow")){return lease.value();} });
            assertTrue(started.await(2,TimeUnit.SECONDS));
            var two=executor.submit(() -> { try(var lease=pool.acquire("slow")){return lease.value();} });
            try(var fast=pool.acquire("fast")){assertEquals("fast",fast.value());}
            release.countDown();assertEquals("slow",one.get(2,TimeUnit.SECONDS));assertEquals("slow",two.get(2,TimeUnit.SECONDS));
            assertEquals(2,creates.get());
        } finally { release.countDown(); }
    }
}
