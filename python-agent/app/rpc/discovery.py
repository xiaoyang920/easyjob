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
        self.lock = asyncio.Lock()
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
            self.task = asyncio.create_task(self.heartbeat(), name='consul-registration')

    async def target(self, user_id):
        async with self.lock:
            now = time.monotonic()
            if now - self.refreshed > 5:
                try:
                    response = await self.http('GET', '/v1/health/service/easyjob-blog?passing=true')
                    peers = []
                    for item in response.json():
                        s = item['Service']; host = s['Address']; port = int(s['Meta']['rpc_port'])
                        if not host or not 0 < port < 65536 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:-' for c in host):
                            continue
                        peers.append(f'[{host}]:{port}' if ':' in host else f'{host}:{port}')
                    self.peers = sorted(set(peers)); self.refreshed = now
                except (httpx.HTTPError, ValueError, KeyError):
                    if now - self.refreshed > 30:
                        self.peers = []
            if not self.peers:
                raise RuntimeError('No healthy Blog instance')
            return max(self.peers, key=lambda peer: hashlib.sha256(f'{user_id}:{peer}'.encode()).digest())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.enabled:
            try:
                await self.http('PUT', '/v1/agent/service/deregister/' + self.instance)
            except httpx.HTTPError:
                pass
        if self.client:
            await self.client.aclose(); self.client = None


catalog = Catalog()
