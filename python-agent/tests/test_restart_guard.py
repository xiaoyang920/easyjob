"""Restart and request admission share a gate; never stop an admitted run."""
import asyncio
from contextlib import asynccontextmanager, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.services.execution_admission import ExecutionAdmission


class GateDatabase:
    def __init__(self, *, runs=0, leases=0, gate=1):
        self.lock = asyncio.Lock()
        self.runs, self.gate = runs, gate
        self.leases = {str(i): {'uid': 7, 'state': 'active'} for i in range(leases)}
        self.is_connected = False

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            yield

    async def fetch_val(self, sql, params=None):
        if 'agent_execution_gate' in sql:
            return self.gate
        if 'agent_run' in sql:
            return self.runs
        if "state='waiting'" in sql:
            return sum(row['state'] == 'waiting' for row in self.leases.values())
        if "state='active'" in sql:
            return sum(row['state'] == 'active' and (not params or row['uid'] == params['uid'])
                       for row in self.leases.values())
        return len(self.leases)

    async def execute(self, sql, params=None):
        if sql.startswith('INSERT INTO agent_execution_lease'):
            self.leases[params['ticket']] = {'uid': params['uid'], 'state': params['state']}
        elif 'WHERE ticket=:ticket' in sql:
            self.leases.pop(params['ticket'], None)


class IdleRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_guard_wins_race_new_request_waits_until_guard_is_released(self):
        database = GateDatabase()
        admission = ExecutionAdmission(database)
        async with admission.idle_restart():
            pending = asyncio.create_task(admission.acquire(7))
            await asyncio.sleep(0)
            self.assertFalse(pending.done())
            self.assertFalse(database.leases)
        ticket = await asyncio.wait_for(pending, 1)
        self.assertIn(ticket, database.leases)
        await admission.release(ticket)

    async def test_request_wins_race_restart_is_refused_before_run_row_exists(self):
        database = GateDatabase()
        admission = ExecutionAdmission(database)
        ticket = await admission.acquire(7)
        self.assertEqual(database.runs, 0)
        with self.assertRaisesRegex(RuntimeError, 'restart refused'):
            async with admission.idle_restart():
                self.fail('Must not restart an admitted request')
        self.assertIn(ticket, database.leases)
        self.assertFalse(database.lock.locked())
        await admission.release(ticket)

    async def test_running_and_waiting_requests_each_prevent_restart(self):
        for runs, leases, waiting in [(1, 0, False), (0, 1, False), (0, 1, True)]:
            with self.subTest(runs=runs, leases=leases, waiting=waiting):
                database = GateDatabase(runs=runs, leases=leases)
                if waiting:
                    database.leases['0']['state'] = 'waiting'
                with self.assertRaises(RuntimeError):
                    async with ExecutionAdmission(database).idle_restart():
                        self.fail('Busy restart was allowed')
                self.assertEqual(len(database.leases), leases)
                self.assertFalse(database.lock.locked())

    async def test_missing_control_row_refuses_restart(self):
        database = GateDatabase(gate=None)
        with self.assertRaisesRegex(RuntimeError, 'gate is unavailable'):
            async with ExecutionAdmission(database).idle_restart():
                self.fail('Missing gate cannot establish idle state')

    async def test_restart_exception_releases_admission_lock(self):
        database = GateDatabase()
        with self.assertRaisesRegex(RuntimeError, 'injected restart failure'):
            async with ExecutionAdmission(database).idle_restart():
                raise RuntimeError('injected restart failure')
        self.assertFalse(database.lock.locked())
        ticket = await ExecutionAdmission(database).acquire(7)
        self.assertIn(ticket, database.leases)

    async def test_cancelled_guard_releases_lock(self):
        database = GateDatabase()
        ready = asyncio.Event()
        async def restart():
            async with ExecutionAdmission(database).idle_restart():
                ready.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(restart())
        await ready.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(database.lock.locked())


class GuardProtocolTests(unittest.IsolatedAsyncioTestCase):
    def helper(self):
        source = Path(__file__).resolve().parents[2] / 'scripts' / 'agent-restart-guard.py'
        spec = importlib.util.spec_from_file_location('restart_guard_helper', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    async def test_release_and_parent_eof_both_close_database_and_unlock(self):
        helper = self.helper()
        for command, expected in [('release\n', 0), ('', 2)]:
            with self.subTest(command=command):
                database, output = GateDatabase(), io.StringIO()
                with patch.object(helper, 'db', database), patch.object(helper.sys, 'stdin', io.StringIO(command)), \
                     redirect_stdout(output):
                    code = await helper.main()
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(output.getvalue()), {'status': 'ready'})
                self.assertFalse(database.lock.locked())
                self.assertFalse(database.is_connected)

    async def test_busy_parent_receives_refusal_without_start_permission(self):
        helper = self.helper()
        database, output = GateDatabase(leases=1), io.StringIO()
        with patch.object(helper, 'db', database), redirect_stdout(output):
            code = await helper.main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), {'status': 'refused', 'error_type': 'RuntimeError'})
        self.assertFalse(database.lock.locked())
        self.assertEqual(len(database.leases), 1)
        self.assertFalse(database.is_connected)
