import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'

import unittest
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError
from app.services.query_rewrite import QueryRewriteService, RewriteResult


class WebQueryContractTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        return QueryRewriteService.__new__(QueryRewriteService)

    async def test_short_resolved_query_keeps_site_and_exclusion_conditions(self):
        service = self.service()
        query = 'Redis cache site:redis.io -site:example.org after:2026'
        with patch.object(service, 'rewrite', AsyncMock()) as rewrite:
            result = await service.rewrite_request({'search_query': query, 'filters': {},
                'instruction': 'find', 'allow_web': True}, 'find', [])
        rewrite.assert_not_awaited()
        self.assertEqual(result['web_query'], query)

    async def test_overlong_web_query_is_rewritten_with_its_original_conditions(self):
        service = self.service()
        query = 'Redis ' * 20 + 'site:redis.io -site:example.org'
        with patch.object(service, 'rewrite', AsyncMock(return_value={'web_query': 'Redis site:redis.io -site:example.org'})) as rewrite:
            result = await service.rewrite_request({'search_query': query, 'filters': {},
                'instruction': 'find', 'allow_web': True}, 'find', [])
        self.assertIn(query, rewrite.await_args.args[0])
        self.assertEqual(result['web_query'], 'Redis site:redis.io -site:example.org')

    async def test_platform_query_limit_is_not_reduced(self):
        service = self.service()
        query = 'q' * 180
        with patch.object(service, 'rewrite', AsyncMock()) as rewrite:
            result = await service.rewrite_request({'search_query': query, 'filters': {},
                'instruction': 'find', 'allow_web': False}, 'find', [])
        rewrite.assert_not_awaited()
        self.assertEqual(result['semantic_queries'], [query])

    def test_structured_web_query_rejects_excess_length(self):
        with self.assertRaises(ValidationError):
            RewriteResult(semantic_queries=['q'], keywords=['q'], web_query='中' * 129)
