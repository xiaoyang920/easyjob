package com.easyjob.agent.rpc;

import org.junit.jupiter.api.Test;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

class RpcPeerPoolTests {
    @Test void failedConnectionIsReplacedAtSameHealthyAddressWithoutReplayingWork() {
        AtomicInteger creates=new AtomicInteger();ArrayList<Integer> disposed=new ArrayList<Integer>();
        try(RpcPeerPool<Integer> pool=new RpcPeerPool<Integer>(2,Duration.ofMinutes(5),target -> creates.incrementAndGet(),disposed::add)) {
            RpcPeerPool<Integer>.Lease failed=pool.acquire("agent:50051");assertEquals(1,failed.value());
            failed.invalidate();failed.close();
            pool.reconcile(List.of("agent:50051"));
            try(RpcPeerPool<Integer>.Lease next=pool.acquire("agent:50051")) { assertEquals(2,next.value()); }
            assertEquals(List.of(1),disposed);
            assertEquals(2,creates.get());
        }
        assertEquals(List.of(1,2),disposed);
    }
    @Test void retiredConnectionDoesNotBlockNewCallsWhileExistingCallsDrain() {
        AtomicInteger creates=new AtomicInteger();ArrayList<Integer> disposed=new ArrayList<Integer>();
        try(RpcPeerPool<Integer> pool=new RpcPeerPool<Integer>(2,Duration.ofMinutes(5),target -> creates.incrementAndGet(),disposed::add)) {
            RpcPeerPool<Integer>.Lease first=pool.acquire("agent");RpcPeerPool<Integer>.Lease ongoing=pool.acquire("agent");
            assertEquals(1,first.value());assertEquals(1,ongoing.value());
            first.invalidate();first.close();pool.reconcile(List.of("agent"));
            assertTrue(disposed.isEmpty());
            try(RpcPeerPool<Integer>.Lease next=pool.acquire("agent")) { assertEquals(2,next.value()); }
            assertEquals(2,pool.size());
            assertTrue(disposed.isEmpty());
            ongoing.close();assertEquals(List.of(1),disposed);
            first.invalidate();first.close();ongoing.invalidate();ongoing.close();
            assertEquals(List.of(1),disposed); // Late callbacks never close it twice.
        }
        assertEquals(List.of(1,2),disposed);
    }
    @Test void drainingGenerationsStillCountTowardsCapacityAndCannotCloseTheirReplacement() {
        AtomicInteger creates=new AtomicInteger();ArrayList<Integer> disposed=new ArrayList<Integer>();
        try(RpcPeerPool<Integer> pool=new RpcPeerPool<Integer>(2,Duration.ofMinutes(5),target -> creates.incrementAndGet(),disposed::add)) {
            RpcPeerPool<Integer>.Lease first=pool.acquire("agent");assertEquals(1,first.value());first.invalidate();
            RpcPeerPool<Integer>.Lease second=pool.acquire("agent");assertEquals(2,second.value());second.invalidate();
            assertEquals(2,pool.size());
            assertThrows(IllegalStateException.class,() -> pool.acquire("agent"));
            first.close();
            try(RpcPeerPool<Integer>.Lease replacement=pool.acquire("agent")) { assertEquals(3,replacement.value()); }
            first.invalidate();first.close();
            try(RpcPeerPool<Integer>.Lease same=pool.acquire("agent")) { assertEquals(3,same.value()); }
            second.close();assertEquals(List.of(1,2),disposed);
        }
        assertEquals(List.of(1,2,3),disposed);
    }
    @Test void lateStreamFailureAfterCancellationRetiresTheIdlePeerOnce() {
        ArrayList<String> disposed=new ArrayList<String>();
        try(RpcPeerPool<String> pool=new RpcPeerPool<String>(2,Duration.ofMinutes(5),target -> target,disposed::add)) {
            RpcPeerPool<String>.Lease cancelled=pool.acquire("agent");cancelled.value();cancelled.close();
            cancelled.invalidate();cancelled.invalidate();
            assertEquals(List.of("agent"),disposed);assertEquals(0,pool.size());
        }
        assertEquals(List.of("agent"),disposed);
    }
    @Test void endpointChurnBeyondCapacityClosesWithdrawnPeers() {
        ArrayList<String> closed=new ArrayList<String>();
        try(RpcPeerPool<String> pool=new RpcPeerPool<String>(4,Duration.ofMinutes(5),s -> s,closed::add)) {
            for(int i=0;i<100;i++) {
                String endpoint="peer-"+i;
                pool.reconcile(List.of(endpoint));
                try(RpcPeerPool<String>.Lease lease=pool.acquire(endpoint)) { assertEquals(endpoint,lease.value()); }
                assertEquals(1,pool.size());
            }
        }
        assertEquals(100,closed.size());assertEquals(100,new HashSet<>(closed).size());
    }
    @Test void withdrawalAndShutdownDrainActiveCallsAndCloseExactlyOnce() {
        ArrayList<String> closed=new ArrayList<String>();RpcPeerPool<String> pool=new RpcPeerPool<String>(2,Duration.ZERO,s -> s,closed::add);
        RpcPeerPool<String>.Lease active=pool.acquire("old");active.value();pool.reconcile(List.of("new"));
        assertTrue(closed.isEmpty());
        try(RpcPeerPool<String>.Lease next=pool.acquire("new")) { next.value(); }
        pool.close();assertEquals(List.of("new"),closed);
        active.close();active.close();assertEquals(List.of("new","old"),closed);
        assertThrows(IllegalStateException.class,() -> pool.acquire("other"));
    }
    @Test void capacityEvictsIdleButNeverActiveCallsAndIdleTtlWorks() {
        AtomicLong tick=new AtomicLong();ArrayList<String> closed=new ArrayList<String>();
        try(RpcPeerPool<String> pool=new RpcPeerPool<String>(1,Duration.ofNanos(10),s -> s,closed::add,tick::get)) {
            RpcPeerPool<String>.Lease first=pool.acquire("a");first.value();
            assertThrows(IllegalStateException.class,() -> pool.acquire("b"));
            first.close();
            try(RpcPeerPool<String>.Lease second=pool.acquire("b")) { second.value(); }
            assertEquals(List.of("a"),closed);
            tick.set(11);pool.reconcile(List.of("b"));assertEquals(List.of("a","b"),closed);
        }
    }
    @Test void initializationIsSingleFlightAndDoesNotBlockOtherEndpoints() throws Exception {
        CountDownLatch started=new CountDownLatch(1);CountDownLatch release=new CountDownLatch(1);AtomicInteger creates=new AtomicInteger();
        try(RpcPeerPool<String> pool=new RpcPeerPool<String>(4,Duration.ofMinutes(5),target -> {
            creates.incrementAndGet();if(target.equals("slow")) { started.countDown();try { release.await(); } catch(InterruptedException e){throw new RuntimeException(e);} }return target;
        },s -> {});ExecutorService executor=Executors.newVirtualThreadPerTaskExecutor()) {
            Future<String> one=executor.submit(() -> { try(RpcPeerPool<String>.Lease lease=pool.acquire("slow")){return lease.value();} });
            assertTrue(started.await(2,TimeUnit.SECONDS));
            Future<String> two=executor.submit(() -> { try(RpcPeerPool<String>.Lease lease=pool.acquire("slow")){return lease.value();} });
            try(RpcPeerPool<String>.Lease fast=pool.acquire("fast")){assertEquals("fast",fast.value());}
            release.countDown();assertEquals("slow",one.get(2,TimeUnit.SECONDS));assertEquals("slow",two.get(2,TimeUnit.SECONDS));
            assertEquals(2,creates.get());
        } finally { release.countDown(); }
    }
}
