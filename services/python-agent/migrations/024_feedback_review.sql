ALTER TABLE agent_answer_feedback ADD COLUMN review_state VARCHAR(16) NOT NULL DEFAULT 'pending';
ALTER TABLE agent_answer_feedback ADD COLUMN review_note VARCHAR(1000) NOT NULL DEFAULT '';
ALTER TABLE agent_answer_feedback ADD COLUMN review_version BIGINT NOT NULL DEFAULT 0;
ALTER TABLE agent_answer_feedback ADD COLUMN handled_by BIGINT NULL;
ALTER TABLE agent_answer_feedback ADD COLUMN handled_at DATETIME(6) NULL;
ALTER TABLE agent_answer_feedback ADD COLUMN feedback_generation CHAR(36) NOT NULL DEFAULT '';
UPDATE agent_answer_feedback SET feedback_generation=UUID() WHERE feedback_generation='';
CREATE TABLE IF NOT EXISTS agent_feedback_review_log (
 command_id CHAR(36) PRIMARY KEY,
 run_id CHAR(36) NOT NULL,
 user_id BIGINT NOT NULL,
 actor_id BIGINT NOT NULL,
 from_state VARCHAR(16) NOT NULL,
 to_state VARCHAR(16) NOT NULL,
 note VARCHAR(1000) NOT NULL DEFAULT '',
 expected_version BIGINT NOT NULL,
 feedback_generation CHAR(36) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 KEY ix_feedback_review_run(run_id,user_id,created_at)
);
