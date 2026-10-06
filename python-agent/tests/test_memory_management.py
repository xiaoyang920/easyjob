import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager

from fastapi import HTTPException
from pydantic import ValidationError
from app.services.memory_management import MemoryManagement, ProfileEdit, RecordEdit, record_view
from app.services.run_repository import digest


def row(**values): return SimpleNamespace(_mapping=values)


class Database:
    def __init__(self):
        self.profile = {'user_id': 7, 'tech_stack': '[]', 'interests': '[]', 'experience': 'unknown', 'preferences': '{}'}
        self.record = dict(memory_id=19, user_id=7, content='禁止联网', status='active', update_time='2026-10-03',
                           importance=.5, source_conversation_id=11, memory_type='constraint', memory_key='other', scope='user', scope_conversation_id=None, source_quote='原话')
        self.writes = []
        self.fetch_val = AsyncMock(return_value=0)
        self.fetch_all = AsyncMock(return_value=[])

    @asynccontextmanager
    async def transaction(self):
        old = len(self.writes)
        try: yield
        except BaseException:
            self.writes = self.writes[:old]
            raise

    async def fetch_one(self, sql, params):
        if 'FROM user_profile' in sql: return row(**self.profile)
        if 'FROM user_memory' in sql:
            assert 'user_id=:uid' in sql
            if 'memory_id<>:mid' in sql: return None
            return row(**self.record) if params['uid'] == self.record['user_id'] else None
        raise AssertionError(sql)

    async def execute(self, sql, params): self.writes.append((sql, params))


class MemoryManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_archived_event_cannot_be_reenabled_but_can_be_deleted(self):
        db = Database(); db.record['memory_type'] = 'event'
        view = record_view(row(**db.record))
        self.assertFalse(view['recall_enabled'])
        with self.assertRaises(HTTPException) as error:
            await MemoryManagement(db).change_record(7, 19, view['version'],
                edit=RecordEdit(version=view['version'], content='old', active=True))
        self.assertEqual(error.exception.status_code, 409); self.assertEqual(db.writes, [])
        await MemoryManagement(db).change_record(7, 19, view['version'])
        self.assertTrue(any("status='deleted'" in sql for sql, _ in db.writes))

    async def test_default_pagination_excludes_events_and_archive_is_separate(self):
        db = Database(); service = MemoryManagement(db)
        result = await service.overview(7)
        self.assertEqual(result['extraction'], {'enabled': False})
        self.assertIn("m.memory_type IN ('constraint','decision')", db.fetch_all.call_args_list[0].args[0])
        self.assertEqual(db.fetch_all.call_args_list[0].args[1]['kind'], 'all')
        await service.overview(7, kind='event')
        self.assertEqual(db.fetch_all.call_args_list[-2].args[1]['kind'], 'event')

    async def test_foreign_record_is_not_read_or_changed(self):
        db = Database()
        with self.assertRaises(HTTPException) as exc:
            await MemoryManagement(db).change_record(8, 19, record_view(row(**db.record))['version'])
        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(db.writes, [])

    async def test_delete_erases_content_and_enqueues_cleanup_in_transaction(self):
        db = Database()
        await MemoryManagement(db).change_record(7, 19, record_view(row(**db.record))['version'])
        sql = '\n'.join(query for query, _ in db.writes)
        self.assertIn("content='',source_quote=NULL,status='deleted'", sql)
        job = next(params for query, params in db.writes if 'agent_background_job' in query)
        self.assertEqual(job['uid'], 7)
        self.assertEqual(job['payload'], '{"ids": [19]}')

    async def test_stale_record_version_rolls_back(self):
        db = Database()
        with self.assertRaises(HTTPException) as exc:
            await MemoryManagement(db).change_record(7, 19, '0' * 64)
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(db.writes, [])

    async def test_reenable_uses_new_identity_and_durable_index_job(self):
        db = Database()
        db.record['status'] = 'inactive'
        version = record_view(row(**db.record))['version']
        await MemoryManagement(db).change_record(7, 19, version, edit=RecordEdit(version=version, content='新约束', active=True))
        inserted = next(params for query, params in db.writes if 'INSERT INTO user_memory' in query)
        self.assertNotEqual(inserted['id'], 19)
        self.assertEqual(inserted['uid'], 7)
        self.assertEqual(inserted['content'], '新约束')

    async def test_profile_version_prevents_overwriting_new_preferences(self):
        db = Database()
        db.profile['preferences'] = '{"language":"中文"}'
        original = dict(topics=[], experience='unknown', preferences={})
        with self.assertRaises(HTTPException) as exc:
            await MemoryManagement(db).save_profile(7, ProfileEdit(version=digest(original)))
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(db.writes, [])

    def test_profile_and_record_bounds(self):
        for values in ({'user_id': 8}, {'preferences': {'bad-key': 'x'}}, {'topics': ['x' * 101]}, {'topics': ['']}, {'topics': ['x'] * 41}, {'tech_stack': ['Java']}):
            with self.assertRaises(ValidationError): ProfileEdit(version='0' * 64, **values)
        with self.assertRaises(ValidationError): RecordEdit(version='bad', content='x', active=True)

    async def test_legacy_topics_merge_and_save_does_not_resurrect_removed_items(self):
        import json
        db = Database()
        db.profile.update(tech_stack='["Java", "Redis"]', interests='[" redis ", "Agent"]', experience='Python新手')
        service = MemoryManagement(db)
        before = await service.overview(7)
        self.assertEqual(before['profile']['topics'], ['redis', 'Agent', 'Java'])
        self.assertNotIn('tech_stack', before['profile'])
        self.assertNotIn('interests', before['profile'])
        await service.save_profile(7, ProfileEdit(version=before['profile_version'], topics=[' Java ', 'java'], experience='Python新手'))
        params = next(p for sql, p in db.writes if 'UPDATE user_profile' in sql)
        self.assertEqual(json.loads(params['it']), ['Java'])
        self.assertEqual(params['ts'], '[]')
        db.profile.update(tech_stack=params['ts'], interests=params['it'], experience=params['exp'], preferences=params['pref'])
        after = await service.overview(7)
        self.assertEqual(after['profile']['topics'], ['Java'])
        self.assertEqual(after['profile']['experience'], 'Python新手')
        await service.save_profile(7, ProfileEdit(version=after['profile_version']))
        clear = [p for sql, p in db.writes if 'UPDATE user_profile' in sql][-1]
        self.assertEqual((clear['ts'], clear['it']), ('[]', '[]'))

    async def test_overview_filters_deleted_and_returns_string_ids(self):
        db = Database(); db.fetch_all.side_effect = [[row(**db.record)], []]
        result = await MemoryManagement(db).overview(7)
        self.assertEqual(result['memories'][0]['memory_id'], '19')
        self.assertIn("m.status IN ('active','inactive')", db.fetch_all.call_args_list[0].args[0])
        self.assertEqual(db.fetch_all.call_args_list[0].args[1]['uid'], 7)

    async def test_write_status_is_owner_scoped_and_never_returns_payload_or_raw_error(self):
        from datetime import datetime
        db = Database(); db.fetch_all.side_effect = [[], [row(job_id='fixture', status='completed', outcome='conflict',
            updated_at=datetime(2026, 10, 5), payload='private', last_error='secret')]]
        result = await MemoryManagement(db).overview(7)
        self.assertEqual(result['write_jobs'], [{'id': 'fixture', 'status': 'conflict', 'updated_at': '2026-10-05T00:00:00Z'}])
        query = db.fetch_all.call_args_list[1]
        self.assertIn('WHERE user_id=:uid', query.args[0]); self.assertEqual(query.args[1], {'uid': 7})
