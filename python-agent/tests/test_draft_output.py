"""Draft metadata limits and bounded correction without rewriting the article."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError
from langchain_core.exceptions import OutputParserException

from app.models.draft import DraftOutput
from app.graph.nodes import writing_worker


def invalid_summary():
    try:
        DraftOutput(title="标题", summary="摘" * 501, content="正文")
    except ValidationError as exc:
        return exc
    raise AssertionError("Expected validation error")


class DraftOutputTests(unittest.IsolatedAsyncioTestCase):
    def test_summary_allows_500_characters_including_emoji_but_not_501(self):
        for char in ("摘", "🙂"):
            self.assertEqual(len(DraftOutput(title="标题", summary=char * 500, content="正文").summary), 500)
            with self.assertRaises(ValidationError):
                DraftOutput(title="标题", summary=char * 501, content="正文")

    async def generate(self, responses, markdown="# 原标题\n\n原正文。\n\n```java\nint n = 1;\n```\n引用 [a:1]"):
        model = SimpleNamespace(ainvoke=AsyncMock(side_effect=responses))
        llm = SimpleNamespace(with_structured_output=lambda *a, **kw: model)
        with patch.object(writing_worker, "run_tool_agent", AsyncMock(return_value=markdown)) as writer, \
             patch.object(writing_worker, "get_llm", return_value=llm):
            result = await writing_worker.generate_draft("任务", "系统提示")
        return result, writer, model, markdown

    async def test_long_valid_summary_is_kept_and_original_markdown_preserved(self):
        parsed = DraftOutput(title="标题", summary="摘要" * 200, content="模型改写了正文")
        draft, writer, model, markdown = await self.generate([parsed])
        self.assertEqual(draft.summary, parsed.summary)
        self.assertEqual(draft.content, markdown)
        writer.assert_awaited_once()
        model.ainvoke.assert_awaited_once()

    async def test_oversized_summary_gets_one_metadata_correction_without_rewriting(self):
        valid = DraftOutput(title="标题", summary="摘要" * 100, content="正文副本")
        draft, writer, model, markdown = await self.generate([invalid_summary(), valid])
        self.assertEqual(draft.summary, valid.summary)
        self.assertEqual(draft.content, markdown)
        self.assertEqual(model.ainvoke.await_count, 2)
        writer.assert_awaited_once()

    async def test_repeated_format_errors_fall_back_without_losing_code_or_citations(self):
        draft, writer, model, markdown = await self.generate([invalid_summary(), OutputParserException("invalid JSON")])
        self.assertEqual(draft.title, "原标题")
        self.assertEqual(draft.content, markdown)
        self.assertIn("原正文", draft.summary)
        self.assertLessEqual(len(draft.summary), 300)
        self.assertNotIn("int n", draft.summary)
        self.assertEqual(model.ainvoke.await_count, 2)
        writer.assert_awaited_once()

    async def test_fallback_summary_respects_target_and_sentence_boundary(self):
        markdown = "# 标题\n" + "这是一段说明。" * 100
        draft, _, _, _ = await self.generate([invalid_summary(), invalid_summary()], markdown)
        self.assertLessEqual(len(draft.summary), 300)
        self.assertTrue(draft.summary.endswith("。"))
        self.assertEqual(draft.content, markdown)

    async def test_empty_summary_uses_article_excerpt(self):
        draft, _, model, _ = await self.generate([DraftOutput(title="标题", summary="", content="副本")])
        self.assertTrue(draft.summary)
        model.ainvoke.assert_awaited_once()

    async def test_provider_failure_is_not_misclassified_as_format_error(self):
        model = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("provider unavailable")))
        llm = SimpleNamespace(with_structured_output=lambda *a, **kw: model)
        with patch.object(writing_worker, "run_tool_agent", AsyncMock(return_value="# 标题\n正文")), \
             patch.object(writing_worker, "get_llm", return_value=llm), self.assertRaises(RuntimeError):
            await writing_worker.generate_draft("任务", "系统提示")
        model.ainvoke.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
