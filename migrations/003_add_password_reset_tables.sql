-- Migration: Add password reset functionality tables
-- Created: Authentication Enhancements Feature

-- Password reset tokens table
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    used_at TIMESTAMP WITH TIME ZONE NULL,
    created_ip INET NULL
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_token_hash ON password_reset_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id_expires ON password_reset_tokens(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires_at ON password_reset_tokens(expires_at);

-- Rate limiting table for password reset attempts
CREATE TABLE IF NOT EXISTS reset_rate_limits (
    id SERIAL PRIMARY KEY,
    user_identifier VARCHAR(255) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    first_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Unique index for user identifier lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_reset_rate_limits_user_identifier ON reset_rate_limits(user_identifier);
CREATE INDEX IF NOT EXISTS idx_reset_rate_limits_first_attempt ON reset_rate_limits(first_attempt_at);

-- Enhanced users table for password history
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS password_history JSONB NULL,
ADD COLUMN IF NOT EXISTS last_password_change TIMESTAMP WITH TIME ZONE NULL;

-- Password reset audit log
CREATE TABLE IF NOT EXISTS password_reset_audit_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    user_identifier VARCHAR(255) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    success BOOLEAN NOT NULL,
    details JSONB NULL
);

-- Indexes for audit log queries
CREATE INDEX IF NOT EXISTS idx_password_reset_audit_log_timestamp ON password_reset_audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_password_reset_audit_log_user_identifier ON password_reset_audit_log(user_identifier);
CREATE INDEX IF NOT EXISTS idx_password_reset_audit_log_event_type ON password_reset_audit_log(event_type);