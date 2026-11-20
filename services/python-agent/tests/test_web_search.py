import asyncio
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.tools import web_search as search
from app.services.dependency_policy import DependencyPolicy
from app.utils.token_utils import count_tokens


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = SimpleNamespace(post=AsyncMock())
        for name, value in [('_client', self.client),
                ('_search_rate', SimpleNamespace(acquire=AsyncMock())),
                ('_fetch_rate', SimpleNamespace(acquire=AsyncMock())),
                ('web_policy', DependencyPolicy('test-search', attempts=1)),
                ('fetch_policy', DependencyPolicy('test-fetch', attempts=1))]:
            p = patch.object(search, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in [('DEEPSEEK_API_KEY', 'test-key'), ('DEEPSEEK_TOOLS_BASE_URL', 'https://api.deepseek.com/v1/')]:
            p = patch.object(search.settings, name, value)
            p.start()
            self.addCleanup(p.stop)

    def response(self, items):
        return httpx.Response(200, json={'results': items})

    def item(self, **updates):
        return {'title': 'Docs', 'url': 'https://spring.io/guides/', 'content': 'Spring docs', **updates}

    async def test_official_request_and_body_instead_of_summary(self):
        self.client.post.return_value = self.response([self.item(summary='short summary')])
        result = await search.do_search('Spring Boot', size=3)
        call = self.client.post.await_args
        self.assertEqual(call.args, ('https://api.deepseek.com/v1/tools/search',))
        self.assertEqual(call.kwargs['json'], {'query': 'Spring Boot', 'count': 3, 'need_content': True})
        self.assertEqual(call.kwargs['headers']['Authorization'], 'Bearer test-key')
        self.assertEqual(result[0]['content'], 'Spring docs')
        self.assertEqual(result[0]['contentScope'], 'page_content')
        self.assertEqual(result[0]['provider'], 'deepseek')
        self.assertEqual(self.client.post.await_count, 1)

    async def test_bounded_count_and_empty_success(self):
        self.client.post.return_value = self.response([])
        for size, expected in [(0, 1), (100, 50)]:
            self.assertEqual(await search.do_search('q', size=size), [])
            self.assertEqual(self.client.post.await_args.kwargs['json']['count'], expected)

    async def test_invalid_query_never_calls_provider_and_preserves_filters(self):
        for query in ['', ' ', 'q' * 129, 'x' * 128 + ' site:spring.io', None]:
            with self.subTest(query=query), self.assertRaisesRegex(search.WebSearchError, '128'):
                await search.do_search(query)
        self.client.post.assert_not_awaited()
        self.client.post.return_value = self.response([])
        query = '中' * 128
        await search.do_search(query)
        self.assertEqual(self.client.post.await_args.kwargs['json']['query'], query)

    async def test_fetch_missing_body_and_preserve_order(self):
        self.client.post.side_effect = [self.response([self.item(content='', summary='summary'),
            self.item(url='https://spring.io/other', content='existing body')]),
            httpx.Response(200, json={'title': 'Fetched title', 'content': '# Retrieved body'})]
        result = await search.do_search('q')
        self.assertEqual(result[0]['content'], '# Retrieved body')
        self.assertEqual(result[0]['title'], 'Docs')
        self.assertEqual(result[0]['fetchStatus'], 'succeeded')
        self.assertEqual(result[1]['content'], 'existing body')
        fetch = self.client.post.await_args
        self.assertTrue(fetch.args[0].endswith('/tools/fetch'))
        self.assertEqual(fetch.kwargs['json'], {'url': 'https://spring.io/guides/'})

    async def test_fetch_limit_is_two_and_failure_retains_summary(self):
        self.client.post.side_effect = [self.response([self.item(url=f'https://spring.io/{i}', content='', summary=f'summary{i}') for i in range(5)]),
                                        httpx.Response(403, text='private'), httpx.Response(404)]
        result = await search.do_search('q')
        self.assertEqual(self.client.post.await_count, 3)
        self.assertEqual(len(result), 5)
        self.assertEqual([r['fetchStatus'] for r in result], ['unavailable', 'unavailable', 'not_attempted', 'not_attempted', 'not_attempted'])
        self.assertTrue(all(r['contentScope'] == 'search_excerpt' for r in result))
        self.assertEqual(result[0]['content'], 'summary0')

    async def test_fetch_bad_json_empty_content_and_timeout_retain_snippet(self):
        for response in [httpx.Response(200, text='bad json'), httpx.Response(200, json={}),
                         httpx.Response(200, json={'title': '', 'content': ''}), httpx.ReadTimeout('private')]:
            self.client.post.side_effect = [self.response([self.item(content='', snippet='snippet')]), response]
            result = await search.do_search('q')
            self.assertEqual(result[0]['content'], 'snippet')
            self.assertEqual(result[0]['fetchStatus'], 'unavailable')

    async def test_unavailable_body_without_summary_is_no_evidence(self):
        self.client.post.side_effect = [self.response([self.item(content='')]), httpx.Response(404)]
        self.assertEqual(await search.do_search('q'), [])

    async def test_invalid_and_duplicate_urls_are_not_fetched(self):
        invalid = ['file:///etc/passwd', 'http://localhost/a', 'http://127.0.0.1/a', 'http://[::1]/',
                   'http://169.254.169.254/', 'https://user:pw@spring.io/', 'http://[broken', 'https://spring.io/a\nb']
        self.client.post.return_value = self.response([self.item(url=url) for url in invalid] +
                                                     [self.item(), self.item(url='https://spring.io/guides/#part')])
        result = await search.do_search('q', size=50)
        self.assertEqual(len(result), 1)
        self.assertEqual(self.client.post.await_count, 1)
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(search.WebSearchError):
                await search.do_fetch(url)

    async def test_source_size_and_scope_are_honest(self):
        content = '完整中文正文。' * 10000
        self.client.post.return_value = self.response([self.item(content=content)])
        result = (await search.do_search('q'))[0]
        self.assertEqual(result['contentScope'], 'page_excerpt')
        self.assertTrue(result['contentTruncated'])
        self.assertLessEqual(count_tokens(result['content']), 4000)
        self.assertLessEqual(len(result['content']), 16000)
        self.assertNotIn('\ufffd', result['content'])

    async def test_http_errors_are_explicit_without_body_or_key(self):
        for code, expected in [(400, '参数'), (401, 'Key'), (402, '余额'), (403, '拒绝'), (408, '超时'), (429, '频繁'), (500, '不可用')]:
            self.client.post.return_value = httpx.Response(code, text='sensitive provider body test-key')
            with self.subTest(code=code), self.assertRaisesRegex(search.WebSearchError, expected) as caught:
                await search.do_search('q')
            self.assertNotIn('sensitive', str(caught.exception))
            self.assertNotIn('test-key', str(caught.exception))

    async def test_malformed_success_is_not_empty_evidence(self):
        for response in [httpx.Response(200, text='not JSON'), httpx.Response(200, json=[]),
                         httpx.Response(200, json={'code': 401}), httpx.Response(200, json={'results': {}}),
                         self.response([None]), self.response([self.item(content={'bad': 1})])]:
            self.client.post.return_value = response
            with self.assertRaisesRegex(search.WebSearchError, '格式'):
                await search.do_search('q')

    async def test_missing_key_makes_no_network_call(self):
        with patch.object(search.settings, 'DEEPSEEK_API_KEY', ''):
            with self.assertRaisesRegex(search.WebSearchError, '未配置'):
                await search.do_search('q')
        self.client.post.assert_not_awaited()

    async def test_network_timeout_sanitized(self):
        self.client.post.side_effect = httpx.ConnectTimeout('sensitive request')
        with self.assertRaisesRegex(search.WebSearchError, '超时') as caught:
            await search.do_search('q')
        self.assertNotIn('sensitive', str(caught.exception))

    async def test_transient_errors_retry_once_but_auth_does_not(self):
        with patch.object(search, 'web_policy', DependencyPolicy('test', attempts=2)):
            self.client.post.side_effect = [httpx.Response(429), self.response([])]
            self.assertEqual(await search.do_search('q'), [])
            self.assertEqual(self.client.post.await_count, 2)
            self.client.post.reset_mock(side_effect=True)
            self.client.post.return_value = httpx.Response(401)
            with self.assertRaises(search.WebSearchError):
                await search.do_search('q')
            self.assertEqual(self.client.post.await_count, 1)

    async def test_cancelled_fetch_is_not_swallowed_as_summary_fallback(self):
        self.client.post.side_effect = [self.response([self.item(content='', summary='summary')]), asyncio.CancelledError()]
        with self.assertRaises(asyncio.CancelledError):
            await search.do_search('q')

    async def test_rolling_rate_window_limits_concurrent_starts(self):
        limiter = search._RateLimit(limit=2, period=.03)
        start = search.monotonic()
        times = []
        async def acquire():
            await limiter.acquire()
            times.append(search.monotonic() - start)
        await asyncio.gather(*(acquire() for _ in range(5)))
        self.assertGreaterEqual(times[2], .025)
        self.assertGreaterEqual(times[4], .05)


if __name__ == '__main__':
    unittest.main()
