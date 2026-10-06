"""Expose only user-facing reply text, never tool arguments or reasoning.

Previews are provisional: final gates and settlement still own the delivered answer.
The same model call continues to produce the validated structured decision.
"""
import json
import time
from langchain_core.utils.json import parse_partial_json


class AnswerPreview:
    def __init__(self, min_interval=.05):
        self.calls = {}
        self.min_interval = min_interval

    def publish(self, call, force=False):
        text, previous = call['reply'], call.get('sent', '')
        now = time.monotonic()
        if text == previous or (not force and previous and now - call.get('sent_at', 0) < self.min_interval):
            return None
        call.update(sent=text, sent_at=now)
        return {'type': 'delta' if previous and text.startswith(previous) else 'replace',
                'content': text[len(previous):] if previous and text.startswith(previous) else text,
                'provisional': True}

    def consume(self, event):
        if event.get('event') == 'on_chat_model_end':
            for key, call in self.calls.items():
                if key[0] == event.get('run_id') and (pending := self.publish(call, force=True)):
                    return pending
        if event.get('event') != 'on_chat_model_stream':
            return None
        node = event.get('metadata', {}).get('langgraph_node')
        chunk = event.get('data', {}).get('chunk')
        if event.get('metadata', {}).get('public_preview') == 'draft':
            content = getattr(chunk, 'content', None)
            if not isinstance(content, str) or not content:
                return None
            key = (event.get('run_id'), 'draft')
            call = self.calls.setdefault(key, {'reply': ''})
            if len(call['reply']) < 100_000:
                call['reply'] += content
            return self.publish(call)
        if node != 'main_agent':
            return None
        # ChatOpenAI provides incremental function-call arguments here. Ordinary
        # content can contain reasoning/routing and must never be forwarded.
        parts = getattr(chunk, 'tool_call_chunks', None) or []
        for part in parts:
            key = (event.get('run_id'), part.get('index', 0))
            call = self.calls.setdefault(key, {'name': '', 'args': '', 'reply': ''})
            call['name'] += part.get('name') or ''
            call['args'] += part.get('args') or ''
            if call['name'] != 'MainDecision' or len(call['args']) > 200_000:
                continue
            try:
                value = parse_partial_json(call['args'])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(value, dict) or value.get('action') != 'answer':
                continue
            reply = value.get('reply')
            if not isinstance(reply, str):
                continue
            call['reply'] = reply
            return self.publish(call)
        return None
