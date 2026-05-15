-- Migration: Add embedding cache columns to existing jobs table
-- Run this in Supabase SQL Editor (service_role key)
-- Date: 2025-05-09

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS description_hash TEXT DEFAULT NULL,
ADD COLUMN IF NOT EXISTS description_embedding JSONB DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_desc_hash ON jobs(user_id, description_hash);
