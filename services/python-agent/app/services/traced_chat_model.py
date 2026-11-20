"""Trace provider calls without exporting prompts, completions or credentials."""
import asyncio
from contextlib import aclosing
from time import perf_counter

from langchain_openai import ChatOpenAI
from openai import APIStatusError
from opentelemetry.trace import use_span

from app.services.tracing import mark_error, traced, tracer


MODEL_BALANCE_MESSAGE = "模型服务余额不足，请恢复模型账号额度后重试。"


def is_model_balance_error(error):
    return isinstance(error, APIStatusError) and error.status_code == 402


class TracedChatOpenAI(ChatOpenAI):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        with traced("agent.model.generate", attributes={"gen_ai.request.model": self.model_name}):
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        with traced("agent.model.generate", attributes={"gen_ai.request.model": self.model_name}):
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(self, *args, **kwargs):
        started = perf_counter()
        first_content = True
        span = tracer().start_span("agent.model.stream", attributes={"gen_ai.request.model": self.model_name})
        try:
            async with aclosing(super()._astream(*args, **kwargs)) as source:
                while True:
                    try:
                        with use_span(span, record_exception=False, set_status_on_exception=False):
                            chunk = await anext(source)
                    except StopAsyncIteration:
                        break
                    if first_content and (chunk.text or getattr(chunk.message, "tool_call_chunks", None)):
                        span.add_event("agent.model.first_content", {"easyjob.elapsed_ms": (perf_counter() - started) * 1000})
                        first_content = False
                    yield chunk
        except (GeneratorExit, asyncio.CancelledError):
            span.set_attribute("easyjob.cancelled", True)
            raise
        except Exception as error:
            mark_error(span, error)
            raise
        finally:
            span.end()
