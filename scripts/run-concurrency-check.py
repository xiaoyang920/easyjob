"""Real local MySQL regression checks; creates and removes isolated fixtures.

No LLM calls, article writes or changes to the database isolation level.
Run with the project's Python environment; --reproduce-old exercises the old
empty-range locking pattern on two temporary conversations only.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python-agent"))

from fastapi import HTTPException
from pymysql.err import OperationalError
from app.clients.mysql_client import db
from app.services.run_repository import RunRepository, digest
from app.utils.snowflake import SnowflakeGenerator


async def main(args):
    if db.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("This fixture check only supports a local MySQL database")
    ids = SnowflakeGenerator(worker_id=29)
    uid = ids.next_id()
    marker = f"run-lock-check-{uuid4().hex}@sample.invalid"
    report = {"started_at": datetime.now().astimezone().isoformat(), "checks": [],
              "different_conversation_requests": args.requests, "concurrency": args.concurrency,
              "cleanup_complete": False}
    output = ROOT / "logs" / "evaluation" / f"run-concurrency-{datetime.now():%Y%m%d-%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    repo = RunRepository(db)
    fixture_created = False

    def check(name, condition, **details):
        report["checks"].append({"name": name, "passed": bool(condition), **details})
        print(json.dumps(report["checks"][-1], ensure_ascii=False), flush=True)
        if not condition:
            raise AssertionError(name)

    async def conversation():
        cid = ids.next_id()
        await db.execute("""INSERT INTO ai_conversation
            (conversation_id,user_id,message_count,total_tokens,status,create_time,update_time)
            VALUES (:cid,:uid,0,0,1,NOW(),NOW())""", {"cid": cid, "uid": uid})
        return cid

    async def create(cid, req=None, method=None):
        try:
            run, created = await (method or repo.create)(cid, uid, req or str(uuid4()), digest("fixture"))
            return {"run": run, "created": created}
        except HTTPException as exc:
            return {"conflict": exc.status_code}
        except OperationalError as exc:
            return {"mysql_error": exc.args[0]}

    async def old_create(cid, barrier):
        async with db.transaction():
            await repo._lock_conversation(cid, uid)
            await db.execute("""UPDATE agent_run SET status='expired',updated_at=UTC_TIMESTAMP(6)
                WHERE conversation_id=:cid AND status IN ('running','awaiting_approval')
                AND deadline<=UTC_TIMESTAMP(6) AND draft_article_id IS NULL""", {"cid": cid})
            await db.fetch_one("""SELECT run_id FROM agent_run WHERE conversation_id=:cid
                AND status IN ('running','awaiting_approval') FOR UPDATE""", {"cid": cid})
            await barrier.wait()
            await db.execute("""INSERT INTO agent_run
                (run_id,conversation_id,user_id,request_id,input_hash,execution_token,status,deadline)
                VALUES (:rid,:cid,:uid,:req,:hash,:token,'running',TIMESTAMPADD(SECOND,300,UTC_TIMESTAMP(6)))""",
                {"rid": str(uuid4()), "cid": cid, "uid": uid, "req": str(uuid4()),
                 "hash": digest("fixture"), "token": str(uuid4())})

    await db.connect()
    try:
        report["transaction_isolation"] = await db.fetch_val("SELECT @@transaction_isolation")
        await db.execute("""INSERT INTO user_info
            (user_id,nick_name,email,password,person_introduction,join_time,sex,status,
             total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
            VALUES (:uid,'运行并发测试',:email,'NotALoginCredential!',:marker,NOW(),2,1,0,0,1,1,0,0,0)""",
            {"uid": uid, "email": marker, "marker": marker})
        fixture_created = True

        if args.reproduce_old:
            old_cids = [await conversation(), await conversation()]
            barrier = asyncio.Barrier(2)
            old = await asyncio.wait_for(asyncio.gather(
                *(old_create(cid, barrier) for cid in old_cids), return_exceptions=True), timeout=20)
            deadlocks = sum(isinstance(item, OperationalError) and item.args[0] == 1213 for item in old)
            check("old_empty_range_pattern_reproduces_deadlock", deadlocks >= 1,
                  deadlocks=deadlocks, successful_transactions=sum(item is None for item in old))

        cids = [await conversation() for _ in range(args.requests)]
        semaphore = asyncio.Semaphore(args.concurrency)

        async def independent(cid):
            async with semaphore:
                # Bypass retries to verify the locking fix itself, rather than
                # conceal deadlocks behind successful retries.
                return await create(cid, method=repo._create_once)

        results = await asyncio.gather(*(independent(cid) for cid in cids))
        check("different_conversations_without_retry", all(r.get("created") for r in results),
              successes=sum(bool(r.get("created")) for r in results),
              deadlocks=sum(r.get("mysql_error") == 1213 for r in results))

        same = await conversation()
        results = await asyncio.gather(*(create(same) for _ in range(args.concurrency)))
        count = await db.fetch_val("SELECT COUNT(*) FROM agent_run WHERE conversation_id=:cid", {"cid": same})
        check("same_conversation_one_run", count == 1 and sum(bool(r.get("created")) for r in results) == 1
              and sum(r.get("conflict") == 409 for r in results) == args.concurrency - 1,
              rows=count, conflicts=sum(r.get("conflict") == 409 for r in results))

        replay_cid, request_id = await conversation(), str(uuid4())
        results = await asyncio.gather(*(create(replay_cid, request_id) for _ in range(args.concurrency)))
        check("same_request_replays_one_run", sum(r.get("created") is True for r in results) == 1
              and sum(r.get("created") is False for r in results) == args.concurrency - 1
              and len({r["run"]["run_id"] for r in results if "run" in r}) == 1)

        lifecycle_cid = await conversation()
        original = (await create(lifecycle_cid))["run"]
        await db.execute("UPDATE agent_run SET deadline=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE run_id=:rid",
                         {"rid": original["run_id"]})
        replacement = await create(lifecycle_cid)
        old_status = await db.fetch_val("SELECT status FROM agent_run WHERE run_id=:rid", {"rid": original["run_id"]})
        fenced = False
        try:
            await repo.assert_executor(original["run_id"], original["execution_token"])
        except HTTPException as exc:
            fenced = exc.status_code == 409
        check("expired_unsaved_run_replaced_and_old_executor_fenced",
              replacement.get("created") and old_status == "expired" and fenced)

        current = replacement["run"]
        await db.execute("UPDATE agent_run SET status='awaiting_approval' WHERE run_id=:rid", {"rid": current["run_id"]})
        check("pending_approval_blocks_new_run", (await create(lifecycle_cid)).get("conflict") == 409)
        await db.execute("""UPDATE agent_run SET deadline=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)),
            draft_article_id=1 WHERE run_id=:rid""", {"rid": current["run_id"]})
        check("expired_committed_draft_blocks_replacement", (await create(lifecycle_cid)).get("conflict") == 409)
        await db.execute("UPDATE agent_run SET draft_article_id=NULL,status='succeeded' WHERE run_id=:rid",
                         {"rid": current["run_id"]})
        check("completed_run_allows_next_request", (await create(lifecycle_cid)).get("created") is True)
    finally:
        try:
            if fixture_created:
                # Delete only the newly created account's test records. No graph
                # or checkpoint was created and no real article was saved.
                async with db.transaction():
                    owner = await db.fetch_val("SELECT user_id FROM user_info WHERE user_id=:uid AND email=:email FOR UPDATE",
                                               {"uid": uid, "email": marker})
                    if owner != uid:
                        raise RuntimeError("Fixture ownership verification failed")
                    await db.execute("DELETE FROM agent_run WHERE user_id=:uid", {"uid": uid})
                    await db.execute("DELETE FROM ai_conversation WHERE user_id=:uid", {"uid": uid})
                    await db.execute("DELETE FROM user_info WHERE user_id=:uid AND email=:email", {"uid": uid, "email": marker})
                report["cleanup_complete"] = True
        finally:
            report["finished_at"] = datetime.now().astimezone().isoformat()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Report: {output}", flush=True)
            await db.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--reproduce-old", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.requests <= 1000 or not 2 <= args.concurrency <= 10:
        parser.error("requests must be 1..1000; concurrency must be 2..10")
    asyncio.run(main(args))
