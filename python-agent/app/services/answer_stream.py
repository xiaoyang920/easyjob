"""Stream a source-free Main answer; audited candidates remain private."""
import time

from langchain_core.utils.json import parse_partial_json


# Explicit headers must be complete before the reply begins. Missing/defaulted
# headers are deliberately buffered: they could still arrive after reply.
DIRECT_HEADER = {
    'action': 'answer', 'evidence_assessment': None, 'artifacts': [],
    'answer_dependencies': [], 'reuse_previous_results': [], 'retrieval': None,
    'draft_request': None, 'plan': None, 'delegation_reason': '',
    'memory_changes': [], 'constraint_overrides': [],
}


def can_stream_direct_answer(state):
    """Backend eligibility, independent of the model's requested action."""
    return (state.get('main_round', 0) == 0
        and state.get('correction_count', 0) == 0
        and not any(state.get(key) for key in (
            'task_results', 'citations', 'article_cards', 'article_context',
            'origin_article_id', 'delivery_evidence', 'delivery_review',
            'business_complete', 'memory_write_status', 'pending_memory_changes',
            'active_workers', 'observations', 'backend_boundary')))


class DirectAnswerStream:
    def __init__(self, min_interval=.12):
        self.calls = {}
        self.call_id = None
        self.text = ''
        self.sequence = 0
        self.started = False
        self.min_interval = min_interval
        self.sent_at = 0.

    def consume(self, event):
        metadata = event.get('metadata') or {}
        if (metadata.get('langgraph_node') != 'main_agent'
                or metadata.get('public_answer_stream') is not True):
            return []
        kind, run_id = event.get('event'), event.get('run_id')
        if kind == 'on_chat_model_end':
            call = self.calls.get((run_id, 0))
            return self.publish((run_id, 0), call, force=True) if call else []
        if kind != 'on_chat_model_stream':
            return []
        chunk = event.get('data', {}).get('chunk')
        events = []
        # Plain model content/reasoning and every other function are private.
        for part in getattr(chunk, 'tool_call_chunks', None) or []:
            key = (run_id, part.get('index', 0))
            call = self.calls.setdefault(key, {'name': '', 'args': '', 'blocked': False})
            call['name'] += part.get('name') or ''
            if call['blocked']:
                continue
            call['args'] += part.get('args') or ''
            if len(call['args']) > 200_000:
                call['blocked'] = True
                continue
            events.extend(self.publish(key, call))
        return events

    def publish(self, key, call, force=False):
        if call['blocked'] or call['name'] != 'MainDecision' or key[1] != 0:
            return []
        if self.call_id is not None and key != self.call_id:
            return []  # Format-repair/retry calls may not replace live text.
        try:
            value = parse_partial_json(call['args'])
        except (ValueError, TypeError):
            return []
        if not isinstance(value, dict):
            return []
        reply_field = 'user_reply' if 'user_reply' in value else 'reply'
        if not isinstance(value.get(reply_field), str):
            return []
        if (any(field not in value or value[field] != expected for field, expected in DIRECT_HEADER.items())
                or set(value) != {*DIRECT_HEADER, reply_field} or list(value)[-1] != reply_field):
            return []
        reply = value[reply_field]
        if not reply.strip() or reply == self.text:
            return []
        from app.graph.staged_runtime import invalid_references
        from app.services.execution_facts import execution_facts, execution_issues
        if invalid_references(reply, []) or execution_issues(reply, execution_facts({})):
            call['blocked'] = True
            return []
        if not reply.startswith(self.text):
            call['blocked'] = True
            return []
        now = time.monotonic()
        if self.started and not force and now - self.sent_at < self.min_interval:
            return []
        frames = []
        if not self.started:
            self.call_id, self.started = key, True
            frames.append({'type': 'start', 'mode': 'direct'})
        frames.append({'type': 'delta', 'seq': self.sequence,
                       'content': reply[len(self.text):]})
        self.text, self.sent_at = reply, now
        self.sequence += 1
        return frames

    def finish(self, text):
        """Keep the live sequence; never blank and retransmit an unchanged answer."""
        if not self.started:
            return []
        frames = []
        if text.startswith(self.text) and text != self.text:
            frames.append({'type': 'delta', 'seq': self.sequence, 'content': text[len(self.text):]})
            self.sequence += 1
        frames.append({'type': 'end', 'chunks': self.sequence})
        # __REPLY__ is still the authoritative settled message, including when
        # cancellation, contract failure, or storage failure prevents completion.
        return frames
