"""Bounded, decision-local numeric memoization; never caches authorization."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
from time import perf_counter

active_calculations = ContextVar('context_calculations', default=None)


class ContextMessages(list):
    def __init__(self, messages, calculations):
        super().__init__(messages)
        self.calculations = calculations


class ContextCalculations:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.tokens = {}
        self.stats = {'token_requests': 0, 'token_encodes': 0, 'token_cache_hits': 0,
                      'result_hashes': 0, 'prepare_ms': 0}

    @contextmanager
    def activate(self):
        if active_calculations.get() is self:
            yield
            return
        started = perf_counter()
        marker = active_calculations.set(self)
        try:
            yield
        finally:
            active_calculations.reset(marker)
            self.stats['prepare_ms'] += (perf_counter() - started) * 1000

    def count(self, text, encode):
        self.stats['token_requests'] += 1
        # Store only digest/length -> integer, not another copy of the prompt.
        key = (hashlib.sha256(text.encode('utf-8')).digest(), len(text), 'cl100k_base:v1') if self.enabled else None
        if key is not None and key in self.tokens:
            self.stats['token_cache_hits'] += 1
            return self.tokens[key]
        self.stats['token_encodes'] += 1
        value = encode(text)
        if key is not None and len(self.tokens) < 512:
            self.tokens[key] = value
        return value

    def snapshot(self):
        return {**self.stats, 'prepare_ms': round(self.stats['prepare_ms'], 2),
                'cache_entries': len(self.tokens)}
