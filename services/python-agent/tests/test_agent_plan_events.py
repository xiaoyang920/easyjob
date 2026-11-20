import unittest
from unittest.mock import AsyncMock, patch
from app.services import agent_events
from app.graph.staged_plan import ExecutionTask


class AgentPlanEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_result_notes_use_outcome_and_counts_without_raw_content(self):
        outcomes = [
            ({'status': 'succeeded', 'kind': 'search', 'citations': [{'excerpt': 'private'}]},
             '取得 1 条候选来源，等待后续判断。'),
            ({'status': 'succeeded', 'result_reads': []}, '在指定范围内没有读到匹配片段。'),
            ({'status': 'insufficient_evidence'}, '这次没有找到可用的候选资料。'),
            ({'status': 'tool_error'}, '工具未能返回可用结果。'),
            ({'status': 'blocked'}, '依赖任务未成功，这一步没有执行。'),
        ]
        with patch.object(agent_events, 'publish_event', AsyncMock()) as publish:
            for result, expected in outcomes:
                await agent_events.publish_task_result('source', {**result, 'result': 'private'})
                self.assertEqual(publish.await_args.args[0], {
                    'kind': 'result', 'id': 'source/result', 'taskId': 'source', 'text': expected})

    async def test_route_prefers_contextual_note_and_falls_back_after_tool_work(self):
        state = {'main_round': 1, 'task_results': {'source': {}}}
        with patch.object(agent_events, 'publish_event', AsyncMock()) as publish:
            await agent_events.publish_route(state, 'answer', progress_note='已有候选资料，接下来按来源整理。')
            self.assertEqual(publish.await_args.args[0]['text'], '已有候选资料，接下来按来源整理。')
            await agent_events.publish_route(state, 'answer')
            self.assertEqual(publish.await_args.args[0]['text'], '我会根据已有结果整理回答。')

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
