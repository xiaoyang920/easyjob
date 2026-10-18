-- Schema only; no production user data or credentials. CI applies versioned migrations after bootstrap.
SET FOREIGN_KEY_CHECKS=0;
CREATE TABLE `admin_operation_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `admin_user_id` bigint NOT NULL,
  `action` varchar(32) COLLATE utf8mb4_general_ci NOT NULL,
  `target_type` varchar(24) COLLATE utf8mb4_general_ci NOT NULL,
  `target_id` bigint NOT NULL,
  `before_value` varchar(128) COLLATE utf8mb4_general_ci NOT NULL,
  `after_value` varchar(128) COLLATE utf8mb4_general_ci NOT NULL,
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `reason` varchar(300) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `details_json` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_admin_log_time` (`created_at`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `admin_role_permission` (
  `role_id` int NOT NULL,
  `permission` varchar(40) COLLATE utf8mb4_general_ci NOT NULL,
  PRIMARY KEY (`role_id`,`permission`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `agent_background_job` (
  `job_id` char(64) COLLATE utf8mb4_general_ci NOT NULL,
  `kind` varchar(32) COLLATE utf8mb4_general_ci NOT NULL,
  `user_id` bigint NOT NULL,
  `conversation_id` bigint DEFAULT NULL,
  `payload` json NOT NULL,
  `status` varchar(16) COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'pending',
  `attempts` int NOT NULL DEFAULT '0',
  `available_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `lease_until` datetime(6) DEFAULT NULL,
  `lease_token` char(36) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `last_error` varchar(128) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`job_id`),
  KEY `idx_background_due` (`status`,`available_at`),
  KEY `idx_background_lease` (`status`,`lease_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `agent_execution_gate` (
  `gate_id` int NOT NULL,
  PRIMARY KEY (`gate_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `agent_execution_lease` (
  `ticket` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `user_id` bigint NOT NULL,
  `state` varchar(12) COLLATE utf8mb4_general_ci NOT NULL,
  `expires_at` datetime(6) NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`ticket`),
  KEY `idx_execution_expiry` (`expires_at`),
  KEY `idx_execution_user` (`user_id`,`state`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `agent_run` (
  `run_id` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `conversation_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `request_id` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `input_hash` char(64) COLLATE utf8mb4_general_ci NOT NULL,
  `execution_token` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_general_ci NOT NULL,
  `active_conversation_id` bigint GENERATED ALWAYS AS ((case when (`status` in (_utf8mb4'running',_utf8mb4'awaiting_approval')) then `conversation_id` else NULL end)) STORED,
  `deadline` datetime(6) NOT NULL,
  `draft_hash` char(64) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `draft_article_id` bigint DEFAULT NULL,
  `result_json` json DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `executor_lease_until` datetime(6) DEFAULT NULL,
  `recovery_count` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`run_id`),
  UNIQUE KEY `uq_agent_request` (`user_id`,`request_id`),
  UNIQUE KEY `uq_agent_active_conversation` (`active_conversation_id`),
  KEY `idx_agent_conversation` (`conversation_id`,`created_at`),
  KEY `idx_agent_created` (`created_at`,`run_id`),
  KEY `idx_agent_expiry` (`status`,`deadline`),
  KEY `idx_agent_terminal_retention` (`status`,`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `agent_run_event` (
  `event_id` bigint NOT NULL AUTO_INCREMENT,
  `run_id` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `node` varchar(64) COLLATE utf8mb4_general_ci NOT NULL,
  `status` varchar(24) COLLATE utf8mb4_general_ci NOT NULL,
  `duration_ms` bigint DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`event_id`),
  KEY `idx_agent_event_run` (`run_id`,`event_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `agent_schema_migration` (
  `version` varchar(100) COLLATE utf8mb4_general_ci NOT NULL,
  `checksum` char(64) COLLATE utf8mb4_general_ci NOT NULL,
  `applied_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `agent_stream_frame` (
  `event_id` bigint NOT NULL AUTO_INCREMENT,
  `run_id` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `execution_token` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `data` mediumtext COLLATE utf8mb4_general_ci NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`event_id`),
  KEY `idx_stream_run` (`run_id`,`execution_token`,`event_id`),
  KEY `idx_stream_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `agent_task_artifact` (
  `run_id` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `task_id` varchar(40) COLLATE utf8mb4_general_ci NOT NULL,
  `input_hash` char(64) COLLATE utf8mb4_general_ci NOT NULL,
  `result_json` json NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`run_id`,`task_id`),
  CONSTRAINT `fk_task_artifact_run` FOREIGN KEY (`run_id`) REFERENCES `agent_run` (`run_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `ai_conversation` (
  `conversation_id` bigint NOT NULL COMMENT '会话ID(雪花ID)',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `title` varchar(200) DEFAULT NULL COMMENT '会话标题(取第一条消息)',
  `message_count` int DEFAULT '0' COMMENT '消息数量',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `status` tinyint DEFAULT '1' COMMENT '状态: 1-正常 0-已删除',
  `summary` text COMMENT '滚动摘要（LLM压缩的早期对话精华）',
  `summary_tokens` int DEFAULT '0' COMMENT '当前摘要的token数',
  `summary_upto_msg_id` bigint DEFAULT NULL COMMENT '摘要覆盖到的最后一条消息ID',
  `total_tokens` int DEFAULT '0' COMMENT '累计消耗token数',
  `origin_article_id` bigint DEFAULT NULL,
  PRIMARY KEY (`conversation_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_ai_conv_origin` (`user_id`,`origin_article_id`,`status`,`update_time`,`conversation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI会话表';

CREATE TABLE `ai_message` (
  `message_id` bigint NOT NULL COMMENT '消息ID(雪花ID)',
  `conversation_id` bigint NOT NULL COMMENT '会话ID',
  `role` varchar(20) NOT NULL COMMENT '角色: user/assistant/system',
  `content` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '消息内容',
  `image_paths` json DEFAULT NULL COMMENT '图片路径列表(如["path1.jpg","path2.jpg"])',
  `token_count` int DEFAULT NULL COMMENT 'Token数量',
  `tool_calls` json DEFAULT NULL COMMENT '工具调用记录',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `article_cards` json DEFAULT NULL COMMENT '文章卡片数据(JSON数组)',
  `draft_article_id` bigint DEFAULT NULL COMMENT 'HITL 产生的草稿 article_id（引用 article_info.article_id），NULL 表示该消息无关联草稿',
  `citations` json DEFAULT NULL,
  PRIMARY KEY (`message_id`),
  KEY `idx_conversation_id` (`conversation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI消息表';

CREATE TABLE `article_index_outbox` (
  `job_id` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `article_id` bigint NOT NULL,
  `action` varchar(16) COLLATE utf8mb4_general_ci NOT NULL,
  `routing_key` varchar(100) COLLATE utf8mb4_general_ci NOT NULL,
  `status` varchar(16) COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'pending',
  `attempts` int NOT NULL DEFAULT '0',
  `available_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `lease_until` datetime(6) DEFAULT NULL,
  `lease_token` char(36) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `last_error` varchar(128) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`job_id`),
  KEY `idx_article_outbox_due` (`status`,`available_at`),
  KEY `idx_article_outbox_lease` (`status`,`lease_until`),
  KEY `idx_article_outbox_article` (`article_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `article_info` (
  `article_id` bigint NOT NULL COMMENT '文章ID',
  `user_id` bigint NOT NULL COMMENT '作者用户ID',
  `title` varchar(100) NOT NULL COMMENT '文章标题',
  `cover_image` varchar(500) DEFAULT NULL COMMENT '封面图片URL',
  `summary` varchar(500) DEFAULT NULL COMMENT '文章摘要',
  `content` longtext COMMENT '文章内容（富文本HTML或Markdown）',
  `content_type` tinyint DEFAULT '1' COMMENT '内容类型：1-富文本 2-Markdown',
  `category_id` bigint DEFAULT NULL COMMENT '分类ID',
  `tags` varchar(200) DEFAULT NULL COMMENT '标签（逗号分隔）',
  `view_count` int DEFAULT '0' COMMENT '浏览次数',
  `like_count` int DEFAULT '0' COMMENT '点赞数',
  `collect_count` int DEFAULT '0' COMMENT '收藏数',
  `comment_count` int DEFAULT '0' COMMENT '评论数',
  `share_count` int DEFAULT '0' COMMENT '分享数',
  `status` tinyint DEFAULT '0' COMMENT '状态：0-草稿 1-已发布 2-已下架 3-审核中',
  `is_top` tinyint DEFAULT '0' COMMENT '是否置顶：0-否 1-是',
  `is_essence` tinyint DEFAULT '0' COMMENT '是否精华：0-否 1-是',
  `is_original` tinyint DEFAULT '1' COMMENT '是否原创：0-否 1-是',
  `publish_time` datetime DEFAULT NULL COMMENT '发布时间',
  `create_time` datetime NOT NULL COMMENT '创建时间',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  `deleted` tinyint DEFAULT '0' COMMENT '删除标记：0-未删除 1-已删除',
  `required_level` int NOT NULL DEFAULT '0',
  `latest_revision_id` bigint NOT NULL DEFAULT '0',
  `published_revision_id` bigint NOT NULL DEFAULT '0',
  `data_source` varchar(16) NOT NULL DEFAULT 'business',
  PRIMARY KEY (`article_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_status` (`status`),
  KEY `idx_publish_time` (`publish_time`),
  KEY `idx_user_status` (`user_id`,`status`,`publish_time` DESC),
  KEY `idx_article_feed` (`status`,`deleted`,`publish_time`,`article_id`),
  KEY `idx_article_category_feed` (`status`,`deleted`,`category_id`,`publish_time`,`article_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文章信息表';

CREATE TABLE `article_read_receipt` (
  `article_id` bigint NOT NULL,
  `reader_hash` char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `read_day` date NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`article_id`,`reader_hash`,`read_day`),
  KEY `idx_read_receipt_day` (`read_day`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `article_review_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `article_id` bigint NOT NULL,
  `revision_id` bigint NOT NULL,
  `actor_id` bigint NOT NULL,
  `action` varchar(24) COLLATE utf8mb4_general_ci NOT NULL,
  `reason` varchar(1000) COLLATE utf8mb4_general_ci NOT NULL DEFAULT '',
  `content_hash` char(64) COLLATE utf8mb4_general_ci NOT NULL,
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `ix_article_review` (`article_id`,`id`),
  KEY `ix_revision_review` (`revision_id`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `article_revision` (
  `revision_id` bigint NOT NULL AUTO_INCREMENT,
  `article_id` bigint NOT NULL,
  `version_no` int NOT NULL,
  `author_id` bigint NOT NULL,
  `base_revision_id` bigint NOT NULL DEFAULT '0',
  `state` tinyint NOT NULL,
  `payload` json NOT NULL,
  `content_hash` char(64) COLLATE utf8mb4_general_ci NOT NULL,
  `review_reason` varchar(1000) COLLATE utf8mb4_general_ci NOT NULL DEFAULT '',
  `reviewer_id` bigint DEFAULT NULL,
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `submitted_at` datetime(3) DEFAULT NULL,
  `reviewed_at` datetime(3) DEFAULT NULL,
  `active_article_id` bigint GENERATED ALWAYS AS ((case when (`state` = 1) then `article_id` else NULL end)) STORED,
  PRIMARY KEY (`revision_id`),
  UNIQUE KEY `uk_article_version` (`article_id`,`version_no`),
  UNIQUE KEY `uk_pending_article` (`active_article_id`),
  KEY `ix_review_queue` (`state`,`submitted_at`,`revision_id`),
  KEY `ix_author_revision` (`author_id`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `article_tag` (
  `tag_id` bigint NOT NULL AUTO_INCREMENT COMMENT '标签ID',
  `tag_name` varchar(50) COLLATE utf8mb4_general_ci NOT NULL COMMENT '标签名称',
  `use_count` int DEFAULT '0' COMMENT '使用次数',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`tag_id`),
  UNIQUE KEY `tag_name` (`tag_name`),
  KEY `idx_use_count` (`use_count` DESC),
  KEY `idx_tag_name` (`tag_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='文章标签表';

CREATE TABLE `article_tag_relation` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '关联ID',
  `article_id` bigint NOT NULL COMMENT '文章ID',
  `tag_id` bigint NOT NULL COMMENT '标签ID',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_article_tag` (`article_id`,`tag_id`),
  KEY `idx_article_id` (`article_id`),
  KEY `idx_tag_id` (`tag_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='文章标签关联表';

CREATE TABLE `article_view_sync` (
  `article_id` bigint NOT NULL,
  `target_count` int NOT NULL,
  `attempts` int NOT NULL DEFAULT '0',
  `available_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `lease_token` char(36) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `lease_until` datetime(6) DEFAULT NULL,
  `last_error` varchar(100) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`article_id`),
  KEY `idx_article_view_sync_ready` (`available_at`,`lease_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `category` (
  `category_id` bigint NOT NULL COMMENT '分类ID',
  `category_name` varchar(50) NOT NULL COMMENT '分类名称',
  `parent_id` bigint DEFAULT '0' COMMENT '父分类ID，0表示顶级分类',
  `sort_order` int DEFAULT '0' COMMENT '排序权重',
  `description` varchar(200) DEFAULT NULL COMMENT '分类描述',
  `article_count` int DEFAULT '0' COMMENT '文章数量',
  `status` tinyint DEFAULT '1' COMMENT '状态：0禁用 1启用',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `version` bigint NOT NULL DEFAULT '0',
  `migrated_to` bigint DEFAULT NULL,
  PRIMARY KEY (`category_id`),
  UNIQUE KEY `uq_category_parent_name` (`parent_id`,`category_name`),
  KEY `idx_parent_id` (`parent_id`),
  KEY `idx_status` (`status`),
  KEY `idx_sort` (`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文章分类表';

CREATE TABLE `comment` (
  `comment_id` bigint NOT NULL COMMENT '评论ID（雪花算法）',
  `article_id` bigint NOT NULL COMMENT '文章ID',
  `article_user_id` bigint NOT NULL COMMENT '文章作者ID',
  `parent_id` bigint NOT NULL DEFAULT '0' COMMENT '父评论ID：0表示顶级评论，非0表示回复（指向顶级评论）',
  `content` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '评论内容',
  `img_path` varchar(150) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '评论配图URL',
  `user_id` bigint NOT NULL COMMENT '评论者ID',
  `user_nick_name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '评论者昵称（冗余）',
  `user_avatar` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '评论者头像（冗余）',
  `reply_user_id` bigint DEFAULT NULL COMMENT '被回复用户ID（回复二级评论时有值）',
  `reply_nick_name` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '被回复用户昵称（冗余）',
  `reply_avatar` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '被回复用户头像（冗余）',
  `top_type` tinyint NOT NULL DEFAULT '0' COMMENT '是否置顶：0否 1是',
  `status` tinyint NOT NULL DEFAULT '0' COMMENT '状态：0正常 1已删除 2审核中 3已折叠',
  `like_count` int NOT NULL DEFAULT '0' COMMENT '点赞数',
  `reply_count` int NOT NULL DEFAULT '0' COMMENT '回复数（仅顶级评论有效）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`comment_id`),
  KEY `idx_article_id_create_time` (`article_id`,`create_time` DESC),
  KEY `idx_article_id_like_count` (`article_id`,`like_count` DESC),
  KEY `idx_parent_id` (`parent_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_article_user_id` (`article_user_id`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文章评论表';

CREATE TABLE `conversation` (
  `conversation_id` bigint NOT NULL COMMENT '会话ID',
  `conversation_type` tinyint NOT NULL DEFAULT '1' COMMENT '会话类型：1=单聊，2=群聊',
  `group_name` varchar(100) DEFAULT NULL COMMENT '群名称（群聊时使用）',
  `group_avatar` varchar(255) DEFAULT NULL COMMENT '群头像（群聊时使用）',
  `creator_id` bigint NOT NULL COMMENT '创建者ID',
  `last_message_id` bigint DEFAULT NULL COMMENT '最后一条消息ID',
  `last_message_content` varchar(500) DEFAULT NULL COMMENT '最后一条消息内容（冗余字段，提高查询效率）',
  `last_message_time` datetime DEFAULT NULL COMMENT '最后消息时间',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`conversation_id`),
  KEY `idx_creator` (`creator_id`),
  KEY `idx_update_time` (`update_time` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='会话表';

CREATE TABLE `conversation_member` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `conversation_id` bigint NOT NULL COMMENT '会话ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `unread_count` int NOT NULL DEFAULT '0' COMMENT '未读消息数',
  `last_read_message_id` bigint DEFAULT NULL COMMENT '最后已读消息ID',
  `is_muted` tinyint NOT NULL DEFAULT '0' COMMENT '是否免打扰：0=否，1=是',
  `is_top` tinyint NOT NULL DEFAULT '0' COMMENT '是否置顶：0=否，1=是',
  `is_deleted` tinyint NOT NULL DEFAULT '0' COMMENT '是否删除会话：0=否，1=是',
  `join_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '加入时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_conversation_user` (`conversation_id`,`user_id`),
  KEY `idx_user_deleted` (`user_id`,`is_deleted`),
  KEY `idx_user_update` (`user_id`,`update_time` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='会话成员表';

CREATE TABLE `maintenance_cursor` (
  `kind` varchar(32) COLLATE utf8mb4_general_ci NOT NULL,
  `last_id` bigint NOT NULL DEFAULT '0',
  `last_key` varchar(32) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `scanned` bigint NOT NULL DEFAULT '0',
  `repaired` bigint NOT NULL DEFAULT '0',
  `next_at` datetime(6) NOT NULL,
  `lease_until` datetime(6) DEFAULT NULL,
  `lease_token` char(36) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `last_error` varchar(64) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `last_finished_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`kind`),
  KEY `ix_maintenance_due` (`next_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `message` (
  `message_id` bigint NOT NULL COMMENT '消息ID',
  `conversation_id` bigint NOT NULL COMMENT '会话ID',
  `sender_id` bigint NOT NULL COMMENT '发送者ID',
  `message_type` tinyint NOT NULL DEFAULT '1' COMMENT '消息类型：1=文本，2=图片，3=语音，4=视频，5=文件',
  `content` text NOT NULL COMMENT '消息内容',
  `extra_data` json DEFAULT NULL COMMENT '扩展数据（图片尺寸、文件大小等）',
  `reply_to_message_id` bigint DEFAULT NULL COMMENT '回复的消息ID',
  `status` tinyint NOT NULL DEFAULT '0' COMMENT '消息状态：0=正常，1=撤回，2=删除',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `client_message_id` varchar(64) DEFAULT NULL,
  PRIMARY KEY (`message_id`),
  UNIQUE KEY `uq_message_client` (`sender_id`,`client_message_id`),
  KEY `idx_conversation_time` (`conversation_id`,`create_time` DESC),
  KEY `idx_sender` (`sender_id`),
  KEY `idx_reply` (`reply_to_message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='消息表';

CREATE TABLE `notification` (
  `notification_id` bigint NOT NULL COMMENT '雪花ID',
  `user_id` bigint NOT NULL COMMENT '接收者',
  `sender_id` bigint NOT NULL COMMENT '触发者',
  `sender_nickname` varchar(64) DEFAULT NULL COMMENT '触发者昵称（冗余快照）',
  `sender_avatar` varchar(255) DEFAULT NULL COMMENT '触发者头像（冗余快照）',
  `type` tinyint NOT NULL COMMENT '1评论/回复 2点赞 3收藏 4关注 5系统',
  `article_id` bigint DEFAULT NULL COMMENT '关联文章ID（关注类为 null）',
  `article_title` varchar(200) DEFAULT NULL COMMENT '文章标题（冗余快照）',
  `target_id` bigint DEFAULT NULL COMMENT '目标对象ID（评论ID/文章ID/被关注者ID）',
  `target_preview` varchar(200) DEFAULT NULL COMMENT '目标内容预览（评论前100字，非评论类为 null）',
  `content` varchar(100) DEFAULT NULL COMMENT '动词文案，如 "赞了你的评论"',
  `is_read` tinyint DEFAULT '0' COMMENT '0未读 1已读',
  `create_time` datetime NOT NULL,
  PRIMARY KEY (`notification_id`),
  KEY `idx_user_read` (`user_id`,`is_read`,`create_time` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='通知表';

CREATE TABLE `reading_level_rule` (
  `level` int NOT NULL,
  `min_seconds` bigint NOT NULL,
  PRIMARY KEY (`level`),
  UNIQUE KEY `uq_reading_threshold` (`min_seconds`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `reading_session` (
  `session_id` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `user_id` bigint NOT NULL,
  `article_id` bigint NOT NULL,
  `last_sequence` bigint NOT NULL DEFAULT '0',
  `last_heartbeat` datetime(3) NOT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  `credited_millis` bigint NOT NULL DEFAULT '0',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`session_id`),
  KEY `ix_reading_owner` (`user_id`,`created_at`),
  KEY `ix_reading_cleanup` (`last_heartbeat`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `recommendation_feedback` (
  `user_id` bigint NOT NULL,
  `article_id` bigint NOT NULL,
  `target_author_id` bigint NOT NULL,
  `kind` varchar(20) COLLATE utf8mb4_general_ci NOT NULL,
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`user_id`,`article_id`),
  KEY `ix_feedback_user_kind` (`user_id`,`kind`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `user_action` (
  `action_id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增ID',
  `article_id` bigint NOT NULL COMMENT '视频id',
  `article_user_id` bigint NOT NULL DEFAULT '0' COMMENT '视频用户ID',
  `comment_id` bigint NOT NULL DEFAULT '0' COMMENT '评论id',
  `action_type` tinyint(1) NOT NULL COMMENT '0:评论喜欢点赞 1:讨厌评论 2;文章点赞 3:文章收藏 4:文章投币',
  `action_count` int NOT NULL COMMENT '数量',
  `user_id` bigint NOT NULL COMMENT '用户id',
  `action_time` datetime NOT NULL COMMENT '操作时间',
  PRIMARY KEY (`action_id`) USING BTREE,
  UNIQUE KEY `idx_key_video_comment_type_user` (`article_id`,`comment_id`,`action_type`,`user_id`) USING BTREE,
  KEY `idx_video_id` (`article_id`) USING BTREE,
  KEY `idx_user_id` (`user_id`) USING BTREE,
  KEY `idx_type` (`action_type`) USING BTREE,
  KEY `idx_action_time` (`action_time`) USING BTREE,
  KEY `idx_user_action_read` (`user_id`,`article_id`,`action_type`,`action_time`),
  KEY `idx_user_action_recent` (`user_id`,`action_time`,`article_id`,`action_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='用户行为点赞，评论';

CREATE TABLE `user_focus` (
  `user_id` bigint NOT NULL COMMENT '用户id',
  `focus_user_id` bigint NOT NULL COMMENT '被关注用户id',
  `focus_time` datetime DEFAULT NULL,
  PRIMARY KEY (`user_id`,`focus_user_id`) USING BTREE,
  KEY `idx_user_focus` (`user_id`,`focus_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;

CREATE TABLE `user_info` (
  `user_id` bigint NOT NULL COMMENT '用户id',
  `nick_name` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '昵称',
  `avatar` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '头像',
  `email` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '邮箱',
  `password` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '密码',
  `sex` tinyint(1) DEFAULT NULL COMMENT '0.女 1.男 2.未知',
  `birthday` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '出生日期',
  `person_introduction` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '个人简介',
  `join_time` datetime NOT NULL COMMENT '加入日期',
  `last_login_time` datetime DEFAULT NULL COMMENT '最后登录时间',
  `last_login_ip` varchar(15) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '最后登录ip',
  `status` tinyint(1) NOT NULL DEFAULT '1' COMMENT '0.禁用 2.正常',
  `article_count` int DEFAULT '0' COMMENT '文章数',
  `follower_count` int DEFAULT '0' COMMENT '粉丝数',
  `following_count` int DEFAULT '0' COMMENT '关注数',
  `school` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '学校',
  `notice_info` varchar(300) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '空间公告',
  `total_coin_count` int NOT NULL COMMENT '硬币总数量',
  `current_coin_count` int NOT NULL COMMENT '当前硬币数量',
  `theme` tinyint(1) NOT NULL DEFAULT '1' COMMENT '主题',
  `role` tinyint DEFAULT '1' COMMENT '角色：1普通用户 2作者 3管理员',
  `auth_version` bigint NOT NULL DEFAULT '0',
  `data_source` varchar(16) NOT NULL DEFAULT 'business',
  PRIMARY KEY (`user_id`) USING BTREE,
  UNIQUE KEY `idx_key_email` (`email`) USING BTREE,
  UNIQUE KEY `idx_nick_name` (`nick_name`) USING BTREE,
  KEY `idx_email` (`email`),
  KEY `idx_role_status` (`role`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='用户信息';

CREATE TABLE `user_memory` (
  `memory_id` bigint NOT NULL COMMENT '雪花ID',
  `user_id` bigint NOT NULL,
  `content` text NOT NULL COMMENT '记忆内容（仅事件记忆，语义事实写 user_profile）',
  `importance` float DEFAULT '0.5' COMMENT '重要性 0-1, 用于遗忘策略',
  `access_count` int DEFAULT '0' COMMENT '被召回次数',
  `source_conversation_id` bigint DEFAULT NULL COMMENT '来源会话ID',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `memory_type` varchar(16) NOT NULL DEFAULT 'event',
  `scope` varchar(16) NOT NULL DEFAULT 'user',
  `scope_conversation_id` bigint DEFAULT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'active',
  `memory_key` varchar(64) DEFAULT NULL,
  `source_quote` varchar(1000) DEFAULT NULL,
  PRIMARY KEY (`memory_id`),
  KEY `idx_user_importance` (`user_id`,`importance` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户事件记忆（Episodic Memory）';

CREATE TABLE `user_memory_change` (
  `run_id` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  `user_id` bigint NOT NULL,
  `conversation_id` bigint NOT NULL,
  `change_hash` char(64) COLLATE utf8mb4_general_ci NOT NULL,
  `result_json` json NOT NULL,
  `index_synced` tinyint NOT NULL DEFAULT '0',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `user_profile` (
  `user_id` bigint NOT NULL,
  `tech_stack` json DEFAULT NULL COMMENT '技术栈偏好 ["Java","Spring Boot","Python"]',
  `interests` json DEFAULT NULL COMMENT '兴趣领域 ["后端开发","微服务","AI"]',
  `experience` varchar(20) DEFAULT 'unknown' COMMENT 'junior|mid|senior',
  `preferences` json DEFAULT NULL COMMENT '对话偏好 {"style":"practical","detail":"high"}',
  `summary` text COMMENT 'LLM 生成的综合画像摘要',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户语义画像';

CREATE TABLE `user_reading_daily` (
  `user_id` bigint NOT NULL,
  `read_day` date NOT NULL,
  `total_millis` bigint NOT NULL DEFAULT '0',
  PRIMARY KEY (`user_id`,`read_day`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `user_reading_progress` (
  `user_id` bigint NOT NULL,
  `total_millis` bigint NOT NULL DEFAULT '0',
  `earned_level` int NOT NULL DEFAULT '0',
  `active_session` char(36) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `user_tag_preference` (
  `user_id` bigint NOT NULL,
  `tag_id` bigint NOT NULL,
  `score` float NOT NULL DEFAULT '0',
  `update_time` datetime NOT NULL,
  PRIMARY KEY (`user_id`,`tag_id`),
  KEY `idx_user_score` (`user_id`,`score` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户标签偏好表';
SET FOREIGN_KEY_CHECKS=1;
