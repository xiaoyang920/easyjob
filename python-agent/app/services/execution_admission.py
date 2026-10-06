"""Cross-process admission. Short transactions lock one existing control row."""
import asyncio
from uuid import uuid4
from fastapi import HTTPException
from app.clients.mysql_client import db
from app.config import settings


class ExecutionAdmission:
    def __init__(self, database=db):
        self.db = database

    async def acquire(self, uid):
        ticket = str(uuid4())
        try:
            async with self.db.transaction():
                await self.db.fetch_val('SELECT gate_id FROM agent_execution_gate WHERE gate_id=1 FOR UPDATE')
                await self.db.execute('DELETE FROM agent_execution_lease WHERE expires_at<=UTC_TIMESTAMP(6)')
                pending = await self.db.fetch_val("SELECT COUNT(*) FROM agent_execution_lease WHERE state='waiting'")
                active = await self.db.fetch_val("SELECT COUNT(*) FROM agent_execution_lease WHERE state='active'")
                user_active = await self.db.fetch_val("SELECT COUNT(*) FROM agent_execution_lease WHERE state='active' AND user_id=:uid", {'uid': uid})
                ready = pending == 0 and active < settings.EXECUTION_GLOBAL_LIMIT and user_active < settings.EXECUTION_USER_LIMIT
                if not ready and pending >= settings.EXECUTION_QUEUE_LIMIT:
                    raise HTTPException(429, '智能助手队列已满，请稍后重试', headers={'Retry-After': '3'})
                await self.db.execute("""INSERT INTO agent_execution_lease (ticket,user_id,state,expires_at)
                    VALUES (:ticket,:uid,:state,TIMESTAMPADD(SECOND,:ttl,UTC_TIMESTAMP(6)))""",
                    {'ticket': ticket, 'uid': uid, 'state': 'active' if ready else 'waiting',
                     'ttl': settings.RUN_TIMEOUT_SECONDS + 60 if ready else settings.EXECUTION_WAIT_SECONDS + 2})
            if ready: return ticket
            async with asyncio.timeout(settings.EXECUTION_WAIT_SECONDS):
                while True:
                    await asyncio.sleep(.25)
                    async with self.db.transaction():
                        await self.db.fetch_val('SELECT gate_id FROM agent_execution_gate WHERE gate_id=1 FOR UPDATE')
                        # Pick the oldest runnable user, avoiding head-of-line blocking by a busy user.
                        first = await self.db.fetch_val("""SELECT ticket FROM agent_execution_lease w
                            WHERE state='waiting' AND expires_at>UTC_TIMESTAMP(6) AND
                            (SELECT COUNT(*) FROM agent_execution_lease a WHERE a.state='active'
                             AND a.expires_at>UTC_TIMESTAMP(6) AND a.user_id=w.user_id)<:per_user
                            ORDER BY created_at,ticket LIMIT 1""", {'per_user': settings.EXECUTION_USER_LIMIT})
                        count = await self.db.fetch_val("SELECT COUNT(*) FROM agent_execution_lease WHERE state='active' AND expires_at>UTC_TIMESTAMP(6)")
                        if first == ticket and count < settings.EXECUTION_GLOBAL_LIMIT:
                            await self.db.execute("""UPDATE agent_execution_lease SET state='active',
                                expires_at=TIMESTAMPADD(SECOND,:ttl,UTC_TIMESTAMP(6)) WHERE ticket=:ticket""",
                                {'ticket': ticket, 'ttl': settings.RUN_TIMEOUT_SECONDS + 60})
                            return ticket
        except BaseException as error:
            await asyncio.shield(self.release(ticket))
            if isinstance(error, TimeoutError):
                raise HTTPException(429, '智能助手繁忙，排队超时，请稍后重试', headers={'Retry-After': '3'}) from error
            raise

    async def release(self, ticket):
        if ticket:
            await self.db.execute('DELETE FROM agent_execution_lease WHERE ticket=:ticket', {'ticket': ticket})


execution_admission = ExecutionAdmission()
