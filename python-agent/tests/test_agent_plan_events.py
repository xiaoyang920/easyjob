import unittest
from unittest.mock import AsyncMock, patch
from app.services import agent_events
from app.graph.staged_plan import ExecutionTask


class AgentPlanEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_plan_preserves_complete_instruction_without_changing_execution(self):
        label = '核实角色出处与原始发布资料，' * 25 + '最后核对纳兰嫣然的服饰与配色。'
        task = ExecutionTask(task_id='source', kind='search', actor='main', instruction=label, allow_web=True)
        update = {'plan': {'tasks': [task.model_dump()]}, 'stages': [['source']]}
        with patch.object(agent_events, 'publish_event', AsyncMock()) as publish:
            await agent_events.publish_route({}, 'retrieve', update)
        plan = next(c.args[0] for c in publish.await_args_list if c.args[0]['kind'] == 'plan')
        self.assertEqual(plan['tasks'][0]['label'], label)
        self.assertEqual(plan['tasks'][0]['id'], task.task_id)
        self.assertEqual(plan['tasks'][0]['stage'], 1)
        self.assertEqual(task.instruction, label)

    async def test_full_unicode_plan_and_memory_role_are_preserved(self):
        label = '图' * 3999 + '🙂'
        task = ExecutionTask(task_id='history', kind='search', actor='main', instruction=label, retrieval_target='memory')
        with patch.object(agent_events, 'publish_event', AsyncMock()) as publish:
            await agent_events.publish_route({}, 'retrieve', {'plan': {'tasks': [task.model_dump()]}, 'stages': [['history']]})
        plan = publish.await_args.args[0]
        self.assertEqual(plan['tasks'][0]['label'], label)
        self.assertEqual(plan['tasks'][0]['role'], 'memory')
