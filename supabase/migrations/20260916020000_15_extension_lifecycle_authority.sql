-- Canonical extension/plugin lifecycle persistence.
-- Forward-only: establishes the tables already represented by SQLAlchemy models
-- and adds the durable lifecycle fields consumed by PluginLifecycleManager.

CREATE TABLE IF NOT EXISTS public.extension_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    version VARCHAR(50) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    author VARCHAR(100),
    license VARCHAR(50),
    category VARCHAR(50),
    tags TEXT[],
    api_version VARCHAR(20) DEFAULT '1.0',
    kari_min_version VARCHAR(20) DEFAULT '0.4.0',
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    dependencies JSONB NOT NULL DEFAULT '{}'::jsonb,
    permissions JSONB NOT NULL DEFAULT '{}'::jsonb,
    resources JSONB NOT NULL DEFAULT '{}'::jsonb,
    ui_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    api_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    background_tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
    marketplace_info JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(50) DEFAULT 'inactive',
    lifecycle_state VARCHAR(32) NOT NULL DEFAULT 'available',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    installed_at TIMESTAMPTZ,
    install_path VARCHAR(500),
    directory_path VARCHAR(500),
    is_validated BOOLEAN NOT NULL DEFAULT FALSE,
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    loaded_at TIMESTAMPTZ,
    last_error_at TIMESTAMPTZ,
    error_message TEXT,
    error_stack_trace TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    load_time_ms INTEGER,
    memory_usage_mb INTEGER,
    cpu_usage_percent INTEGER
);

ALTER TABLE public.extension_registry
    ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(32) NOT NULL DEFAULT 'available',
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS installed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS install_path VARCHAR(500);

CREATE INDEX IF NOT EXISTS idx_extension_name_version
    ON public.extension_registry(name, version);
CREATE INDEX IF NOT EXISTS idx_extension_category_status
    ON public.extension_registry(category, status);
CREATE INDEX IF NOT EXISTS idx_extension_status_created
    ON public.extension_registry(status, created_at);
CREATE INDEX IF NOT EXISTS idx_extension_lifecycle_enabled
    ON public.extension_registry(lifecycle_state, enabled);
CREATE INDEX IF NOT EXISTS idx_extension_author
    ON public.extension_registry(author);

CREATE TABLE IF NOT EXISTS public.extension_installation_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extension_id UUID NOT NULL REFERENCES public.extension_registry(id) ON DELETE CASCADE,
    action VARCHAR(20) NOT NULL,
    version_from VARCHAR(50),
    version_to VARCHAR(50) NOT NULL,
    performed_by VARCHAR(100),
    reason TEXT,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_history_extension_action
    ON public.extension_installation_history(extension_id, action);
CREATE INDEX IF NOT EXISTS idx_history_performed_at
    ON public.extension_installation_history(performed_at);

CREATE TABLE IF NOT EXISTS public.extension_hook_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extension_id UUID NOT NULL REFERENCES public.extension_registry(id) ON DELETE CASCADE,
    hook_point VARCHAR(100) NOT NULL,
    hook_priority INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by VARCHAR(100),
    execution_count INTEGER NOT NULL DEFAULT 0,
    average_execution_time_ms INTEGER,
    last_execution_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_assignment_extension_hook
    ON public.extension_hook_assignments(extension_id, hook_point);
CREATE INDEX IF NOT EXISTS idx_assignment_hook_priority
    ON public.extension_hook_assignments(hook_point, hook_priority);
CREATE INDEX IF NOT EXISTS idx_assignment_active_hook
    ON public.extension_hook_assignments(is_active, hook_point);

CREATE TABLE IF NOT EXISTS public.extension_dependency_graph (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extension_id UUID NOT NULL REFERENCES public.extension_registry(id) ON DELETE CASCADE,
    dependency_id UUID NOT NULL REFERENCES public.extension_registry(id) ON DELETE CASCADE,
    dependency_type VARCHAR(20) NOT NULL,
    is_optional BOOLEAN NOT NULL DEFAULT FALSE,
    declared_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(extension_id, dependency_id)
);
CREATE INDEX IF NOT EXISTS idx_dependency_extension
    ON public.extension_dependency_graph(extension_id);
CREATE INDEX IF NOT EXISTS idx_dependency_target
    ON public.extension_dependency_graph(dependency_id);
CREATE INDEX IF NOT EXISTS idx_dependency_type
    ON public.extension_dependency_graph(dependency_type);

CREATE TABLE IF NOT EXISTS public.extension_validation_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extension_id UUID NOT NULL REFERENCES public.extension_registry(id) ON DELETE CASCADE,
    validation_type VARCHAR(50) NOT NULL,
    validation_result BOOLEAN NOT NULL,
    validator_name VARCHAR(100) NOT NULL,
    validation_message TEXT,
    validation_details JSONB,
    severity VARCHAR(20) DEFAULT 'info',
    validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_validation_extension_type
    ON public.extension_validation_logs(extension_id, validation_type);
CREATE INDEX IF NOT EXISTS idx_validation_result
    ON public.extension_validation_logs(validation_result);
CREATE INDEX IF NOT EXISTS idx_validation_severity
    ON public.extension_validation_logs(severity);

CREATE TABLE IF NOT EXISTS public.extension_usage_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extension_id UUID NOT NULL REFERENCES public.extension_registry(id) ON DELETE CASCADE,
    usage_count INTEGER NOT NULL DEFAULT 0,
    unique_users INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    total_execution_time_ms INTEGER NOT NULL DEFAULT 0,
    average_execution_time_ms INTEGER,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_extension_period
    ON public.extension_usage_metrics(extension_id, period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_usage_period
    ON public.extension_usage_metrics(period_start, period_end);
