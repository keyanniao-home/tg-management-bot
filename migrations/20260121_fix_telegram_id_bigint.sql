-- Migration: Fix all tables to support 64-bit Telegram IDs
-- Date: 2026-01-21
-- Description: Convert all Telegram ID fields from INTEGER to BIGINT
-- Affected tables: dm_relays, dm_read_receipts, resources, resource_tags, resource_edits

-- ============================================================
-- DM 相关表
-- ============================================================

-- Fix dm_relays table
ALTER TABLE dm_relays 
    ALTER COLUMN from_user_id TYPE BIGINT,
    ALTER COLUMN to_user_id TYPE BIGINT;

-- Fix dm_read_receipts table
ALTER TABLE dm_read_receipts 
    ALTER COLUMN read_by TYPE BIGINT;

-- ============================================================
-- 资源相关表
-- ============================================================

-- Fix resources table
ALTER TABLE resources 
    ALTER COLUMN uploader_id TYPE BIGINT,
    ALTER COLUMN message_thread_id TYPE BIGINT;

-- Fix resource_tags table
ALTER TABLE resource_tags 
    ALTER COLUMN added_by TYPE BIGINT;

-- Fix resource_edits table
ALTER TABLE resource_edits 
    ALTER COLUMN editor_id TYPE BIGINT;

-- ============================================================
-- 说明
-- ============================================================
-- 不需要数据迁移，只是扩展整数范围（32位 → 64位）
-- 所有现有的 INTEGER 值都是有效的 BIGINT 值
-- group_id 字段已经是 BIGINT，无需修改
