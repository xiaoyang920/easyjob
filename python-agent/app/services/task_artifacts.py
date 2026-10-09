"""Same-run read-only artifacts; all mutations are fenced by the live executor."""
import json
from fastapi import HTTPException
from app.clients.mysql_client import db
from app.services.run_repository import digest
from app.services.evidence_verifier import verify_public_evidence
from app.skills.registry import skill_registry


def task_fingerprint(context):
    payload = {key: value for key, value in context.items()
               if key not in ('execution_token', 'run_id')}
    payload['artifact_version'] = 1
    payload['skills'] = {name: skill_registry.get_content(name)
                         for name in context.get('required_skills', [])}
    return digest(payload)


class TaskArtifacts:
    def __init__(self, database=db, verifier=verify_public_evidence):
        self.db, self.verifier = database, verifier

    async def load(self, context, fingerprint):
        row = await self.db.fetch_one('''SELECT a.input_hash,a.result_json FROM agent_task_artifact a
            JOIN agent_run r ON r.run_id=a.run_id
            WHERE a.run_id=:rid AND a.task_id=:tid AND r.user_id=:uid''',
            {'rid': context['run_id'], 'tid': context['task_id'], 'uid': context['user_id']})
        if not row or row._mapping['input_hash'] != fingerprint:
            return None
        raw = row._mapping['result_json']
        result = json.loads(raw) if isinstance(raw, str) else raw
        task = context['current_task']
        if (result.get('status') != 'succeeded' or result.get('task_id') != task['task_id']
                or result.get('actor') != 'subagent' or result.get('kind') != task['kind']):
            return None
        try:
            await self.verifier(result.get('citations', []))
        except ValueError:
            return None  # Changed/deleted sources must be retrieved again.
        return result

    async def save(self, context, fingerprint, result, token):
        if context['current_task']['kind'] not in ('search', 'analysis'):
            raise PermissionError('只读子任务才能保存恢复产物')
        async with self.db.transaction():
            owner = await self.db.fetch_val('''SELECT run_id FROM agent_run
                WHERE run_id=:rid AND user_id=:uid AND execution_token=:token AND status='running'
                  AND deadline>UTC_TIMESTAMP(6) AND executor_lease_until>UTC_TIMESTAMP(6) FOR UPDATE''',
                {'rid': context['run_id'], 'uid': context['user_id'], 'token': token})
            if not owner:
                raise HTTPException(409, '子任务执行代次已失效')
            await self.db.execute('''INSERT INTO agent_task_artifact(run_id,task_id,input_hash,result_json,updated_at)
                VALUES(:rid,:tid,:hash,:result,UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE input_hash=VALUES(input_hash),result_json=VALUES(result_json),updated_at=VALUES(updated_at)''',
                {'rid': context['run_id'], 'tid': context['task_id'], 'hash': fingerprint,
                 'result': json.dumps(result, ensure_ascii=False)})


task_artifacts = TaskArtifacts()
