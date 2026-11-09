"""Bounded, read-only Java -> Agent warmup; never replay a user operation."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python-agent'))
import httpx
from app.config import settings


async def wait_ready(client, timeout=25, consecutive=2, interval=.3):
    deadline = monotonic() + timeout
    attempts = failures = successes = 0
    while monotonic() < deadline:
        attempts += 1
        ready = False
        try:
            response = await asyncio.wait_for(client.get('/internal/agent/ready'),
                                              timeout=max(.001, deadline - monotonic()))
            if response.status_code in (401, 403, 404):
                # Wrong service key or an old Java build will not heal on retry.
                return {'status': 'unavailable', 'reason': 'configuration', 'http_status': response.status_code}
            ready = response.status_code == 200 and response.json() == {'status': 'ready', 'rpc': 'ok'}
        except (httpx.TransportError, TimeoutError, ValueError):
            pass
        successes = successes + 1 if ready else 0
        failures += int(not ready)
        if successes >= consecutive:
            return {'status': 'ready', 'attempts': attempts, 'failed_probes': failures}
        await asyncio.sleep(min(interval, max(0, deadline - monotonic())))
    return {'status': 'unavailable', 'reason': 'deadline', 'attempts': attempts, 'failed_probes': failures}


async def main(timeout):
    if len(settings.AGENT_SERVICE_KEY.encode()) < 32:
        result = {'status': 'unavailable', 'reason': 'service_identity'}
    else:
        async with httpx.AsyncClient(base_url=settings.JAVA_AGENT_URL.rstrip('/'),
                headers={'X-Agent-Key': settings.AGENT_SERVICE_KEY},
                timeout=httpx.Timeout(20, connect=2), trust_env=False, follow_redirects=False) as client:
            result = await wait_ready(client, timeout)
    print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'ready' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=25)
    raise SystemExit(asyncio.run(main(parser.parse_args().timeout)))
