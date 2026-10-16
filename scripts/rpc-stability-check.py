"""Isolated loopback gRPC/Consul fault and sustained-load probe; no database or model calls."""
import argparse
import asyncio
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'python-agent'))
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
import grpc
from app.rpc.discovery import Catalog
from app.rpc.peer_pool import PeerPool
from app.rpc.generated import easyjob_rpc_pb2 as pb, easyjob_rpc_pb2_grpc as api
from app.rpc.codec import encode, decode
from evaluation.metrics import percentile


def rss_bytes():
    """Current resident memory; None on unsupported hosts."""
    try:
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in
                    ('peak_working', 'working', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
            get_process = ctypes.windll.kernel32.GetCurrentProcess
            get_process.restype = wintypes.HANDLE
            get_info = ctypes.windll.psapi.GetProcessMemoryInfo
            get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            counters = Counters();counters.cb = ctypes.sizeof(counters)
            return counters.working if get_info(get_process(), ctypes.byref(counters), counters.cb) else None
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1])*1024
    except (OSError, AttributeError, ValueError):
        pass
    return None


class Backend(api.BlogRpcServicer):
    def __init__(self):
        self.writes = self.cancelled = 0
        self.entered = asyncio.Event()

    async def ReadPublic(self, request, context):
        if request.name == 'slow':
            self.entered.set()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        return pb.Reply(data=encode({'trace_id': request.identity.trace_id, 'ok': True}))

    async def SaveDraft(self, request, context):
        self.writes += 1
        await asyncio.sleep(.2)
        return pb.Reply(data=encode({'saved': True}))


async def run(args):
    state = {'targets': [], 'delay': 0, 'queries': 0}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state['queries'] += 1
            time.sleep(state['delay'])
            body = json.dumps([{'Service': {'Address': target.split(':')[0], 'Meta': {'rpc_port': target.split(':')[1]}}}
                for target in state['targets']]).encode()
            try:
                self.send_response(200);self.send_header('Content-Length', str(len(body)));self.end_headers();self.wfile.write(body)
            except (ConnectionError, OSError):
                pass
        def log_message(self, *args): pass
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    catalog = Catalog();catalog.base = f'http://127.0.0.1:{http.server_port}'
    catalog.client = None
    servers, closed = [], []
    created = 0
    def factory(target):
        nonlocal created
        created += 1
        channel = grpc.aio.insecure_channel(target, options=[('grpc.enable_retries', 0)])
        class Channel:
            async def close(self):
                await channel.close();closed.append(target)
        return Channel(), api.BlogRpcStub(channel)
    pool = PeerPool(factory, capacity=8, idle=30)
    records, checks, memory = [], {}, []

    async def backend():
        service = Backend();server = grpc.aio.server()
        api.add_BlogRpcServicer_to_server(service, server)
        port = server.add_insecure_port('127.0.0.1:0');await server.start();servers.append(server)
        return server, service, f'127.0.0.1:{port}'

    async def read(name='', timeout=2):
        target = await catalog.target(7)
        async with pool.lease(target, catalog.healthy_targets()) as stub:
            reply = await stub.ReadPublic(pb.BlogQuery(identity=pb.Identity(user_id=7,
                service_key='isolated-test-key', trace_id='stability-12345678'), name=name), timeout=timeout)
            return decode(reply.data)

    async def measured(phase):
        started = time.perf_counter()
        try:
            result = await read()
            error = None if result['trace_id'] == 'stability-12345678' else 'TraceMismatch'
        except Exception as exc:
            error = type(exc).__name__
        records.append({'phase': phase, 'duration_ms': (time.perf_counter()-started)*1000, 'error_type': error})

    try:
        previous = None
        for _ in range(args.churn):
            current, service, target = await backend()
            state['targets'] = [target];await catalog.refresh();await pool.reconcile(catalog.healthy_targets())
            await measured('endpoint_churn')
            if previous:
                await previous.stop(0)
            previous = current
        checks['churn_reclaimed_connections'] = len(pool.entries) == 1 and len(closed) == args.churn-1
        queries = state['queries']
        state['delay'] = .5
        refreshing = asyncio.create_task(catalog.refresh())
        await asyncio.sleep(.03)
        started = time.perf_counter()
        await asyncio.gather(*(measured('slow_registry') for _ in range(args.users)))
        elapsed = time.perf_counter()-started
        checks['requests_do_not_wait_for_registry'] = elapsed < .4
        await refreshing;state['delay'] = 0
        checks['one_background_refresh'] = state['queries'] == queries+1
        until = time.perf_counter()+args.seconds
        monitor_stop = asyncio.Event()
        async def monitor():
            while not monitor_stop.is_set():
                memory.append({'rss_bytes': rss_bytes(), 'cached_channels': len(pool.entries),
                    'active_leases': sum(e.active for e in pool.entries.values()), 'async_tasks': len(asyncio.all_tasks())})
                try:
                    await asyncio.wait_for(monitor_stop.wait(), .5)
                except TimeoutError:
                    pass
        monitoring = asyncio.create_task(monitor())
        async def worker():
            while time.perf_counter() < until:
                await measured('sustained_load')
                await asyncio.sleep(.01)
        try:
            await asyncio.gather(*(worker() for _ in range(args.users)))
        finally:
            monitor_stop.set();await monitoring

        # Deadline and explicit cancellation both release their channel lease.
        try:
            await read('slow', timeout=.03)
            checks['deadline'] = False
        except grpc.aio.AioRpcError as error:
            checks['deadline'] = error.code() == grpc.StatusCode.DEADLINE_EXCEEDED
        service.entered.clear();task = asyncio.create_task(read('slow'))
        await asyncio.wait_for(service.entered.wait(), 2)
        task.cancel();await asyncio.gather(task, return_exceptions=True)
        checks['cancel_released_lease'] = all(entry.active == 0 for entry in pool.entries.values())

        target = await catalog.target(7)
        async with pool.lease(target, catalog.healthy_targets()) as stub:
            try:
                await stub.SaveDraft(pb.DraftRequest(identity=pb.Identity(user_id=7)), timeout=.03)
            except grpc.aio.AioRpcError:
                pass
        checks['mutation_not_transparently_retried'] = service.writes == 1

        state['targets'] = [];await catalog.refresh();await pool.reconcile(catalog.healthy_targets())
        try:
            await catalog.target(7)
            checks['empty_registry_fails_closed'] = False
        except RuntimeError:
            checks['empty_registry_fails_closed'] = not pool.entries
        state['targets'] = [target];await catalog.refresh()
        catalog.refreshed = time.monotonic()-31
        try:
            await catalog.target(7)
            checks['expired_snapshot_fails_closed'] = False
        except RuntimeError:
            checks['expired_snapshot_fails_closed'] = True
        await catalog.refresh();await previous.stop(0)
        try:
            await read()
            checks['dead_backend_fails_without_retry'] = False
        except grpc.aio.AioRpcError:
            checks['dead_backend_fails_without_retry'] = True
    finally:
        await pool.close()
        for server in servers:
            await server.stop(0)
        if catalog.client:
            await catalog.client.aclose()
        await asyncio.to_thread(http.shutdown);http.server_close()
    checks['all_channels_closed'] = created == len(closed)
    phases = {}
    for phase in sorted({r['phase'] for r in records}):
        subset = [r for r in records if r['phase'] == phase]
        phases[phase] = {'requests': len(subset), 'unexpected_errors': sum(bool(r['error_type']) for r in subset),
            'p50_ms': percentile([r['duration_ms'] for r in subset], 50),
            'p95_ms': percentile([r['duration_ms'] for r in subset], 95)}
    result = {'scope': 'real_loopback_grpc_with_fake_business_and_fake_consul; not_production_qps',
        'users': args.users, 'load_seconds': args.seconds, 'endpoint_replacements': args.churn,
        'channels_created': created, 'channels_closed': len(closed), 'llm_calls': 0,
        'memory_samples': memory, 'memory_scope': 'whole test process including growing measurement records; not an automatic leak verdict',
        'checks': checks, 'phases': phases,
        'passed': all(checks.values()) and not any(r['error_type'] for r in records)}
    output = Path(args.output);output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    output.with_suffix('.trials.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(not result['passed'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users', type=int, default=16)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--churn', type=int, default=64)
    parser.add_argument('--output', default=str(ROOT/'logs/rpc-stability.json'))
    args = parser.parse_args()
    if not 1 <= args.users <= 128 or not 1 <= args.seconds <= 300 or not 33 <= args.churn <= 256:
        parser.error('users 1..128, seconds 1..300, churn 33..256')
    raise SystemExit(asyncio.run(run(args)))
