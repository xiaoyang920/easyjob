from contextlib import aclosing
from time import monotonic
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.runnables.config import ensure_config, merge_configs
from app.services.tracing import traced


def _usage(span, response):
    usage = getattr(response, "usage_metadata", None) or {}
    for source, target in (("input_tokens", "easyjob.llm.input_tokens"),
                           ("output_tokens", "easyjob.llm.output_tokens")):
        value = usage.get(source)
        if isinstance(value, int):
            span.set_attribute(target, value)


class _FirstContent(AsyncCallbackHandler):
    run_inline = True

    def __init__(self, span):
        self.span, self.started, self.seen = span, monotonic(), False

    async def on_llm_new_token(self, token, **kwargs):
        if token and not self.seen:
            self.seen = True
            self.span.set_attribute("easyjob.llm.first_content_ms", (monotonic() - self.started) * 1000)


async def traced_ainvoke(model, messages, *, config=None, span_name="agent.model", **kwargs):
    with traced(span_name) as span:
        measured_config = merge_configs(ensure_config(config), {"callbacks": [_FirstContent(span)]})
        response = await model.ainvoke(messages, config=measured_config, **kwargs)
        _usage(span, response)
        return response


async def traced_astream(model, messages, *, config=None, span_name="agent.model.stream", **kwargs):
    with traced(span_name) as span:
        started = monotonic()
        first_content = False
        async with aclosing(model.astream(messages, config=config, **kwargs)) as chunks:
            async for chunk in chunks:
                # An empty protocol chunk is not the first visible content.
                if not first_content and getattr(chunk, "content", None):
                    span.set_attribute("easyjob.llm.first_content_ms", (monotonic() - started) * 1000)
                    first_content = True
                _usage(span, chunk)
                yield chunk
