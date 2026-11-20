"""Protocol fixtures only; persistence arbitration has separate repository tests."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import hashlib

RUN_ID = "11111111-1111-4111-8111-111111111111"
HASH = "a" * 64
SERVICE_KEY = "offline-service-key-32-bytes-long!!"


def article_chunk(aid="42", index=0, html="<p>current public evidence</p>", content="current public evidence", title="RAG", **extra):
    fingerprint = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return {"article_id": str(aid), "chunk_index": index, "content": content, "title": title,
            "source_hash": fingerprint, "chunker_version": "html-dom-v1",
            "chunk_id": f"{aid}_html-dom-v1_{fingerprint}_{index}", "section_path": [title], **extra}


def repository():
    run = {"run_id": RUN_ID, "conversation_id": 11, "user_id": 7,
           "execution_token": "executor", "status": "running", "draft_article_id": None}
    async def settle(cid, uid, rid, token, status, result, append=None):
        if append:
            await append()
        return result
    return SimpleNamespace(find_request=AsyncMock(return_value=None),
                           create=AsyncMock(return_value=(run, True)), get=AsyncMock(return_value=run),
                           claim_resume=AsyncMock(return_value=run), settle=AsyncMock(side_effect=settle),
                           fail=AsyncMock(), assert_executor=AsyncMock(), bind_admission=AsyncMock(), event=AsyncMock())
