CREATE TABLE IF NOT EXISTS agent_task_artifact (
 run_id CHAR(36) NOT NULL,
 task_id VARCHAR(40) NOT NULL,
 input_hash CHAR(64) NOT NULL,
 result_json JSON NOT NULL,
 updated_at DATETIME(6) NOT NULL,
 PRIMARY KEY(run_id,task_id),
 CONSTRAINT fk_task_artifact_run FOREIGN KEY(run_id) REFERENCES agent_run(run_id) ON DELETE CASCADE
) ENGINE=InnoDB;
ALTER TABLE agent_run ADD COLUMN recovery_count INT NOT NULL DEFAULT 0;
