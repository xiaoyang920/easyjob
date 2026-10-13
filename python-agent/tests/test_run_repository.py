from rpc_fakes import public_reader
"""Offline SQL control-path checks; live MySQL concurrency is a deployment gate."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from pymysql.err import OperationalError

from app.services.run_repository import RunRepository
from app.services.evidence_verifier import verify_public_evidence
from app.services.reranker import RerankerService
from fakes import RUN_ID, HASH


def row(**values):
    return SimpleNamespace(_mapping=values)


def database(run):
    if run:
        run = {"conversation_id": 11, "user_id": 7, "status": "running",
               "expired": False, "draft_article_id": None, **run}
    calls = []
    @asynccontextmanager
    async def transaction():
        calls.append("begin")
        try:
            yield
            calls.append("commit")
        except BaseException:
            calls.append("rollback")
            raise
    async def fetch(query, params=None):
        calls.append(query)
        if "FROM ai_conversation" in query:
            return row(user_id=7, status=1)
        return row(**run) if run else None
    return SimpleNamespace(transaction=transaction, fetch_one=fetch,
        fetch_val=AsyncMock(side_effect=lambda sql,*a: None if 'draft_commit' in sql else 1), execute=AsyncMock()), calls


def creation_database(active=None, previous=None, insert_errors=()):
    db, calls = database(None)
    stored = None
    errors = iter(insert_errors)

    async def fetch(query, params=None):
        calls.append(query)
        if "FROM ai_conversation" in query:
            return row(user_id=7, status=1)
        if "request_id=:req" in query:
            return row(**previous) if previous else None
        if "active_conversation_id=:cid" in query:
            return row(run_id=RUN_ID) if active else None
        if "AS expired" in query:
            return row(**{"status": "running", "expired": False, "draft_article_id": None, **(active or {})})
        return row(**stored) if stored else None

    async def execute(query, params=None):
        nonlocal stored
        calls.append(query)
        if "INSERT INTO agent_run" in query:
            error = next(errors, None)
            if error:
                raise error
            stored = {"run_id": params["rid"], "conversation_id": params["cid"],
                      "user_id": params["uid"], "request_id": params["req"],
                      "input_hash": params["hash"], "status": "running"}

    db.fetch_one = fetch
    db.execute = AsyncMock(side_effect=execute)
    return db, calls


@patch('app.services.service_queries.user_source', new=AsyncMock(return_value='business'))
class RunCreationTests(unittest.IsolatedAsyncioTestCase):
    async def test_sweeper_rechecks_expiry_under_parent_and_existing_run_locks(self):
        for values, expected in (({'expired': True}, True), ({'expired': False}, False),
                ({'expired': True, 'status': 'succeeded'}, False),
                ({'expired': True, 'status': 'awaiting_approval', 'draft_article_id': 42}, False)):
            db, calls = database(values)
            with self.subTest(values=values):
                result = await RunRepository(db).expire_existing(11, 7, RUN_ID)
                self.assertEqual(result, expected)
                locks = [c for c in calls if 'FOR UPDATE' in c]
                self.assertIn('ai_conversation', locks[0])
                self.assertIn('WHERE run_id=:rid', locks[1])
                self.assertEqual(db.execute.await_count, 2 * int(expected))
    async def test_empty_conversation_creates_without_locking_missing_run_range(self):
        db, calls = creation_database()
        run, created = await RunRepository(db).create(11, 7, "req", HASH)
        self.assertTrue(created)
        self.assertEqual(run["status"], "running")
        locking = [q for q in calls if "FOR UPDATE" in q]
        self.assertEqual(len(locking), 1)
        self.assertIn("ai_conversation", locking[0])
        self.assertFalse(any("UPDATE agent_run" in q for q in calls))
        self.assertEqual(calls[-1], "commit")

    async def test_running_and_pending_approval_block_new_requests(self):
        for status in ("running", "awaiting_approval"):
            with self.subTest(status=status):
                db, calls = creation_database(active={"status": status})
                with self.assertRaises(HTTPException) as caught:
                    await RunRepository(db).create(11, 7, "req", HASH)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertFalse(any("INSERT INTO agent_run" in q for q in calls))
                self.assertEqual(calls[-1], "rollback")

    async def test_expired_unsaved_run_is_replaced_by_primary_key(self):
        db, calls = creation_database(active={"expired": True})
        _, created = await RunRepository(db).create(11, 7, "req", HASH)
        self.assertTrue(created)
        expiration = [c for c in db.execute.call_args_list if "UPDATE agent_run" in c.args[0]]
        self.assertEqual(len(expiration), 1)
        self.assertIn("WHERE run_id=:rid", expiration[0].args[0])
        self.assertEqual(expiration[0].args[1], {"rid": RUN_ID})

    async def test_expired_run_with_committed_draft_still_blocks_replacement(self):
        db, _ = creation_database(active={"expired": True, "draft_article_id": 99})
        with self.assertRaises(HTTPException) as caught:
            await RunRepository(db).create(11, 7, "req", HASH)
        self.assertEqual(caught.exception.status_code, 409)
        db.execute.assert_not_awaited()

    async def test_current_failed_status_overrides_stale_active_lookup(self):
        db, _ = creation_database(active={"status": "failed"})
        _, created = await RunRepository(db).create(11, 7, "req", HASH)
        self.assertTrue(created)

    async def test_identical_request_replays_without_insert(self):
        previous = {"run_id": RUN_ID, "conversation_id": 11, "input_hash": HASH}
        db, calls = creation_database(previous=previous)
        run, created = await RunRepository(db).create(11, 7, "req", HASH)
        self.assertFalse(created)
        self.assertEqual(run, previous)
        db.execute.assert_not_awaited()
        self.assertEqual(calls[-1], "commit")

    async def test_reused_request_with_different_input_or_conversation_is_rejected(self):
        for previous in ({"conversation_id": 12, "input_hash": HASH},
                         {"conversation_id": 11, "input_hash": "different"}):
            db, calls = creation_database(previous=previous)
            with self.assertRaises(HTTPException) as caught:
                await RunRepository(db).create(11, 7, "req", HASH)
            self.assertEqual(caught.exception.status_code, 409)
            db.execute.assert_not_awaited()
            self.assertEqual(calls[-1], "rollback")

    async def test_deadlock_retries_after_rollback_with_same_idempotency_key(self):
        db, calls = creation_database(insert_errors=[OperationalError(1213, "deadlock")])
        with patch("app.services.run_repository.asyncio.sleep", new_callable=AsyncMock) as sleep:
            run, created = await RunRepository(db).create(11, 7, "req", HASH)
        self.assertTrue(created)
        self.assertEqual(run["request_id"], "req")
        self.assertEqual(calls.count("begin"), 2)
        self.assertEqual(calls.count("rollback"), 1)
        self.assertEqual(calls.count("commit"), 1)
        self.assertLess(calls.index("rollback"), calls.index("begin", 1))
        self.assertEqual([c.args[1]["req"] for c in db.execute.call_args_list], ["req", "req"])
        sleep.assert_awaited_once()

    async def test_deadlock_exhaustion_stops_after_three_transactions(self):
        db, calls = creation_database(insert_errors=[OperationalError(1213, "deadlock") for _ in range(3)])
        with patch("app.services.run_repository.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(OperationalError):
                await RunRepository(db).create(11, 7, "req", HASH)
        self.assertEqual(calls.count("begin"), 3)
        self.assertEqual(calls.count("rollback"), 3)
        self.assertNotIn("commit", calls)
        self.assertEqual(sleep.await_count, 2)

    async def test_other_database_errors_are_not_retried(self):
        db, calls = creation_database(insert_errors=[OperationalError(1040, "connections")])
        with patch("app.services.run_repository.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(OperationalError):
                await RunRepository(db).create(11, 7, "req", HASH)
        self.assertEqual(calls.count("begin"), 1)
        sleep.assert_not_awaited()


@patch('app.services.service_queries.user_source', new=AsyncMock(return_value='business'))
class RunArbitrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_settlement_preserves_input_anchor_and_progress_for_approval_and_history(self):
        metadata = {'user_message_id': '123', 'progress': {'node': 'main_delegate'}}
        db, _ = database({'execution_token': 't', 'status': 'running', 'result_json': json.dumps(metadata)})
        repo = RunRepository(db)
        repo.assert_executor = AsyncMock()
        result = await repo.settle(11, 7, RUN_ID, 't', 'awaiting_approval', {'reply': 'preview'})
        self.assertEqual(result, {**metadata, 'reply': 'preview'})
        self.assertEqual(json.loads(db.execute.await_args.args[1]['result']), result)

    async def test_cancelled_run_cannot_persist_assistant_result(self):
        db, calls = database({"execution_token": "t", "status": "cancelled"})
        append = AsyncMock()
        with self.assertRaises(HTTPException):
            await RunRepository(db).settle(11, 7, RUN_ID, "t", "succeeded", {}, append)
        append.assert_not_awaited()
        db.execute.assert_not_awaited()
        self.assertIn("ai_conversation", calls[1])
        self.assertIn("FOR UPDATE", calls[1])
        self.assertIn("FOR UPDATE", calls[2])
        self.assertEqual(calls[-1], "rollback")

    async def test_old_executor_token_cannot_settle_or_resume(self):
        db, _ = database({"execution_token": "new", "status": "running", "draft_hash": HASH})
        with self.assertRaises(HTTPException):
            await RunRepository(db).settle(11, 7, RUN_ID, "old", "succeeded", {})
        with self.assertRaises(HTTPException):
            await RunRepository(db).claim_resume(11, 7, RUN_ID, HASH)
        db.execute.assert_not_awaited()

    async def test_repeated_settlement_returns_original_and_never_appends_twice(self):
        original = {"reply": "saved"}
        db, _ = database({"execution_token": "t", "status": "succeeded", "result_json": json.dumps(original)})
        append = AsyncMock()
        result = await RunRepository(db).settle(11, 7, RUN_ID, "t", "succeeded", {"reply": "new"}, append)
        self.assertEqual(result, original)
        append.assert_not_awaited()
        db.execute.assert_not_awaited()

    async def test_cancel_after_draft_commit_returns_committed_id(self):
        db, _ = database({"run_id": RUN_ID, "execution_token": "t", "status": "running", "draft_article_id": 99})
        result = await RunRepository(db).cancel(11, 7)
        self.assertEqual(result, {"status": "draft_saved", "draftArticleId": "99"})
        db.execute.assert_not_awaited()

    async def test_cancel_before_commit_terminates_run(self):
        db, _ = database({"run_id": RUN_ID, "status": "running", "draft_article_id": None})
        result = await RunRepository(db).cancel(11, 7)
        self.assertEqual(result["status"], "cancelled")
        updates = [call.args[0] for call in db.execute.call_args_list if 'UPDATE agent_run' in call.args[0]]
        self.assertEqual(len(updates), 1)
        self.assertIn("status='cancelled'", updates[0])
        self.assertIn('DELETE l FROM agent_execution_lease', db.execute.call_args.args[0])

    async def test_message_failure_rolls_back_ledger_completion(self):
        db, calls = database({"execution_token": "t", "status": "running"})
        repo = RunRepository(db)
        with patch.object(repo, "assert_executor", AsyncMock()), self.assertRaises(RuntimeError):
            await repo.settle(11, 7, RUN_ID, "t", "succeeded", {}, AsyncMock(side_effect=RuntimeError("write failed")))
        db.execute.assert_not_awaited()
        self.assertEqual(calls[-1], "rollback")

    async def test_second_running_conversation_request_is_rejected_before_insert(self):
        db, _ = database({"run_id": RUN_ID})
        repo = RunRepository(db)
        with patch.object(repo, "find_request", AsyncMock(return_value=None)), self.assertRaises(HTTPException):
            await repo.create(11, 7, RUN_ID, HASH)
        self.assertFalse(any("INSERT INTO agent_run" in call.args[0] for call in db.execute.call_args_list))


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unpublished_or_changed_source_cannot_pass_delivery_gate(self):
        citation = {"articleId": "42", "sourceHash": HASH}
        for rows in ([], [row(article_id=42, content="changed")] ):
            with patch("app.services.evidence_verifier.public_read", AsyncMock(return_value=[dict(r._mapping) for r in rows])), self.assertRaises(ValueError):
                await verify_public_evidence([citation])

    async def test_low_relevance_is_not_promoted_to_successful_evidence(self):
        service = RerankerService()
        await service.client.aclose()
        service.client = SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"output": {"results": [{"index": 0, "relevance_score": 0.01}]}})))
        result = await service.rerank("q", [{"title": "A", "content": "unrelated", "score": 1}])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
