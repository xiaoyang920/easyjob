"""Verify the gateway assertion before any public Agent handler reads a body."""
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from time import monotonic

import jwt
from starlette.responses import JSONResponse

from app.config import settings
from app.security.delegation import current_identity
from app.services.logging_config import request_trace

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def public_key():
    return jwt.PyJWK.from_dict(json.loads(
        Path(settings.GATEWAY_IDENTITY_PUBLIC_KEY_FILE).read_text(encoding='utf-8'))).key


def verify(token, method, path):
    claims = jwt.decode(token, public_key(), algorithms=['RS256'],
        issuer='easyjob-gateway', audience='easyjob-agent', leeway=5,
        options={'require': ['iss', 'aud', 'sub', 'iat', 'nbf', 'exp', 'jti', 'sid', 'ver', 'token_use']})
    if (claims['token_use'] != 'gateway' or claims.get('kind') != 'user'
            or claims.get('method') != method or claims.get('path') != path
            or not 0 < claims['exp'] - claims['iat'] <= 20
            or not isinstance(claims['sub'], str) or not re.fullmatch(r'[1-9][0-9]{0,18}', claims['sub'])
            or int(claims['sub']) >= 2**63
            or not isinstance(claims['sid'], str) or not re.fullmatch(r'[a-f0-9]{64}', claims['sid'])
            or type(claims['ver']) is not int or claims['ver'] < 0):
        raise ValueError('Invalid gateway identity')
    return claims


class GatewayIdentityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or not (path == '/api/agent' or path.startswith('/api/agent/')):
            return await self.app(scope, receive, send)
        try:
            tokens = [v.decode('ascii') for k, v in scope['headers'] if k.lower() == b'x-easyjob-identity']
            if len(tokens) != 1:
                raise ValueError('Missing gateway assertion')
            claims = verify(tokens[0], scope['method'], path)
        except (OSError, json.JSONDecodeError):
            return await JSONResponse({'status': 'error', 'code': 503,
                'message': '身份校验服务暂不可用', 'data': None}, status_code=503)(scope, receive, send)
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, UnicodeError):
            return await JSONResponse({'status': 'error', 'code': 401,
                'message': '请求身份无效，请通过统一入口访问', 'data': None}, status_code=401)(scope, receive, send)
        identity = {'user_id': int(claims['sub']), 'sid': claims['sid'], 'version': claims['ver']}
        scope.setdefault('state', {})['gateway_identity'] = identity
        token = current_identity.set(identity)
        started, status = monotonic(), 500

        async def capture(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            await send(message)

        try:
            with request_trace(trace_id=claims.get('trace')):
                try:
                    await self.app(scope, receive, capture)
                finally:
                    log.info('gateway_http method=%s path=%s status=%s duration_ms=%.2f',
                             scope['method'], path, status, (monotonic() - started) * 1000)
        finally:
            current_identity.reset(token)
