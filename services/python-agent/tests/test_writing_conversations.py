import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-test')
os.environ.setdefault('AGENT_SERVICE_KEY', 'offline-service-key-32-bytes-long!!')
import unittest
from types import SimpleNamespace
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from pydantic import ValidationError
from app.services.writing_conversations import WritingContext, bind_writing, writing_question_title
from app.services.conversation import ConversationService
from app.services.conversation_features import query
from app.rpc.generated import easyjob_rpc_pb2 as pb


def row(**values): return SimpleNamespace(_mapping=values)
@asynccontextmanager
async def transaction(): yield
def database(**values):
    return SimpleNamespace(transaction=transaction, fetch_one=AsyncMock(return_value=row(origin_article_id=None, is_writing=0, writing_article_id=None)),
        fetch_all=AsyncMock(return_value=[]), fetch_val=AsyncMock(return_value=0), execute=AsyncMock(), **values)


class WritingConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_binding_checks_both_owners_before_changing_metadata_and_rejects_public_or_other_sources(self):
        store = database()
        metadata = AsyncMock(return_value=[{'article_id': 42, 'title': '我的草稿'}])
        with patch('app.services.writing_conversations.writing_metadata', metadata):
            result = await bind_writing(11, 7, WritingContext(article_id=42), store)
            self.assertEqual(result, {'isWriting': True, 'writingArticleId': '42', 'writingArticleTitle': '我的草稿', 'writingArticleAvailable': True})
            metadata.assert_awaited_once_with(7, [42])
            self.assertEqual(store.execute.await_args.args[1], {'cid': 11, 'uid': 7, 'aid': 42})
            store.execute.reset_mock()
            for origin, existing in ((9, None), (None, 43), (None, 42)):
                store.fetch_one.return_value = row(origin_article_id=origin, is_writing=1, writing_article_id=existing)
                target = 43 if existing == 42 else 42
                metadata.return_value = [{'article_id': target, 'title': '我的草稿'}]
                with self.assertRaises(HTTPException) as error:
                    await bind_writing(11, 7, WritingContext(article_id=target), store)
                self.assertEqual(error.exception.status_code, 409)
            store.execute.assert_not_awaited()
            store.fetch_one.return_value = None
            metadata.reset_mock()
            with self.assertRaises(HTTPException): await bind_writing(11, 8, WritingContext(article_id=42), store)
            metadata.assert_not_awaited()

    async def test_unowned_or_deleted_draft_never_attaches_and_unsaved_draft_has_no_public_lookup(self):
        store = database()
        with patch('app.services.writing_conversations.writing_metadata', AsyncMock(return_value=[])) as metadata:
            with self.assertRaises(HTTPException) as error: await bind_writing(11, 7, WritingContext(article_id=42), store)
            self.assertEqual(error.exception.status_code, 404)
            store.execute.assert_not_awaited()
            metadata.reset_mock()
            result = await bind_writing(11, 7, WritingContext(), store)
            self.assertTrue(result['isWriting']); self.assertIsNone(result['writingArticleId'])
            metadata.assert_not_awaited()

    async def test_lists_exclude_writing_from_general_and_recover_only_the_exact_owned_draft(self):
        store = database()
        with patch('app.services.conversation.db', store):
            service = ConversationService()
            await service.list_conversations(7, scope='general')
            self.assertIn('c.is_writing = 0', store.fetch_all.await_args.args[0])
            await service.list_conversations(7, scope='writing', writing_article_id=9007199254740993)
            sql, values = store.fetch_all.await_args.args
            self.assertIn('c.user_id = :uid', sql); self.assertIn('c.is_writing = 1', sql)
            self.assertIn('c.writing_article_id = :writing', sql)
            self.assertEqual(values['writing'], 9007199254740993)
            for options in ({'scope': 'general', 'writing_article_id': 42}, {'scope': 'writing', 'origin_article_id': 42}):
                with self.assertRaises(HTTPException): await service.list_conversations(7, **options)
        await query(pb.AgentQuery(kind='conversation_library', state='writing', page=1, limit=20), 7, store)
        self.assertIn('c.is_writing=1', store.fetch_all.await_args.args[0])

    async def test_private_titles_are_enriched_under_the_actual_owner_and_missing_titles_do_not_expose_stale_data(self):
        records = [{'user_id': 7, 'origin_article_id': None, 'is_writing': 1, 'writing_article_id': 42},
                   {'user_id': 8, 'origin_article_id': None, 'is_writing': 1, 'writing_article_id': 42}]
        metadata = AsyncMock(side_effect=lambda uid, ids: [{'article_id': 42, 'title': '仅作者可见'}] if uid == 7 else [])
        with patch('app.rpc.blog_client.writing_metadata', metadata), patch('app.services.conversation.public_read', AsyncMock()) as public:
            await ConversationService._enrich_origins(records)
            public.assert_not_awaited()
        self.assertEqual(records[0]['writing_article_title'], '仅作者可见')
        self.assertIsNone(records[1]['writing_article_title'])
        self.assertFalse(records[1]['writing_article_available'])

    async def test_new_writing_record_stays_out_of_published_article_context(self):
        store = database()
        with patch('app.services.conversation.db', store):
            await ConversationService().create_conversation(7, is_writing=True, writing_article_id=42)
        self.assertIsNone(store.execute.await_args.args[1]['origin_article_id'])
        self.assertEqual(store.execute.await_args.args[1]['is_writing'], 1)
        self.assertEqual(store.execute.await_args.args[1]['writing_article_id'], 42)

    def test_identifier_and_title_contracts_do_not_leak_reference_payloads(self):
        self.assertEqual(WritingContext(article_id='9007199254740993').article_id, 9007199254740993)
        for value in (0, -1, True, 2**63):
            with self.assertRaises(ValidationError): WritingContext(article_id=value)
        text = '这是什么意思\n\n<easyjob-writing-reference>\n{"version":1,"kind":"selection","text":"正文","truncated":false}\n</easyjob-writing-reference>'
        self.assertEqual(writing_question_title(text), '这是什么意思')
        self.assertEqual(writing_question_title('普通聊天标题'), '普通聊天标题')
