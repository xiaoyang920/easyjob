"""
统一日志配置 + 请求上下文 trace_id

使用方式：
1. 在 main.py 最早的地方调用 setup_logging()
2. 在 FastAPI endpoint 里用 `with request_trace(conversation_id):` 包裹
3. 需要打日志的地方 `log = get_logger(__name__)`，日志格式会自动带上 trace
"""
import contextvars
import logging
import sys
import uuid
import re
from typing import Optional

# 请求级别的 trace id 上下文
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")
_conversation_id: contextvars.ContextVar[str] = contextvars.ContextVar("conv_id", default="-")
_run_id: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")


def normalize_trace(value):
    return value if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_-]{8,64}', value) else uuid.uuid4().hex


def set_request_trace(conversation_id: Optional[int | str] = None, trace_id: Optional[str] = None) -> str:
    """
    为当前 asyncio Task 设置 trace 上下文。返回生成的 trace_id。
    配合 FastAPI 在每个请求开头调用一次即可，同一 Task 内所有 await 都能读到。
    """
    tid = normalize_trace(trace_id or _trace_id.get())
    _trace_id.set(tid)
    _conversation_id.set(str(conversation_id) if conversation_id is not None else "-")
    return tid


class TraceFilter(logging.Filter):
    """把 trace_id 和 conversation_id 注入每条日志"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _trace_id.get()
        record.conv_id = _conversation_id.get()
        record.run_id = _run_id.get()
        return True


class _ColorFormatter(logging.Formatter):
    """控制台彩色日志（终端不支持时自动降级）"""
    COLORS = {
        "DEBUG": "\033[36m",    # 青
        "INFO": "\033[32m",     # 绿
        "WARNING": "\033[33m",  # 黄
        "ERROR": "\033[31m",    # 红
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        formatted = super().format(record)
        if color and sys.stdout.isatty():
            return f"{color}{formatted}{self.RESET}"
        return formatted


def setup_logging(level: str = "INFO") -> None:
    """
    初始化日志：
    - 统一格式：时间 | 级别 | [trace=xxx conv=yyy] | logger名 | 消息
    - 第三方库降级到 WARNING，减少噪音
    """
    fmt = "%(asctime)s | %(levelname)-5s | [trace=%(trace_id)s conv=%(conv_id)s run=%(run_id)s] | %(name)s | %(message)s"
    datefmt = "%H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ColorFormatter(fmt, datefmt=datefmt))
    handler.addFilter(TraceFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # 抑制过度输出的第三方日志
    for noisy in ("httpx", "httpcore", "openai._base_client", "openai._streaming",
                  "langchain_core.tracers.base", "elastic_transport.transport"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """业务代码统一用它拿 logger"""
    return logging.getLogger(name)


class request_trace:
    """
    用法:
        async with request_trace(conversation_id="123"):
            ...
    """

    def __init__(self, conversation_id: Optional[int | str] = None, trace_id: Optional[str] = None, run_id=None):
        self.trace_id = normalize_trace(trace_id or _trace_id.get())
        self.conv_id = str(conversation_id) if conversation_id is not None else "-"
        self.run_id = str(run_id) if run_id and re.fullmatch(r'[a-zA-Z0-9_-]{8,64}', str(run_id)) else '-'
        self._tokens: list = []

    def __enter__(self):
        self._tokens.append(_trace_id.set(self.trace_id))
        self._tokens.append(_conversation_id.set(self.conv_id))
        self._tokens.append(_run_id.set(self.run_id))
        return self

    def __exit__(self, exc_type, exc, tb):
        for tok in reversed(self._tokens):
            try:
                tok.var.reset(tok)
            except Exception:
                pass

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb):
        return self.__exit__(exc_type, exc, tb)


def current_trace_id() -> str:
    return _trace_id.get()


def set_run_trace(run_id):
    _run_id.set(str(run_id) if run_id and re.fullmatch(r'[a-zA-Z0-9_-]{8,64}', str(run_id)) else '-')


def truncate(s, max_len: int = 300) -> str:
    """日志打印用的字符串截断，避免一行几万字"""
    if s is None:
        return ""
    s = str(s).replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"... [+{len(s) - max_len} chars]"
