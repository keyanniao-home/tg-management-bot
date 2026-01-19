-- 每日推送配置表迁移脚本
-- 创建 digest_config 表

CREATE TABLE IF NOT EXISTS digest_config (
    id SERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL UNIQUE,
    is_enabled BOOLEAN DEFAULT TRUE,
    push_hour INTEGER DEFAULT 9 CHECK (push_hour >= 0 AND push_hour <= 23),
    push_minute INTEGER DEFAULT 0 CHECK (push_minute >= 0 AND push_minute <= 59),
    include_summary BOOLEAN DEFAULT TRUE,
    include_stats BOOLEAN DEFAULT TRUE,
    include_hot_topics BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_digest_config_group_id ON digest_config(group_id);

-- 添加注释
COMMENT ON TABLE digest_config IS '每日推送配置表';
COMMENT ON COLUMN digest_config.group_id IS '群组ID';
COMMENT ON COLUMN digest_config.is_enabled IS '是否启用推送';
COMMENT ON COLUMN digest_config.push_hour IS '推送小时(0-23)';
COMMENT ON COLUMN digest_config.push_minute IS '推送分钟(0-59)';
COMMENT ON COLUMN digest_config.include_summary IS '包含消息总结';
COMMENT ON COLUMN digest_config.include_stats IS '包含活跃统计';
COMMENT ON COLUMN digest_config.include_hot_topics IS '包含热门话题';
