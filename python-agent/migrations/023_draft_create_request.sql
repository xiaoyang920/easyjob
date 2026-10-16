ALTER TABLE article_revision ADD COLUMN client_request_id CHAR(36) NULL;
CREATE UNIQUE INDEX uq_revision_create_request ON article_revision(author_id,client_request_id);
