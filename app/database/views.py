"""
数据库视图定义
用于创建PostgreSQL的VIEW或MATERIALIZED VIEW
"""

# 创建消息统计视图的SQL
CREATE_MESSAGE_STATS_VIEW = """
CREATE OR REPLACE VIEW message_stats AS
SELECT
    gm.group_id,
    gm.user_id,
    gm.username,
    gm.full_name,
    COUNT(m.id) as message_count,
    MAX(m.created_at) as last_message_at
FROM group_members gm
LEFT JOIN messages m ON gm.id = m.member_id AND m.is_deleted = false
WHERE gm.is_active = true
GROUP BY gm.group_id, gm.user_id, gm.username, gm.full_name;
"""

# 创建物化视图（性能更好，但需要手动刷新）
CREATE_MESSAGE_STATS_MATERIALIZED_VIEW = """
CREATE MATERIALIZED VIEW IF NOT EXISTS message_stats_materialized AS
SELECT
    gm.group_id,
    gm.user_id,
    gm.username,
    gm.full_name,
    COUNT(m.id) as message_count,
    MAX(m.created_at) as last_message_at
FROM group_members gm
LEFT JOIN messages m ON gm.id = m.member_id AND m.is_deleted = false
WHERE gm.is_active = true
GROUP BY gm.group_id, gm.user_id, gm.username, gm.full_name;

CREATE UNIQUE INDEX IF NOT EXISTS idx_message_stats_user
ON message_stats_materialized(group_id, user_id);
"""

# 刷新物化视图
REFRESH_MESSAGE_STATS_MATERIALIZED_VIEW = """
REFRESH MATERIALIZED VIEW CONCURRENTLY message_stats_materialized;
"""

# 按天数查询发言统计的SQL（用户和频道都在 group_members 表）
QUERY_MESSAGE_STATS_BY_DAYS = """
SELECT
    gm.user_id,
    gm.username,
    gm.full_name,
    COUNT(m.id) as message_count,
    MAX(m.created_at) as last_message_at
FROM group_members gm
LEFT JOIN messages m
    ON gm.id = m.member_id
    AND m.is_deleted = false
    AND m.created_at >= NOW() - :days * INTERVAL '1 day'
WHERE gm.group_id = :group_id
    AND gm.is_active = true
GROUP BY gm.user_id, gm.username, gm.full_name
ORDER BY message_count DESC
LIMIT :limit OFFSET :offset;
"""

# 查询指定天数内未发言用户（排除频道）
QUERY_INACTIVE_USERS = """
SELECT
    gm.user_id,
    gm.username,
    gm.full_name,
    gm.last_message_at
FROM group_members gm
WHERE gm.group_id = :group_id
    AND gm.is_active = true
    AND gm.user_id > 0
    AND (gm.last_message_at IS NULL
         OR gm.last_message_at < NOW() - :days * INTERVAL '1 day')
ORDER BY gm.last_message_at ASC NULLS FIRST;
"""

# 查询频道是否活跃（指定天数内是否有发言）
QUERY_CHANNEL_ACTIVE = """
SELECT
    gm.user_id as channel_id,
    gm.last_message_at,
    CASE
        WHEN gm.last_message_at >= NOW() - :days * INTERVAL '1 day' THEN true
        ELSE false
    END as is_active
FROM group_members gm
WHERE gm.group_id = :group_id
    AND gm.user_id = :channel_id
    AND gm.is_active = true;
"""

