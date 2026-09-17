"""
Token 计数工具
用于消息入库时计算 token、构建上下文时做预算控制

【为什么不用 len(text) / 4 估算？】
- 中文平均 1 字 ≈ 1~2 token，英文平均 1 词 ≈ 1.3 token
- 混合内容（中英 + 代码）误差可达 50%+
- tiktoken 用和 LLM 一致的 BPE 分词，偏差 <5%
"""
import tiktoken

# cl100k_base：GPT-4 / DeepSeek 系列通用编码
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
    return len(_encoder.encode(text))


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
    tokens = _encoder.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return _encoder.decode(tokens[:max_tokens])