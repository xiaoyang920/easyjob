"""
Token 计数工具
用于消息入库时计算 token、构建上下文时做预算控制

使用本地 BPE 估算；不同供应商的分词器与请求封装不同，
不能视为 DeepSeek 的精确计费数。调用方必须预留安全余量。
"""
import tiktoken

# cl100k_base 用于本地预算估算，不声称与当前 DeepSeek 分词器一致。
# 初始化一次，后续复用（线程安全）
_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """
    计算文本的 token 数

    >>> count_tokens("你好世界")     → 4
    >>> count_tokens("Hello World")  → 2
    >>> count_tokens("")             → 0
    """
    if not text:
        return 0
    return len(_encoder.encode(text, disallowed_special=()))


def count_messages_tokens(messages: list[dict]) -> int:
    """
    计算消息列表的总 token 数

    每条消息额外算 4 token 开销（role标记 + 分隔符），
    这是 OpenAI Chat API 的计费方式，DeepSeek 近似。
    """
    total = 0
    for msg in messages:
        total += 4  # role + 分隔符开销
        total += count_tokens(msg.get("content", ""))
    total += 2  # 尾部 assistant 起始标记
    return total


def truncate_to_token_budget(text: str, max_tokens: int) -> str:
    """
    将文本截断到不超过 max_tokens
    用于摘要超长时的兜底截断
    """
    if max_tokens < 0:
        raise ValueError('max_tokens 必须非负')
    tokens = _encoder.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return text
    # A token can contain only part of a UTF-8 character. Drop an incomplete
    # suffix rather than introducing replacement characters into the summary.
    result = _encoder.decode_bytes(tokens[:max_tokens]).decode('utf-8', errors='ignore')
    while count_tokens(result) > max_tokens:
        result = result[:-1]
    return result
