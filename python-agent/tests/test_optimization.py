"""Concurrency, failure recovery and bounded model inputs without external services."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'

import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError

from app.config import settings
from app.services.retrieval_service import RetrievalService
from app.services.query_rewrite import ResolvedFilters, QueryFilters
from app.graph.nodes import search_worker as search
from app.services.evidence_selection import EvidenceSelection
from app.services.memory import MemoryService
from app.services.conversation import summary_prompt
from app.services.durable_jobs import BackgroundWorker, DurableJobs, LeaseLost
from app.utils.context_budget import request_tokens, ContextBudgetExceeded
import test_retrieval_delivery as delivery
from fakes import article_chunk


class ParallelRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrency_is_shared_and_bounded_across_requests(self):
        service = RetrievalService.__new__(RetrievalService)
        service._slots = asyncio.Semaphore(2)
        active, peak, entered = 0, 0, asyncio.Event()
        async def retrieve(*a, **kw):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 2:
                entered.set()
            try:
                await asyncio.wait_for(entered.wait(), 1)
                await asyncio.sleep(.01)
                return [article_chunk()]
            finally:
                active -= 1
        service._vector_store = SimpleNamespace(search=retrieve)
        service._chunk_search = SimpleNamespace(search=retrieve)
        result = await asyncio.gather(*(service.hybrid_search(['a', 'b'], ['c', 'd'], ResolvedFilters()) for _ in range(2)))
        self.assertEqual(peak, 2)
        self.assertEqual(active, 0)
        self.assertEqual(result[0], result[1])

    async def test_source_failure_cancels_sibling_requests(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def slow(*a, **kw):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        async def fail(*a, **kw):
            await started.wait()
            raise ConnectionError('offline')
        service = RetrievalService.__new__(RetrievalService)
        service._vector_store = SimpleNamespace(search=slow)
        service._chunk_search = SimpleNamespace(search=fail)
        with self.assertRaises(ConnectionError):
            await service.hybrid_search(['a'], ['b'], ResolvedFilters())
        self.assertTrue(cancelled.is_set())

    async def test_web_starts_before_platform_finishes(self):
        state = delivery.RetrievalDeliveryTests().state()
        platform_started, web_started = asyncio.Event(), asyncio.Event()
        async def platform(**kw):
            platform_started.set()
            await asyncio.wait_for(web_started.wait(), 1)
            return []
        async def web(*a, **kw):
            web_started.set()
            await asyncio.wait_for(platform_started.wait(), 1)
            return [{'url': 'https://example.org/intro', 'title': 'intro', 'content': 'Spring Boot tutorial'}]
        rewrite = {'semantic_queries': ['Spring'], 'keywords': ['Spring'], 'web_query': 'Spring', 'filters': QueryFilters()}
        with patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', True), \
             patch.object(search.query_rewrite_service, 'rewrite', AsyncMock(return_value=rewrite)), \
             patch.object(search.filter_resolver_instance, 'resolve', AsyncMock(return_value=ResolvedFilters())), \
             patch.object(search.retrieval_service_instance, 'hybrid_search', platform), \
             patch.object(search, '_verify_candidates_from_mysql', AsyncMock(return_value=[])), \
             patch.object(search, 'do_search', web), \
             patch.object(search.evidence_selector, 'select', AsyncMock(return_value=EvidenceSelection(selected_ids=['web_0'], adequacy='partial', reason='one source'))):
            result = await search.retrieve_evidence(state)
        self.assertEqual(result['retrieval_report']['web']['status'], 'found')
        self.assertEqual(result['status'], 'succeeded')


class RetiredExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_extract_api_does_not_call_model_or_write_history(self):
        service = MemoryService.__new__(MemoryService)
        model = AsyncMock(side_effect=AssertionError('retired model called'))
        service._llm = SimpleNamespace(with_structured_output=lambda *a, **kw: SimpleNamespace(ainvoke=model))
        service._store_memory = AsyncMock(side_effect=AssertionError('event write'))
        await service.extract_and_store(7, 11, [{'role': 'user', 'content': ' long' * 10000}] * 12)
        model.assert_not_awaited(); service._store_memory.assert_not_awaited()

    async def test_legacy_enqueue_does_not_create_background_work(self):
        database = SimpleNamespace(execute=AsyncMock())
        self.assertIsNone(await DurableJobs(database).enqueue_extraction(7, 11, 42))
        database.execute.assert_not_awaited()

    async def test_pending_old_job_is_drained_without_history_or_llm(self):
        jobs = SimpleNamespace(claim=AsyncMock(return_value={'kind':'memory_extract','user_id':7,'conversation_id':11}),
                               complete=AsyncMock(), retry=AsyncMock(), db=SimpleNamespace(fetch_all=AsyncMock()))
        worker = BackgroundWorker(jobs)
        with patch('app.services.memory.memory_service.extract_and_store', AsyncMock()) as extract:
            await worker.run_once()
        extract.assert_not_awaited(); jobs.db.fetch_all.assert_not_awaited()
        jobs.complete.assert_awaited_once(); jobs.retry.assert_not_awaited()

    async def test_answer_settlement_does_not_schedule_extraction(self):
        from app.services.run_service import RunService
        conversations = SimpleNamespace(add_message=AsyncMock(return_value=42))
        jobs = SimpleNamespace(enqueue_extraction=AsyncMock())
        service = RunService(conversations, SimpleNamespace(), jobs=jobs)
        await service.finish(11, 7, SimpleNamespace(values={'final_reply':'解释完成'}, next=()))
        conversations.add_message.assert_awaited_once()
        jobs.enqueue_extraction.assert_not_awaited()

    def test_summary_target_scales_without_old_five_hundred_character_cap(self):
        with patch.object(settings, 'SUMMARY_MAX_TOKENS', 4096):
            long_prompt = summary_prompt('prior', ' history' * 20000)
            short_prompt = summary_prompt('', 'short')
        self.assertNotIn('500字', long_prompt)
        self.assertIn('4096 Token', long_prompt)
        self.assertIn('128 Token', short_prompt)
        self.assertIn('被撤销', long_prompt)


class DurableWorkerTests(unittest.IsolatedAsyncioTestCase):
    def worker(self):
        job = {'job_id': 'fixture', 'kind': 'memory_extract', 'attempts': 1, 'lease_token': 'token'}
        jobs = SimpleNamespace(claim=AsyncMock(return_value=job), complete=AsyncMock(), retry=AsyncMock())
        return BackgroundWorker(jobs), job

    async def test_success_completes_once(self):
        worker, job = self.worker()
        worker.handle = AsyncMock()
        self.assertTrue(await worker.run_once())
        worker.jobs.complete.assert_awaited_once_with(job)
        worker.jobs.retry.assert_not_awaited()

    async def test_failure_is_retried_without_completion(self):
        worker, job = self.worker()
        worker.handle = AsyncMock(side_effect=ConnectionError())
        await worker.run_once()
        worker.jobs.retry.assert_awaited_once()
        worker.jobs.complete.assert_not_awaited()

    async def test_shutdown_does_not_mark_unfinished_job_complete(self):
        worker, job = self.worker()
        worker.handle = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await worker.run_once()
        worker.jobs.complete.assert_not_awaited()
        worker.jobs.retry.assert_not_awaited()

    async def test_old_executor_cannot_pass_commit_fence(self):
        jobs = DurableJobs(SimpleNamespace(fetch_one=AsyncMock(return_value=None)))
        with self.assertRaises(LeaseLost):
            await jobs.assert_lease({'job_id': 'id', 'lease_token': 'stale'})
