ALTER TABLE user_info ADD COLUMN data_source VARCHAR(16) NOT NULL DEFAULT 'business';
ALTER TABLE article_info ADD COLUMN data_source VARCHAR(16) NOT NULL DEFAULT 'business';
ALTER TABLE category ADD COLUMN version BIGINT NOT NULL DEFAULT 0;
ALTER TABLE category ADD COLUMN migrated_to BIGINT NULL;
UPDATE user_info SET data_source='evaluation' WHERE email='rag-eval-v1@sample.invalid' AND nick_name='RAG评测样例';
UPDATE article_info a JOIN user_info u ON u.user_id=a.user_id SET a.data_source='evaluation' WHERE u.email='rag-eval-v1@sample.invalid' AND u.nick_name='RAG评测样例' AND u.data_source='evaluation';
