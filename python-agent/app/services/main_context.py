"""Full-request compaction admission, one pass per decision, no threshold loop."""
import hashlib
import logging

from app.config import settings
from app.services.conversation import ConversationService
from app.services.agent_events import activity
from app.utils.context_budget import json_text, request_tokens, input_budget, split_history, message_tokens

log = logging.getLogger(__name__)
context_service = ConversationService()


def history_version(history):
    return hashlib.sha256(json_text(history).encode('utf-8')).hexdigest()


async def prepare_context(state, render, schemas, *, fence=None):
    history = state.get('history_messages', [])
    before = request_tokens(render(history), schemas)
    hard_limit = input_budget()
    trigger = min(settings.CONTEXT_COMPACT_TRIGGER_TOKENS, hard_limit)
    previous = state.get('context_compaction') or {}
    versions = list(previous.get('attempted_versions', []))
    metadata = {'attempted_versions': versions, 'before_tokens': before, 'after_tokens': before,
                'round': state.get('main_round', 0) + 1, 'status': 'below_threshold'}
    def finish(status, updated=history, **extra):
        metadata.update(status=status, **extra)
        update = {'context_compaction': metadata}
        if updated is not history:
            update['history_messages'] = updated
        return {**state, **update}, update
    if before < trigger:
        return finish('below_threshold')
    version = history_version(history)
    if version in versions:
        return finish('already_attempted')
    versions.append(version)
    mandatory = request_tokens(render([]), schemas)
    if mandatory > hard_limit:
        return finish('mandatory_over_budget')
    _, turns = split_history(history)
    if len(turns) < 2:
        return finish('no_early_history')
    # Target the whole input. A latest complete turn is protected even when it
    # exceeds the 24K soft recent target; the final request still obeys 112K.
    target = min(settings.CONTEXT_COMPACT_TARGET_TOKENS, trigger)
    recent_budget = min(settings.HISTORY_RECENT_TOKENS,
                        max(0, target - mandatory - settings.SUMMARY_MAX_TOKENS - 512))
    retained = list(turns[-1])
    retained_tokens = sum(message_tokens(message) for message in retained)
    for turn in reversed(turns[:-1]):
        cost = sum(message_tokens(message) for message in turn)
        if retained_tokens + cost > recent_budget:
            break
        retained = [*turn, *retained]
        retained_tokens += cost
    prefix_count = sum(len(turn) for turn in turns) - len(retained)
    if not prefix_count:
        return finish('no_early_history')
    # Reserve the maximum possible new summary before deciding to pay for it.
    estimated_after = request_tokens(render(retained), schemas) + settings.SUMMARY_MAX_TOKENS + 512
    minimum_saving = settings.CONTEXT_COMPACT_MIN_SAVING_TOKENS
    if before > hard_limit:
        minimum_saving = min(minimum_saving, before - hard_limit + 256)
    if before - estimated_after < minimum_saving:
        return finish('insufficient_expected_saving')
    def accept(updated):
        return before - request_tokens(render(updated), schemas) >= minimum_saving
    event_state = {**state, 'main_round': metadata['round']}
    if fence is not None:
        await fence(state)
    await activity(event_state, 'context_compaction', '整理早期对话')
    try:
                result = await context_service.compact_history(state.get('conversation_id'), history, prefix_count,
                                                       accept=accept, user_id=state.get('user_id'),
                                                       before_commit=(lambda: fence(state)) if fence is not None else None)
    except Exception as exc:
        if fence is not None:
            await fence(state)
        log.warning('历史压缩未完成: type=%s input_tokens=%d', type(exc).__name__, before)
        await activity(event_state, 'context_compaction', '整理早期对话', 'error', '未完成压缩，按输入预算处理')
        return finish('failed', summary_calls=getattr(exc, 'compaction_calls', 0),
                      summary_usage=getattr(exc, 'compaction_usage', []))
    updated = result['history']
    if updated is not history:
        versions.append(history_version(updated))
    after = request_tokens(render(updated), schemas)
    log.info('Main context admission: before=%d after=%d status=%s', before, after, result['status'])
    await activity(event_state, 'context_compaction', '整理早期对话', 'done',
                   f'已整理{result.get("processed_messages", 0)}条早期消息' if result['status'] == 'compacted' else '无需重复压缩，按输入预算继续')
    return finish(result['status'], updated, after_tokens=after, summary_calls=result.get('summary_calls', 0),
                  persisted=result.get('persisted', False), summary_usage=result.get('summary_usage', []))
