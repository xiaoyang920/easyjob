"""Count real model usage without retaining prompts, replies or credentials."""
from time import perf_counter
from langchain_core.callbacks import AsyncCallbackHandler
from app.config import settings
from app.utils.token_utils import count_tokens


class RunTokenBudgetExceeded(RuntimeError):
    pass


class RunMetrics(AsyncCallbackHandler):
    raise_error = True
    def __init__(self, previous=None):
        self.previous = previous or {}
        self.started = perf_counter()
        self.calls = set()
        self.finished = set()
        self.usage = {}
        self.models = set(self.previous.get('models') or [])
        self.errors = set()
        self.reservations = {}
        self.charged = int(self.previous.get('budget_charged_tokens') or
                           self.previous.get('measured_input_tokens', 0) + self.previous.get('measured_output_tokens', 0))

    def reserve(self, key, text, kwargs):
        if key in self.reservations or key in self.finished: return
        params = kwargs.get('invocation_params') or {}
        output = params.get('max_tokens') or params.get('max_completion_tokens') or settings.WORKER_OUTPUT_MAX_TOKENS
        reservation = count_tokens(text) + int(output) + 32
        if self.charged + sum(self.reservations.values()) + reservation > settings.RUN_TOTAL_TOKEN_BUDGET:
            raise RunTokenBudgetExceeded('本次运行累计 Token 预算不足，请缩小任务范围后重试')
        self.reservations[key] = reservation

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.reserve(str(run_id), '\n'.join(str(m.content) for batch in messages for m in batch), kwargs)
        self.calls.add(str(run_id))

    async def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self.reserve(str(run_id), '\n'.join(prompts), kwargs)
        self.calls.add(str(run_id))

    async def on_llm_end(self, response, *, run_id, **kwargs):
        key = str(run_id)
        if key in self.finished:
            return
        self.finished.add(key)
        self.calls.add(key)
        if model := (response.llm_output or {}).get('model_name'):
            self.models.add(model)
        usage = (response.llm_output or {}).get('token_usage') or {}
        if not usage:
            for group in response.generations:
                for generation in group:
                    usage = getattr(getattr(generation, 'message', None), 'usage_metadata', None) or {}
                    if usage:
                        break
        input_tokens = usage.get('input_tokens', usage.get('prompt_tokens'))
        output_tokens = usage.get('output_tokens', usage.get('completion_tokens'))
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            self.usage[key] = (input_tokens, output_tokens)
            self.charged += input_tokens + output_tokens
            self.reservations.pop(key, None)
        else:
            self.charged += self.reservations.pop(key, 0)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        # Provider failures may still have incurred usage; conservatively charge the reservation.
        key = str(run_id)
        if key in self.finished: return
        self.calls.add(key)
        self.errors.add(key)
        self.finished.add(key)
        self.charged += self.reservations.pop(key, 0)

    def snapshot(self):
        previous = self.previous
        calls = previous.get('llm_calls', 0) + len(self.calls)
        measured = previous.get('measured_llm_calls', 0) + len(self.usage)
        complete = calls > 0 and measured == calls
        input_measured = previous.get('measured_input_tokens', 0) + sum(v[0] for v in self.usage.values())
        output_measured = previous.get('measured_output_tokens', 0) + sum(v[1] for v in self.usage.values())
        return {'llm_calls': calls, 'models': sorted(self.models), 'measured_llm_calls': measured, 'token_usage_complete': complete,
                'failed_llm_calls': previous.get('failed_llm_calls', 0) + len(self.errors),
                'budget_charged_tokens': self.charged + sum(self.reservations.values()),
                'budget_limit_tokens': settings.RUN_TOTAL_TOKEN_BUDGET,
                'input_tokens': input_measured if complete else None,
                'output_tokens': output_measured if complete else None,
                'measured_input_tokens': input_measured, 'measured_output_tokens': output_measured,
                'active_duration_ms': previous.get('active_duration_ms', 0) + round((perf_counter() - self.started) * 1000),
                'scope': 'agent_graph_llm; excludes embedding, rerank, background extraction, image preprocessing and human approval wait'}


def metrics_from(config):
    for callback in (config or {}).get('callbacks') or []:
        if isinstance(callback, RunMetrics):
            return callback.snapshot()
    return None
