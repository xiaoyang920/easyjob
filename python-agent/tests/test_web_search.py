import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.tools import web_search as search


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, response, *, key="test-key", size=3):
        client = SimpleNamespace(post=AsyncMock(return_value=response))
        with patch.object(search, "_client", client), patch.object(search.settings, "BOCHA_API_KEY", key):
            result = await search.do_search("Spring Boot", size=size)
        return result, client.post.await_args

    async def test_official_count_parameter_and_snippet_fallback(self):
        response = httpx.Response(200, json={"code": 200, "data": {"webPages": {"value": [
            {"name": "Docs", "url": "https://spring.io/", "summary": None, "snippet": "Spring docs"}]}}})
        results, request = await self.call(response)
        self.assertEqual(request.kwargs["json"]["count"], 3)
        self.assertNotIn("size", request.kwargs["json"])
        self.assertEqual(request.args[0], search.settings.BOCHA_BASE_URL)
        self.assertEqual(results[0]["content"], "Spring docs")

    async def test_request_count_is_bounded(self):
        response = httpx.Response(200, json={"code": 200, "data": {"webPages": {"value": []}}})
        for size, expected in [(0, 1), (100, 50)]:
            _, request = await self.call(response, size=size)
            self.assertEqual(request.kwargs["json"]["count"], expected)

    async def test_http_auth_and_balance_errors_are_explicit_and_do_not_leak_body(self):
        for code, expected in [(401, "Key"), (403, "余额"), (429, "频繁")]:
            with self.subTest(code=code), self.assertRaises(search.WebSearchError) as caught:
                await self.call(httpx.Response(code, text="sensitive provider body"))
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn("sensitive", str(caught.exception))

    async def test_failed_application_code_is_not_an_empty_success(self):
        with self.assertRaisesRegex(search.WebSearchError, "Key"):
            await self.call(httpx.Response(200, json={"code": 401, "msg": "sensitive provider body"}))

    async def test_invalid_response_is_an_error(self):
        for response in [httpx.Response(200, text="not JSON"), httpx.Response(200, json={"code": 200, "data": "bad"})]:
            with self.assertRaisesRegex(search.WebSearchError, "格式"):
                await self.call(response)

    async def test_missing_key_does_not_make_network_request(self):
        client = SimpleNamespace(post=AsyncMock())
        with patch.object(search, "_client", client), patch.object(search.settings, "BOCHA_API_KEY", ""):
            with self.assertRaisesRegex(search.WebSearchError, "未配置"):
                await search.do_search("query")
        client.post.assert_not_awaited()

    async def test_timeout_is_reported_without_request_details(self):
        client = SimpleNamespace(post=AsyncMock(side_effect=httpx.ConnectTimeout("sensitive request")))
        with patch.object(search, "_client", client), patch.object(search.settings, "BOCHA_API_KEY", "test-key"):
            with self.assertRaisesRegex(search.WebSearchError, "超时") as caught:
                await search.do_search("query")
        self.assertNotIn("sensitive", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
