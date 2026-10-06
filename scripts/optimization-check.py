"""Local SQL/Redis checks with isolated fixture ownership and cleanup."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.models.memory_change import MemoryChange
from app.models.memory_identity import MemoryConflict
from app.services.memory_policy import MemoryPolicyService
from app.services.memory import memory_service
from app.services.run_repository import RunRepository, digest
from app.services.operations import Operations
from app.services.durable_jobs import BackgroundWorker, DurableJobs
from app.graph.state_factory import create_initial_state
from app.graph.builder import get_graph, close_graph
from app.utils.snowflake import SnowflakeGenerator
from fastapi import HTTPException
from langgraph.checkpoint.base import empty_checkpoint


async def main():
    if db.url.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise RuntimeError('Local fixtures only')
    ids = SnowflakeGenerator(worker_id=30)
    uid, cid = ids.next_id(), ids.next_id()
    marker = f'optimization-{uuid4().hex}@sample.invalid'
    report = {'checks': [], 'cleanup_complete': False, 'scope': 'real local MySQL and Redis; no LLM calls'}
    output = ROOT / 'logs/evaluation' / f'optimization-storage-{datetime.now():%Y%m%d-%H%M%S}.json'
    checkpoint_ids = []
    saver = None

    def check(name, passed):
        report['checks'].append({'name': name, 'passed': bool(passed)})
        print(json.dumps(report['checks'][-1], ensure_ascii=False), flush=True)
        if not passed: raise AssertionError(name)

    await db.connect()
    repository, policy = RunRepository(db), MemoryPolicyService(db)
    async def new_state(message):
        await repository.cancel(cid, uid)
        run, _ = await repository.create(cid, uid, str(uuid4()), digest(message))
        state = create_initial_state(uid, message, [])
        state.update(conversation_id=cid, run_id=run['run_id'], execution_token=run['execution_token'],
                     memory_source_message=message, **(await policy.load_context(uid, cid)))
        return state

    try:
        await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,
            sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
            VALUES(:uid,'优化验证',:marker,'NotALoginCredential!',:marker,NOW(),2,1,0,0,1,1,0,0,0)""",
            {'uid': uid, 'marker': marker})
        await db.execute("""INSERT INTO ai_conversation(conversation_id,user_id,message_count,total_tokens,status,create_time,update_time)
            VALUES(:cid,:uid,0,0,1,NOW(),NOW())""", {'cid': cid, 'uid': uid})
        with patch.object(memory_service, 'sync_changes', AsyncMock(return_value=True)):
            s = await new_state('请保存本会话约束：文章面向初学者')
            change = MemoryChange(kind='constraint', key='audience', value='初学者', source_quote=s['user_message'])
            result = await policy.apply_changes(s, [change])
            mid = result['active_constraints'][0]['id']
            check('canonical_constraint_identity', result['active_constraints'][0]['key'] == 'article_audience')
            await db.execute("UPDATE user_memory SET memory_key='target_audience' WHERE memory_id=:mid AND user_id=:uid", {'mid': int(mid), 'uid': uid})
            s = await new_state('同一个要求，文章面向新手，不重复保存')
            result = await policy.apply_changes(s, [MemoryChange(kind='constraint', key='reader_level', value='面向新手', source_quote=s['user_message'])])
            check('legacy_alias_and_synonym_repeat_does_not_create_another_record', result['memory_change_log'][0]['operation'] == 'unchanged'
                and await db.fetch_val('SELECT COUNT(*) FROM user_memory WHERE user_id=:uid', {'uid': uid}) == 1)
            s = await new_state('文章面向专家')
            try:
                await policy.apply_changes(s, [MemoryChange(kind='constraint', key='article_audience', value='专家', source_quote=s['user_message'])])
            except MemoryConflict:
                check('unreferenced_conflict_rolls_back', await db.fetch_val(
                    "SELECT content FROM user_memory WHERE user_id=:uid AND memory_id=:mid AND status='active'", {'uid': uid, 'mid': int(mid)}) == '面向初学者')
            else: check('unreferenced_conflict_rolls_back', False)
            s = await new_state('明确替换原要求：文章面向专家')
            result = await policy.apply_changes(s, [MemoryChange(kind='constraint', key='article_audience', value='专家',
                record_id=mid, source_quote=s['user_message'])])
            check('explicit_replacement_has_one_active_record', len(result['active_constraints']) == 1
                  and result['active_constraints'][0]['content'] == '专家')
            s = await new_state('确认已保存的同一决策UseRRF，不重复新增')
            await db.execute("""INSERT INTO user_memory(memory_id,user_id,content,importance,source_conversation_id,
                create_time,update_time,memory_type,scope,scope_conversation_id,status,memory_key,source_quote)
                VALUES(:mid,:uid,'UseRRF',.8,:cid,NOW(),NOW(),'decision','conversation',:cid,'active','original_choice','确认UseRRF')""",
                {'mid': ids.next_id(), 'uid': uid, 'cid': cid})
            result = await policy.apply_changes(s, [MemoryChange(kind='decision', key='duplicate_choice', value='UseRRF', source_quote=s['user_message'])])
            check('exact_decision_under_another_key_is_not_duplicated', result['memory_change_log'][0]['operation'] == 'unchanged')
            check('decision_dedup_does_not_ignore_case', not await db.fetch_val(
                'SELECT memory_id FROM user_memory WHERE user_id=:uid AND CAST(content AS BINARY)=CAST(:content AS BINARY)',
                {'uid': uid, 'content': 'useRRF'}))
        s = await new_state('expiry fixture')
        await db.execute("UPDATE agent_run SET status='awaiting_approval',deadline=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE run_id=:rid", {'rid': s['run_id']})
        check('expired_approval_releases_active_slot', await repository.expire_existing(cid, uid, s['run_id']))
        try: await repository.assert_executor(s['run_id'], s['execution_token'])
        except HTTPException as exc: check('expired_executor_is_fenced', exc.status_code == 409)
        else: check('expired_executor_is_fenced', False)
        s = await new_state('checkpoint fixture')
        await db.execute("UPDATE agent_run SET status='succeeded',updated_at=TIMESTAMPADD(DAY,-31,UTC_TIMESTAMP(6)) WHERE run_id=:rid", {'rid': s['run_id']})
        saver = (await get_graph()).checkpointer
        async def checkpoint(rid):
            checkpoint_ids.append(rid)
            return await saver.aput({'configurable': {'thread_id': 'run_' + rid, 'checkpoint_ns': ''}},
                empty_checkpoint(), {'source': 'input', 'step': 0, 'parents': {}}, {})
        cfg = await checkpoint(s['run_id'])
        check('terminal_checkpoint_fixture_exists', await saver.aget_tuple(cfg) is not None)
        worker = BackgroundWorker(DurableJobs(db))
        await worker.handle({'kind': 'checkpoint_cleanup', 'user_id': uid, 'conversation_id': cid, 'payload': {'run_id': s['run_id']}})
        check('old_terminal_checkpoint_is_removed', await saver.aget_tuple(cfg) is None)
        s = await new_state('pending approval fixture')
        await db.execute("""UPDATE agent_run SET status='awaiting_approval',deadline=TIMESTAMPADD(DAY,1,UTC_TIMESTAMP(6)),
            updated_at=TIMESTAMPADD(DAY,-31,UTC_TIMESTAMP(6)) WHERE run_id=:rid""", {'rid': s['run_id']})
        cfg = await checkpoint(s['run_id'])
        await worker.handle({'kind': 'checkpoint_cleanup', 'user_id': uid, 'conversation_id': cid, 'payload': {'run_id': s['run_id']}})
        check('pending_approval_checkpoint_is_preserved', await saver.aget_tuple(cfg) is not None)
        check('live_approval_cannot_be_expired', not await repository.expire_existing(cid, uid, s['run_id']))
        await db.execute("UPDATE agent_run SET draft_article_id=42,deadline=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE run_id=:rid", {'rid': s['run_id']})
        check('committed_draft_is_never_expired_by_sweeper', not await repository.expire_existing(cid, uid, s['run_id']))
        metrics = await Operations(db).metrics()
        check('metrics_are_available_and_contain_no_fixture_text', 'recent_quality' in metrics and marker not in json.dumps(metrics))
    finally:
        if saver:
            for rid in checkpoint_ids: await saver.adelete_thread('run_' + rid)
        await close_graph()
        if await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE user_id=:uid AND email=:marker', {'uid': uid, 'marker': marker}) == 1:
            async with db.transaction():
                for table in ('agent_run_event', 'agent_stream_frame'):
                    await db.execute(f'DELETE FROM {table} WHERE run_id IN (SELECT run_id FROM agent_run WHERE user_id=:uid)', {'uid': uid})
                for table in ('agent_background_job', 'user_memory_change', 'agent_run', 'user_memory', 'user_profile', 'ai_conversation'):
                    await db.execute(f'DELETE FROM {table} WHERE user_id=:uid', {'uid': uid})
                await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:marker', {'uid': uid, 'marker': marker})
            report['cleanup_complete'] = True
        await db.disconnect()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(str(output), flush=True)


if __name__ == '__main__': asyncio.run(main())
