-- Migration: Fix DM relay ID fields to support 64-bit Telegram IDs
-- Date: 2026-01-21
-- Description: Change group_id, from_user_id, to_user_id in dm_relays and read_by in dm_read_receipts from INTEGER to BIGINT

-- Alter dm_relays table
ALTER TABLE dm_relays 
    ALTER COLUMN group_id TYPE BIGINT,
    ALTER COLUMN from_user_id TYPE BIGINT,
    ALTER COLUMN to_user_id TYPE BIGINT;

-- Alter dm_read_receipts table
ALTER TABLE dm_read_receipts 
    ALTER COLUMN read_by TYPE BIGINT;

-- No data migration needed as we're only expanding the integer range
-- All existing INTEGER values are valid BIGINT values
