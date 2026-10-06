"""Identity issued by the authenticated Java boundary, never by the planner."""
import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.config import settings


@dataclass(frozen=True)
class Principal:
    user_id: int
    visible_scope: str = "published_public"


async def require_principal(request: Request) -> Principal:
    secret = settings.AGENT_SERVICE_KEY
    if len(secret.encode()) < 32:
        raise HTTPException(503, "Agent 服务认证尚未配置")
    if not hmac.compare_digest(request.headers.get("X-Agent-Key", ""), secret):
        raise HTTPException(401, "服务身份无效")
    try:
        user_id = int(request.headers.get("X-Agent-User", ""))
        if user_id <= 0:
            raise ValueError()
    except ValueError:
        raise HTTPException(401, "用户身份无效") from None
    return Principal(user_id)


def match_user(principal: Principal, claimed_user: int):
    if principal.user_id != claimed_user:
        raise HTTPException(403, "请求用户与可信身份不一致")
