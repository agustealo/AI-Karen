-- Migrated from database/migrations/004_chat_runtime_control_plane.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration: Add Chat Runtime Control Plane Tables
-- Description: Adds tables for runtime state management, maintenance windows, notifications, dependency health, and audit events
-- Created: 2026-04-09

-- Create system_runtime_state table
CREATE TABLE IF NOT EXISTS system_runtime_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    current_mode VARCHAR(50) NOT NULL DEFAULT 'normal' CHECK (current_mode IN ('normal', 'degraded', 'maintenance', 'emergency_fallback')),
    normal_ready BOOLEAN NOT NULL DEFAULT FALSE,
    degraded_ready BOOLEAN NOT NULL DEFAULT FALSE,
    maintenance_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    maintenance_reason TEXT,
    estimated_completion_time TIMESTAMP WITH TIME ZONE,
    last_transition_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_transition_reason TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create maintenance_windows table
CREATE TABLE IF NOT EXISTS maintenance_windows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    message TEXT,
    reason TEXT,
    estimated_completion_time TIMESTAMP WITH TIME ZONE,
    notifications_supported BOOLEAN NOT NULL DEFAULT TRUE,
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    auto_end_policy VARCHAR(100) DEFAULT 'manual',
    created_by UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
    updated_by UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create maintenance_notification_requests table
CREATE TABLE IF NOT EXISTS maintenance_notification_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    maintenance_window_id UUID NOT NULL REFERENCES maintenance_windows(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth_users(user_id) ON DELETE CASCADE,
    session_id VARCHAR(255),
    notification_channel VARCHAR(50) DEFAULT 'in_app',
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'pending', 'completed', 'cancelled')),
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    dispatched_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE
);

-- Create runtime_dependency_health table
CREATE TABLE IF NOT EXISTS runtime_dependency_health (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dependency_name VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (status IN ('healthy', 'unhealthy', 'unknown')),
    reason TEXT,
    checked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    consecutive_successes INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    last_failure_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create chat_runtime_events table
CREATE TABLE IF NOT EXISTS chat_runtime_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(100) NOT NULL,
    mode VARCHAR(50) CHECK (mode IN ('normal', 'degraded', 'maintenance', 'emergency_fallback')),
    user_id UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
    session_id VARCHAR(255),
    conversation_id UUID,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_runtime_state_mode ON system_runtime_state(current_mode);
CREATE INDEX IF NOT EXISTS idx_runtime_state_updated ON system_runtime_state(updated_at);

CREATE INDEX IF NOT EXISTS idx_maintenance_enabled ON maintenance_windows(enabled);
CREATE INDEX IF NOT EXISTS idx_maintenance_started ON maintenance_windows(started_at);
CREATE INDEX IF NOT EXISTS idx_maintenance_created ON maintenance_windows(created_at);

CREATE INDEX IF NOT EXISTS idx_notification_maintenance ON maintenance_notification_requests(maintenance_window_id);
CREATE INDEX IF NOT EXISTS idx_notification_user ON maintenance_notification_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_session ON maintenance_notification_requests(session_id);
CREATE INDEX IF NOT EXISTS idx_notification_status ON maintenance_notification_requests(status);

CREATE INDEX IF NOT EXISTS idx_dependency_name ON runtime_dependency_health(dependency_name);
CREATE INDEX IF NOT EXISTS idx_dependency_status ON runtime_dependency_health(status);
CREATE INDEX IF NOT EXISTS idx_dependency_checked ON runtime_dependency_health(checked_at);

CREATE INDEX IF NOT EXISTS idx_runtime_event_type ON chat_runtime_events(event_type);
CREATE INDEX IF NOT EXISTS idx_runtime_event_user ON chat_runtime_events(user_id);
CREATE INDEX IF NOT EXISTS idx_runtime_event_session ON chat_runtime_events(session_id);
CREATE INDEX IF NOT EXISTS idx_runtime_event_created ON chat_runtime_events(created_at);

-- Insert initial runtime state
INSERT INTO system_runtime_state (current_mode, normal_ready, degraded_ready, maintenance_enabled)
VALUES ('normal', true, true, false)
ON CONFLICT DO NOTHING;