"""Numeric-only context-window telemetry, not cumulative token billing."""
import json
from datetime import datetime, timezone

from app.config import settings


def context_usage(view=None):
    if isinstance(view, str):
        try:
            view = json.loads(view)
        except (ValueError, TypeError):
            view = None
    view = view if isinstance(view, dict) else {}
    saved = view.get('window')
    saved = saved if isinstance(saved, dict) else {}

    def limit(name, fallback):
        value = saved.get(name)
        return value if type(value) is int and value > 0 else fallback

    total = limit('limitTokens', settings.MAIN_CONTEXT_MAX_TOKENS)
    output = limit('outputReserveTokens', settings.MAIN_OUTPUT_MAX_TOKENS)
    safety = limit('safetyReserveTokens', settings.CONTEXT_SAFETY_TOKENS)
    used = view.get('total_tokens')
    used = used if type(used) is int and used >= 0 else None
    return {'scope': 'main_request', 'estimated': True, 'usedTokens': used,
            'limitTokens': total, 'inputBudgetTokens': max(0, total - output - safety),
            'outputReserveTokens': output, 'safetyReserveTokens': safety,
            'measuredAt': saved.get('measuredAt') if isinstance(saved.get('measuredAt'), str) else None}


def measured_context_usage(breakdown):
    result = context_usage(breakdown)
    result['measuredAt'] = datetime.now(timezone.utc).isoformat()
    return result


async def conversation_context_usage(cid, uid, conversations, runs):
    if cid is None:
        return context_usage()
    await conversations.require_owner(cid, uid)
    return context_usage(await runs.latest_context_view(cid, uid))
