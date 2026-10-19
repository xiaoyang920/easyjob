package com.easyjob.agent.rpc;

import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.*;

/** Bounded endpoint resources. Removed/idle peers drain in-flight calls before closing. */
public final class RpcPeerPool<T> implements AutoCloseable {
    private final int capacity;
    private final long idleNanos;
    private final LongSupplier clock;
    private final Function<String,T> factory;
    private final Consumer<T> disposer;
    private final Map<String,Entry> entries=new LinkedHashMap<>();
    private final Set<Entry> draining=new HashSet<>();
    private boolean closed;
    private final class Entry {
        final FutureTask<T> resource;
        int active;
        long used;
        boolean retired;
        boolean invalid;
        final String target;
        final AtomicBoolean disposed = new AtomicBoolean();
        Entry(String target) { this.target=target;resource=new FutureTask<>(() -> factory.apply(target)); }
    }
    public RpcPeerPool(int capacity, Duration idle, Function<String,T> factory, Consumer<T> disposer) {
        this(capacity,idle,factory,disposer,System::nanoTime);
    }
    public RpcPeerPool(int capacity, Duration idle, Function<String,T> factory, Consumer<T> disposer, LongSupplier clock) {
        if(capacity<1 || idle.isNegative()) throw new IllegalArgumentException("Invalid pool limits");
        this.capacity=capacity; idleNanos=idle.toNanos(); this.factory=factory;this.disposer=disposer;this.clock=clock;
    }
    public final class Lease implements AutoCloseable {
        private final Entry entry;
        private final AtomicBoolean released=new AtomicBoolean();
        private Lease(Entry entry) { this.entry=entry; }
        public T value() {
            entry.resource.run(); // Single initialization, outside the pool lock.
            try { return entry.resource.get(); }
            catch(InterruptedException error) { Thread.currentThread().interrupt();throw new IllegalStateException("RPC initialization interrupted",error); }
            catch(ExecutionException error) { synchronized(RpcPeerPool.this) { entry.retired=true; }
                throw new IllegalStateException("RPC initialization failed",error.getCause()); }
        }
        /** Retire a failed connection; never replay the operation that failed. */
        public void invalidate() {
            boolean dispose;
            synchronized(RpcPeerPool.this) {
                entry.invalid=true;entry.retired=true;
                // A stopped/failed stream must not quarantine unrelated calls
                // until every old subscriber finishes. New calls get a fresh
                // generation; only existing leases keep the failed resource.
                entries.remove(entry.target,entry);
                dispose=entry.active==0;
                if(!dispose) draining.add(entry);
                else draining.remove(entry);
            }
            if(dispose) dispose(entry);
        }
        @Override public void close() {
            if(!released.compareAndSet(false,true)) return;
            boolean dispose;
            synchronized(RpcPeerPool.this) {
                entry.active--;entry.used=clock.getAsLong();
                dispose=entry.active==0 && (entry.retired || closed);
                if(dispose) { entries.remove(entry.target,entry);draining.remove(entry); }
            }
            if(dispose) dispose(entry);
        }
    }
    public Lease acquire(String target) {
        Entry evicted=null, entry;
        synchronized(this) {
            if(closed) throw new IllegalStateException("RPC pool closed");
            entry=entries.get(target);
            if(entry==null) {
                if(entries.size()+draining.size()>=capacity) {
                    var victim=entries.entrySet().stream().filter(e -> e.getValue().active==0)
                        .min(Comparator.comparingLong(e -> e.getValue().used));
                    if(victim.isEmpty()) throw new IllegalStateException("RPC endpoint pool busy");
                    evicted=entries.remove(victim.get().getKey());
                }
                entry=new Entry(target);entries.put(target,entry);
            }
            entry.retired=false;entry.active++;entry.used=clock.getAsLong();
        }
        if(evicted!=null) dispose(evicted);
        return new Lease(entry);
    }
    public void reconcile(Collection<String> healthy) {
        var removed=new ArrayList<Entry>();
        synchronized(this) {
            long now=clock.getAsLong();
            var iterator=entries.entrySet().iterator();
            while(iterator.hasNext()) {
                var item=iterator.next();var entry=item.getValue();
                entry.retired=entry.retired || !healthy.contains(item.getKey());
                if(entry.active==0 && (entry.retired || now-entry.used>=idleNanos)) {
                    iterator.remove();removed.add(entry);
                }
            }
        }
        removed.forEach(this::dispose);
    }
    public synchronized int size() { return entries.size()+draining.size(); }
    private void dispose(Entry entry) {
        if(!entry.resource.isDone() || entry.resource.isCancelled()) return;
        if(!entry.disposed.compareAndSet(false,true)) return;
        try { disposer.accept(entry.resource.get()); }
        catch(InterruptedException error) { Thread.currentThread().interrupt(); }
        catch(ExecutionException ignored) { /* Failed construction has no resource. */ }
        catch(RuntimeException error) { org.slf4j.LoggerFactory.getLogger(RpcPeerPool.class)
            .warn("rpc_peer_close_failed type={}",error.getClass().getSimpleName()); }
    }
    @Override public void close() {
        synchronized(this) { closed=true; }
        reconcile(List.of());
    }
}
