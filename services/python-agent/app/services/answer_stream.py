"""Stream Main answers after validating the controls and selected evidence."""
from contextvars import ContextVar
import json
import re
import time

from langchain_core.utils.json import parse_partial_json


live_answer_controls = ContextVar('live_answer_controls', default=None)
REFERENCE_TAIL = re.compile(r'\[[a-z0-9_:]*\]?$')


# Explicit headers must be complete before the reply begins. Missing/defaulted
# headers are deliberately buffered: they could still arrive after reply.
DIRECT_HEADER = {
    'action': 'answer', 'evidence_assessment': None, 'artifacts': [],
    'answer_dependencies': [], 'reuse_previous_results': [], 'tool_call': None,
    'editor_edits': [],
    'draft_request': None, 'plan': None, 'delegation_reason': '',
    'memory_changes': [], 'constraint_overrides': [],
    'task_context_patch': None,
}


def can_stream_direct_answer(state):
    """Backend eligibility, independent of the model's requested action."""
    return (state.get('correction_count', 0) == 0
        and not any(state.get(key) for key in (
            'editor_edits', 'delivery_review', 'business_complete', 'pending_memory_changes', 'active_workers')))


class DirectAnswerStream:
    def __init__(self, min_interval=.12):
        self.calls = {}
        self.call_id = None
        self.text = ''
        self.sequence = 0
        self.started = False
        self.min_interval = min_interval
        self.sent_at = 0.
        self.controls = {}
        self.citations = []
        self.evidence_checked = False

    def consume(self, event):
        metadata = event.get('metadata') or {}
        if (metadata.get('langgraph_node') != 'main_agent'
                or metadata.get('public_answer_stream') is not True):
            return []
        kind, run_id = event.get('event'), event.get('run_id')
        if kind == 'on_chat_model_end':
            call = self.calls.pop((run_id, 0), None)
            return self.publish((run_id, 0), call, force=True) if call else []
        if kind != 'on_chat_model_stream':
            return []
        chunk = event.get('data', {}).get('chunk')
        events = []
        # Plain model content/reasoning and every other function are private.
        for part in getattr(chunk, 'tool_call_chunks', None) or []:
            key = (run_id, part.get('index', 0))
            if key[1] != 0:
                continue
            if key not in self.calls:
                self.calls[key] = {'name': '', 'args': '', 'blocked': False,
                                   'validator': self.controls.pop(metadata.get('context_round'), None)}
            call = self.calls[key]
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
        if call['blocked'] or call['name'] not in ('MainDecision', 'BrowserDecision') or key[1] != 0:
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
        if call['name'] == 'BrowserDecision':
            if (not call['validator'] or value.get('action') != 'answer' or 'tool_call' not in value
                    or value['tool_call'] is not None
                    or set(value) - {'action', 'tool_call', 'progress_note', 'user_reply'}
                    or list(value)[-1] != 'user_reply'):
                return []
        else:
            adjustable = {'evidence_assessment', 'answer_dependencies', 'reuse_previous_results'} if call['validator'] else set()
            if (any(field not in value or (field not in adjustable and value[field] != expected)
                    for field, expected in DIRECT_HEADER.items())
                    or (not call['validator'] and value.get('progress_note') not in (None, ''))
                    or set(value) - {'progress_note'} != {*DIRECT_HEADER, reply_field} or list(value)[-1] != reply_field):
                return []
        reply = value[reply_field]
        # Keep an unfinished reference out of the visible prefix. A trailing
        # closed reference waits for one more character to distinguish links.
        if not force and (tail := REFERENCE_TAIL.search(reply)):
            try:
                json.loads(call['args'])
            except ValueError:
                reply = reply[:tail.start()]
        if not reply.strip() or reply == self.text:
            return []
        from app.graph.staged_runtime import invalid_references
        from app.services.execution_facts import execution_facts, execution_issues
        if 'checked_controls' not in call:
            try:
                call['checked_controls'] = call['validator'](value) if call['validator'] else ([], execution_facts({}))
            except ValueError:
                call['blocked'] = True
                return []
        citations, facts = call['checked_controls']
        if invalid_references(reply, citations) or execution_issues(reply, facts):
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
            self.citations = citations
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
