import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.services.dependency_policy import DependencyPolicy, DependencyHTTPError, DependencyUnavailable
from app.services.filter_resolver import FilterResolver, FilterResolutionError
from app.services.query_rewrite import QueryFilters, ResolvedFilters
from app.services.retrieval_service import RetrievalService
from app.graph.main_agent import RetrievalRequest
from app.graph.staged_plan import ExecutionTask


class DependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_rejection_never_retries(self):
        operation = AsyncMock(side_effect=DependencyHTTPError(401))
        policy = DependencyPolicy('test')
        with self.assertRaises(DependencyHTTPError): await policy.run(operation)
        self.assertEqual(operation.await_count, 1)
        self.assertIsNone(policy.opened_at)

    async def test_transient_error_retries_once(self):
        operation = AsyncMock(side_effect=[DependencyHTTPError(503), 'ok'])
        self.assertEqual(await DependencyPolicy('test').run(operation), 'ok')
        self.assertEqual(operation.await_count, 2)

    async def test_circuit_blocks_then_allows_only_one_recovery_probe(self):
        clock = [0]
        policy = DependencyPolicy('test', attempts=1, threshold=2, clock=lambda: clock[0])
        failing = AsyncMock(side_effect=TimeoutError())
        for _ in range(2):
            with self.assertRaises(TimeoutError): await policy.run(failing)
        with self.assertRaises(DependencyUnavailable): await policy.run(failing)
        self.assertEqual(failing.await_count, 2)
        clock[0] = 31
        waiting = asyncio.Event()
        async def recover(): await waiting.wait(); return 'ok'
        task = asyncio.create_task(policy.run(recover))
        await asyncio.sleep(0)
        with self.assertRaises(DependencyUnavailable): await policy.run(recover)
        waiting.set()
        self.assertEqual(await task, 'ok')
        self.assertEqual(await policy.run(AsyncMock(return_value='next')), 'next')

    async def test_total_timeout_includes_waiting_for_concurrency_slot(self):
        policy = DependencyPolicy('test', timeout=.02, concurrency=1, attempts=1)
        await policy.slots.acquire()
        operation = AsyncMock()
        with self.assertRaises(TimeoutError): await policy.run(operation)
        operation.assert_not_awaited()
        policy.slots.release()


class StrictFiltersTests(unittest.IsolatedAsyncioTestCase):
    async def test_ambiguous_author_and_unknown_category_do_not_become_keywords(self):
        service = FilterResolver()
        for filters, rows in [(QueryFilters(author_name='重名'), [{'user_id': 1}, {'user_id': 2}]),
                              (QueryFilters(category_names=['不存在']), [])]:
            service.reader = AsyncMock(return_value=rows)
            with self.assertRaises(FilterResolutionError): await service.resolve(filters)

    async def test_topic_word_is_soft_but_an_explicit_tag_is_required(self):
        service = FilterResolver()
        service.reader = AsyncMock(return_value=[])
        self.assertEqual((await service.resolve(QueryFilters(tags=['Redis']))).soft_terms, ['Redis'])
        with self.assertRaises(FilterResolutionError): await service.resolve(QueryFilters(required_tags=['Redis']))

    def test_current_database_metadata_must_satisfy_filters(self):
        filters = ResolvedFilters(author_ids=[7], category_ids=[2], time_range='week')
        meta = {'user_id': 7, 'category_id': 2, 'publish_time': datetime.now() - timedelta(days=1)}
        self.assertTrue(RetrievalService.matches_filters(meta, filters))
        for changed in [{'user_id': 8}, {'category_id': 3}, {'publish_time': datetime.now() - timedelta(days=30)}]:
            self.assertFalse(RetrievalService.matches_filters({**meta, **changed}, filters))

    def test_memory_cannot_accept_article_filters(self):
        with self.assertRaises(ValueError): RetrievalRequest(target='memory', instruction='recall', filters={})
        with self.assertRaises(ValueError): ExecutionTask(task_id='m',kind='search',actor='main',retrieval_target='memory',instruction='recall',filters={})
