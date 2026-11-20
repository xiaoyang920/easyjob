CREATE TABLE IF NOT EXISTS article_comment_anchor (
    comment_id BIGINT NOT NULL,
    quote_text TEXT NOT NULL,
    quote_prefix VARCHAR(48) NOT NULL,
    quote_suffix VARCHAR(48) NOT NULL,
    start_offset INT NOT NULL,
    end_offset INT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(comment_id),
    CONSTRAINT fk_comment_anchor_comment FOREIGN KEY(comment_id) REFERENCES comment(comment_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
