"""Regression checks for periodic extraction and explicit-change timing separation."""
import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-test')
os.environ.setdefault('AGENT_SERVICE_KEY', 'offline-service-key-32-bytes-long!!')

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app.services.memory import MemoryService
from app.services.memory_policy import constraint_view
from databases.backends.common.records import Record, Row
from sqlalchemy import create_engine, text


def history(turns, last='解释缓存击穿的处理思路'):
    rows = []
    for i in range(turns):
        rows.extend([{'role': 'user', 'content': last if i == turns - 1 else '解释缓存一致性的具体实现'},
                     {'role': 'assistant', 'content': '缓存一致性需要考虑数据库提交与缓存失效的先后顺序，以及并发访问造成的时间窗口。'}])
    return rows


class MemoryTriggerTests(unittest.IsolatedAsyncioTestCase):
    def service(self, cooling=False):
        service = object.__new__(MemoryService)
        service._redis = SimpleNamespace(get=AsyncMock(return_value='1' if cooling else None))
        return service

    async def test_periodic_and_keyword_triggers_are_all_retired(self):
        for turns, last in [(6, '解释 RAG'), (12, '解释缓存'), (2, '记住我喜欢 Java'),
                            (2, '我平时主要做后端'), (132, '继续上次')]:
            service = self.service()
            rows = history(2, last=last)
            self.assertFalse(await service.should_extract(1, rows, rows[-1]['content'], False, total_user_turns=turns))
            service._redis.get.assert_not_awaited()

    def test_constraint_context_accepts_real_database_row_adapter(self):
        engine = create_engine('sqlite://')
        try:
            with engine.connect() as connection:
                result = connection.execute(text("SELECT 42 AS memory_id, 'web_search' AS memory_key, 'deny' AS content, 'conversation' AS scope, 7 AS scope_conversation_id"))
                metadata = result._metadata
                row = Row(metadata, metadata._processors, metadata._keymap, result.fetchone())
                record = Record(row, (), engine.dialect, ({}, {}, {}))
                self.assertEqual({'id': '42', 'type': 'constraint', 'key': 'web_search', 'content': 'deny',
                                  'scope': 'conversation', 'conversation_id': '7'}, constraint_view(record))
        finally:
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
