"""User delegation comes from a verified Blog signature, never a model/tool argument."""
import contextvars
import json
from functools import lru_cache
from pathlib import Path
import jwt
from fastapi import HTTPException
from app.config import settings

current_identity=contextvars.ContextVar('authenticated_delegation',default=None)
@lru_cache(maxsize=1)
def public_key():
    return jwt.PyJWK.from_dict(json.loads(Path(settings.BLOG_DELEGATION_PUBLIC_KEY_FILE).read_text(encoding='utf-8'))).key

def verify(identity,method):
    if not settings.AUTH_DELEGATION_ENABLED:return None
    try:
        claims=jwt.decode(identity.delegation_token,public_key(),algorithms=['RS256'],audience='easyjob-agent',issuer='easyjob-blog',leeway=5,options={'require':['iss','aud','sub','exp','iat','nbf','jti','token_use']})
        if claims['sub']!=str(identity.user_id) or claims['exp']-claims['iat']>60:raise ValueError()
        if claims['token_use']=='service_observe':
            if method!='ServiceQuery':raise ValueError()
            current_identity.set(None)
            return 'service_observe'
        if claims['token_use']!='delegation' or len(claims.get('sid',''))!=64 or not isinstance(claims.get('ver'),int):raise ValueError()
        current_identity.set({'user_id':identity.user_id,'sid':claims['sid'],'version':claims['ver']})
        return claims
    except (jwt.PyJWTError,ValueError,TypeError,KeyError):raise HTTPException(401,'用户委托身份无效') from None
