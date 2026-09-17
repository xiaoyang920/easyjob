import logging

log = logging.getLogger(__name__)
def get_langfuse_callback():
    """
        获取 LangFuse v3 的 LangChain Callback Handler

        自动读取环境变量: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST
        未安装或环境变量未配置时静默返回 None

        用于注入 LLM 调用链: llm.ainvoke(messages, config={"callbacks": [cb]})
        """
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except ImportError:
        log.warning("langfuse 未安装,llm调用追踪禁用")
        return None
    except Exception as e:
        log.warning("langfuse 初始化失败: %s", e)
        return None
def trace_node(node_name: str):
    """
    节点级别装饰器：给函数加上 LangFuse 追踪，追踪名使用 node_name。
    langfuse 未安装时静默返回原函数。
    """
    def decorator(func):
        try:
            from langfuse import observe
            # observe 的正确用法：作为装饰器工厂，name 必须用关键字参数
            return observe(name=node_name)(func)
        except ImportError:
            log.warning("langfuse 未安装,llm调用追踪禁用")
            return func
        except Exception as e:
            log.warning("langfuse observe 绑定失败,跳过追踪: %s", e)
            return func
    return decorator
class CostTracker:
    """
    Token/费用追踪器
    """
    # 主流模型定价 ($/1K tokens)，2026年价格
    PRICING = {
        "deepseek-chat": {"prompt": 0.00014, "completion": 0.00028},
        "glm-4.6v": {"prompt": 0.001, "completion": 0.001},
    }
    def __init__(self):
        self._records: list[dict] = []
    def add_usage(self,model:str,prompt_tokens:int,completion_tokens:int):
        pricing = self.PRICING.get(model,{"prompt": 0.001, "completion": 0.001})
        cost = (
                prompt_tokens / 1000 * pricing["prompt"]
                + completion_tokens / 1000 * pricing["completion"]
        )
        self._records.append({
            "model":model,
            "prompt_tokens":prompt_tokens,
            "completion_tokens":completion_tokens,
            "cost_usd":round(cost, 6),
        })
    def summary(self)->dict:
        total_prompt = sum(r["prompt_tokens"] for r in self._records)
        total_completion = sum(r["completion_tokens"] for r in self._records)
        total_cost = sum(r["cost_usd"] for r in self._records)
        return {
            "total_calls": len(self._records),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_cost_usd": round(total_cost, 6),
            "details": self._records,
        }