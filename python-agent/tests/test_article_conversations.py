"""Source-scoped persistence, ownership, current visibility and bounded article data."""
import hashlib
import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app import migrate
from app.services.article_context import ArticleContextService, article_text
from app.services.conversation import ConversationService
from app.utils.token_utils import count_tokens


def row(**values):
    return SimpleNamespace(_mapping=values)


class ArticleConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_creation_preserves_null_for_general_and_allows_multiple_topics(self):
        execute = AsyncMock()
        service = ConversationService()
        with patch("app.services.conversation.db", SimpleNamespace(execute=execute)), \
             patch("app.services.conversation.snowflake.next_id", side_effect=[11, 12, 13]):
            self.assertEqual(await service.create_conversation(7), 11)
            self.assertEqual(await service.create_conversation(7, 42), 12)
            self.assertEqual(await service.create_conversation(7, 42), 13)
        self.assertEqual([c.args[1]["origin_article_id"] for c in execute.call_args_list], [None, 42, 42])
        self.assertEqual(execute.await_count, 3)

    async def test_source_is_derived_from_owned_conversation_and_cannot_be_rebound(self):
        database = SimpleNamespace(fetch_one=AsyncMock(return_value=row(user_id=7, origin_article_id=42)), execute=AsyncMock())
        service = ConversationService()
        with patch("app.services.conversation.db", database):
            self.assertEqual(await service.resolve_origin(11, 7), 42)
            self.assertEqual(await service.resolve_origin(11, 7, 42), 42)
            with self.assertRaises(HTTPException) as conflict:
                await service.resolve_origin(11, 7, 99)
            self.assertEqual(conflict.exception.status_code, 409)
            with self.assertRaises(HTTPException) as unauthorized:
                await service.resolve_origin(11, 8)
            self.assertEqual(unauthorized.exception.status_code, 404)
            database.fetch_one.return_value = row(user_id=7, origin_article_id=None)
            self.assertIsNone(await service.resolve_origin(11, 7))
            with self.assertRaises(HTTPException):
                await service.resolve_origin(11, 7, 42)
        database.execute.assert_not_awaited()

    async def test_lists_have_stable_cursor_scope_and_current_visible_title(self):
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[row(conversation_id=11, origin_article_id=42,
                                                                        origin_article_title="Current title")]))
        service = ConversationService()
        cursor = datetime(2026, 10, 2)
        with patch("app.services.conversation.db", database):
            result = await service.list_conversations(7, cursor, 11, 10, scope="article", origin_article_id=42)
            sql, values = database.fetch_all.call_args.args
            self.assertIn("c.origin_article_id = :origin", sql)
            self.assertIn("c.message_count > 0", sql)
            self.assertIn("a.status = 1 AND a.deleted = 0", sql)
            self.assertIn("c.update_time = :t AND c.conversation_id < :lid", sql)
            self.assertIn("ORDER BY c.update_time DESC, c.conversation_id DESC", sql)
            self.assertEqual(values["origin"], 42)
            self.assertEqual(result[0]["originArticleId"], 42)
            self.assertEqual(result[0]["originArticleTitle"], "Current title")
            await service.list_conversations(7, scope="general")
            self.assertIn("c.origin_article_id IS NULL", database.fetch_all.call_args.args[0])
            await service.list_conversations(7)
            self.assertNotIn("c.origin_article_id IS NULL", database.fetch_all.call_args.args[0])

    async def test_read_only_latest_and_metadata_never_create_empty_conversations(self):
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[]), fetch_one=AsyncMock(return_value=None), execute=AsyncMock())
        service = ConversationService()
        with patch("app.services.conversation.db", database):
            self.assertIsNone(await service.latest_article_conversation(7, 42))
            self.assertEqual(database.fetch_all.call_args.args[1]["lim"], 1)
            with self.assertRaises(HTTPException) as inaccessible:
                await service.get_conversation(11, 8)
            self.assertEqual(inaccessible.exception.status_code, 404)
            sql, values = database.fetch_one.call_args.args
            self.assertIn("c.user_id = :uid", sql)
            self.assertEqual(values, {"cid": 11, "uid": 8})
        database.execute.assert_not_awaited()

    async def test_invalid_source_or_incomplete_cursor_is_rejected_before_query(self):
        database = SimpleNamespace(execute=AsyncMock(), fetch_all=AsyncMock())
        service = ConversationService()
        with patch("app.services.conversation.db", database):
            for origin in (0, -1, True):
                with self.assertRaises(HTTPException):
                    await service.create_conversation(7, origin)
            for kwargs in ({"scope": "unknown"}, {"scope": "general", "origin_article_id": 42},
                           {"last_id": 11}, {"last_update_time": datetime.now()}, {"origin_article_id": 0}):
                with self.assertRaises(HTTPException):
                    await service.list_conversations(7, **kwargs)
        database.execute.assert_not_awaited()
        database.fetch_all.assert_not_awaited()


class ArticleContextTests(unittest.IsolatedAsyncioTestCase):
    def service(self, content="<h2>Condition</h2><p>Visible current content</p>", **overrides):
        values = {"article_id": 42, "title": "Spring Boot", "content": content, "content_type": 1,
                  "update_time": datetime(2026, 10, 2), "cover_image": None,
                  "author_name": "Writer", "view_count": 3, "like_count": 2}
        values.update(overrides)
        database = SimpleNamespace(fetch_one=AsyncMock(return_value=row(**values)))
        return ArticleContextService(database), database

    async def test_live_public_source_and_raw_hash_are_shared_by_context_and_citation(self):
        raw = "<p>Visible &amp; current</p>"
        service, database = self.service(raw)
        context = await service.load(42)
        self.assertIn("a.status = 1 AND a.deleted = 0", database.fetch_one.call_args.args[0])
        self.assertEqual(context["content"], "Visible & current")
        self.assertEqual(context["completeness"], "full")
        self.assertEqual(context["source_hash"], hashlib.sha256(raw.encode()).hexdigest())
        evidence = service.evidence(context)
        self.assertEqual(evidence["citations"][0]["sourceHash"], context["source_hash"])
        self.assertEqual(evidence["citations"][0]["id"], "article_context:1")
        self.assertEqual(evidence["article_cards"][0]["articleId"], "42")
        # Another round must fetch current data rather than keep the old text.
        database.fetch_one.return_value = row(article_id=42, title="Updated title", content="<p>New</p>")
        changed = await service.load(42)
        self.assertEqual(changed["content"], "New")
        self.assertNotEqual(changed["source_hash"], context["source_hash"])

    async def test_missing_hidden_or_deleted_source_is_rejected_before_agent_input(self):
        service, database = self.service()
        database.fetch_one.return_value = None
        with self.assertRaises(HTTPException) as missing:
            await service.load(42)
        self.assertEqual(missing.exception.status_code, 404)

    async def test_image_only_article_explicitly_reports_no_readable_body(self):
        service, _ = self.service('<p><img src="picture.png"></p>')
        context = await service.load(42)
        self.assertEqual(context["content"], "")
        self.assertIn("没有可读取的文字正文", service.evidence(context)["result"])

    async def test_long_article_is_bounded_and_explicitly_partial(self):
        service, _ = self.service("<p>" + "中文解释 条件装配 example " * 1000 + "</p>")
        context = await service.load(42, max_tokens=100)
        self.assertLessEqual(count_tokens(context["content"]), 100)
        self.assertNotIn("\ufffd", context["content"])
        self.assertEqual(context["completeness"], "excerpt")
        self.assertGreater(context["full_content_tokens"], context["content_tokens"])
        self.assertIn("未读部分需要按 article_ids 检索", service.evidence(context)["result"])

    def test_html_skips_hidden_scripts_and_keeps_code_indentation(self):
        html = """<style>secret css</style><script>do not run</script><template>hidden template</template>
            <p>Visible <strong>paragraph</strong></p><div hidden>private</div>
            <span aria-hidden="true">hidden aria</span><p style="display: none">hidden css</p>
            <pre><code>if (enabled) {\n    bean();\n}</code></pre><p>Last</p>"""
        text = article_text(html)
        self.assertIn("Visible paragraph", text)
        self.assertIn("if (enabled) {\n    bean();\n}", text)
        self.assertTrue(text.endswith("Last"))
        for hidden in ("secret css", "do not run", "hidden template", "private", "hidden aria", "hidden css"):
            self.assertNotIn(hidden, text)

    def test_markdown_code_angle_brackets_are_not_discarded_as_html(self):
        text = article_text("# Test\n\n```java\nList<String> value;\n    next();\n```", 2)
        self.assertIn("List<String> value;\n    next();", text)


class ArticleConversationMigrationTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, origin=None, index=None):
        columns = {"conversation_id": {"name": "conversation_id", "type": "bigint", "nullable": "NO"}}
        if origin is not None:
            columns["origin_article_id"] = {"name": "origin_article_id", "type": origin[0], "nullable": origin[1]}
        indexes = index or []
        receipt = {}
        async def fetch_all(sql):
            return [row(**i) for i in indexes] if "STATISTICS" in sql else [row(**c) for c in columns.values()]
        async def execute(sql, params=None):
            if sql.startswith("ALTER TABLE"):
                columns["origin_article_id"] = {"name": "origin_article_id", "type": "bigint", "nullable": "YES"}
            if sql.startswith("CREATE INDEX"):
                indexes.extend({"column_name": name, "position": i + 1, "non_unique": 1}
                               for i, name in enumerate(("user_id", "origin_article_id", "status", "update_time", "conversation_id")))
            if sql.startswith("INSERT IGNORE"):
                receipt.update(params)
        connection = SimpleNamespace(fetch_val=AsyncMock(return_value=1), fetch_all=AsyncMock(side_effect=fetch_all),
            fetch_one=AsyncMock(side_effect=lambda *a: row(checksum=receipt["checksum"]) if receipt else None),
            execute=AsyncMock(side_effect=execute))
        @asynccontextmanager
        async def connect():
            yield connection
        return SimpleNamespace(connection=connect), connection, receipt

    async def test_additive_migration_replays_and_has_no_per_article_unique_constraint(self):
        database, connection, _ = self.fixture()
        await migrate.apply_article_conversation_migration(database)
        await migrate.apply_article_conversation_migration(database)
        alters = [c for c in connection.execute.call_args_list if c.args[0].startswith("ALTER")]
        indexes = [c for c in connection.execute.call_args_list if c.args[0].startswith("CREATE INDEX")]
        self.assertEqual(len(alters), 1)
        self.assertEqual(len(indexes), 1)
        self.assertIn("BIGINT NULL DEFAULT NULL", alters[0].args[0])
        self.assertNotIn("UNIQUE", indexes[0].args[0])

    async def test_partial_upgrade_adds_only_missing_index(self):
        database, connection, _ = self.fixture(origin=("bigint", "YES"))
        await migrate.apply_article_conversation_migration(database)
        self.assertFalse(any(c.args[0].startswith("ALTER") for c in connection.execute.call_args_list))
        self.assertTrue(any(c.args[0].startswith("CREATE INDEX") for c in connection.execute.call_args_list))

    async def test_checksum_and_incompatible_column_are_rejected_without_writes(self):
        database, connection, receipt = self.fixture()
        receipt["checksum"] = "tampered"
        with self.assertRaisesRegex(RuntimeError, "校验和"):
            await migrate.apply_article_conversation_migration(database)
        connection.execute.assert_not_awaited()
        self.assertIn("RELEASE_LOCK", connection.fetch_val.call_args.args[0])
        for origin in (("varchar", "YES"), ("bigint", "NO")):
            database, connection, _ = self.fixture(origin=origin)
            with self.assertRaisesRegex(RuntimeError, "不兼容"):
                await migrate.apply_article_conversation_migration(database)
            connection.execute.assert_not_awaited()

    async def test_startup_check_requires_expected_nonunique_index(self):
        database = SimpleNamespace(fetch_all=AsyncMock(side_effect=[
            [row(name="origin_article_id", type="bigint", nullable="YES")],
            [row(column_name="origin_article_id", position=1, non_unique=0)]]), execute=AsyncMock())
        with self.assertRaisesRegex(RuntimeError, "索引未就绪"):
            await migrate.check_article_conversation_schema(database)
        database.execute.assert_not_awaited()

    async def test_incompatible_existing_index_is_not_overwritten_or_recorded(self):
        database, connection, _ = self.fixture(index=[{"column_name": "origin_article_id", "position": 1, "non_unique": 0}])
        with self.assertRaisesRegex(RuntimeError, "索引不兼容"):
            await migrate.apply_article_conversation_migration(database)
        connection.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
