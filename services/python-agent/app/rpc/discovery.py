"""Shared Consul health catalog. Native gRPC clients never retry writes at another instance."""
import asyncio
import hashlib
import os
import time
import httpx


class Catalog:
    def __init__(self):
        self.enabled = os.getenv('SERVICE_DISCOVERY_ENABLED', 'false').lower() == 'true'
        self.base = os.getenv('CONSUL_URL', 'http://127.0.0.1:8500').rstrip('/')
        self.address = os.getenv('SERVICE_ADVERTISE_HOST', '127.0.0.1')
        self.port = int(os.getenv('AGENT_HTTP_PORT', '8000'))
        self.rpc_port = int(os.getenv('AGENT_RPC_BIND', '127.0.0.1:50051').rsplit(':', 1)[1])
        self.instance = os.getenv('AGENT_INSTANCE_ID') or f'easyjob-agent-{self.address}-{self.port}'
        self.client = None
        self.task = None
        self.refresh_task = None
        self.peers = []
        self.refreshed = -1000.0

    async def http(self, method, path, **kwargs):
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.base, timeout=2,
                headers={'X-Consul-Token': os.getenv('CONSUL_TOKEN', '')}, trust_env=False)
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    async def heartbeat(self):
        while True:
            try:
                await self.http('PUT', '/v1/agent/service/register', json={
                    'ID': self.instance, 'Name': 'easyjob-agent', 'Address': self.address, 'Port': self.port,
                    'Meta': {'rpc_port': str(self.rpc_port)},
                    'Check': {'TTL': '30s', 'DeregisterCriticalServiceAfter': '5m'}})
                await self.http('PUT', '/v1/agent/check/pass/service:' + self.instance)
            except (httpx.HTTPError, ValueError):
                pass  # A dead process loses its TTL health automatically.
            await asyncio.sleep(10)

    async def start(self):
        if self.enabled and self.task is None:
            await self.refresh()
            self.task = asyncio.create_task(self.heartbeat(), name='consul-registration')
            self.refresh_task = asyncio.create_task(self.refresh_loop(), name='consul-discovery')

    async def refresh_loop(self):
        while True:
            await asyncio.sleep(5)
            await self.refresh()
            from .blog_client import pool
            await pool.reconcile(self.healthy_targets())

    async def refresh(self):
        try:
            response = await self.http('GET', '/v1/health/service/easyjob-blog?passing=true')
            peers = []
            for item in response.json():
                s = item['Service']; host = s['Address']; port = int(s['Meta']['rpc_port'])
                if not host or not 0 < port < 65536 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:-' for c in host):
                    continue
                peers.append(f'[{host}]:{port}' if ':' in host else f'{host}:{port}')
            # No await between publication of these fields: atomic to async readers.
            self.peers = tuple(sorted(set(peers)))
            self.refreshed = time.monotonic()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass  # healthy_targets enforces expiry even while refresh is blocked.

    def healthy_targets(self):
        return self.peers if time.monotonic() - self.refreshed <= 30 else ()

    async def target(self, user_id):
        peers = self.healthy_targets()
        if not peers:
            raise RuntimeError('No healthy Blog instance')
        return max(peers, key=lambda peer: hashlib.sha256(f'{user_id}:{peer}'.encode()).digest())

    async def close(self):
        tasks = [task for task in (self.task, self.refresh_task) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.task = self.refresh_task = None
        self.peers = ()
        if self.enabled:
            try:
                await self.http('PUT', '/v1/agent/service/deregister/' + self.instance)
            except httpx.HTTPError:
                pass
        if self.client:
            await self.client.aclose(); self.client = None


catalog = Catalog()
