"""One eligibility rule for enqueue and locked deletion; active runs never expire here."""
from app.config import settings

EXPIRED_CHECKPOINT_SQL = """r.status IN ('succeeded','failed','cancelled','expired')
    AND r.updated_at<TIMESTAMPADD(DAY,
        -IF(r.status='succeeded',:success_days,:failure_days),UTC_TIMESTAMP(6))"""

# A cleanup skipped because a run resumed must not suppress cleanup after that
# run ends again. Deduplicate per terminal generation, not permanently per run.
CHECKPOINT_CLEANUP_KEY_SQL = "CONCAT('checkpoint-cleanup:',r.run_id,':',DATE_FORMAT(r.updated_at,'%Y%m%d%H%i%s%f'))"


def retention_parameters():
    return {'success_days': settings.CHECKPOINT_SUCCESS_RETENTION_DAYS,
            'failure_days': settings.CHECKPOINT_RETENTION_DAYS}
