-- MEDUSA-DEEPAGENTS-CHECKPOINTS-1
-- Forward-only schema for tenant-scoped LangGraph checkpoints.
-- The canonical PostgreSQL engine owns connections; no runtime DDL is allowed.
-- Deep Agents checkpointing remains OFF until this migration and tests pass.

-- The existing run ledger remains the lifecycle owner. This unique constraint
-- allows checkpoints to prove that run_id belongs to the same tenant.
ALTER TABLE agent_medusa_runs
    ADD CONSTRAINT uq_agent_medusa_runs_id_tenant UNIQUE (run_id, tenant_id);

CREATE TABLE agent_medusa_deepagents_checkpoints (
    tenant_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    policy_decision_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    checkpoint_encoding TEXT NOT NULL,
    checkpoint_bytes BYTEA NOT NULL,
    metadata_encoding TEXT NOT NULL,
    metadata_bytes BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_medusa_deepagents_checkpoint PRIMARY KEY (
        tenant_id, thread_id, checkpoint_ns, checkpoint_id
    ),
    CONSTRAINT fk_medusa_deepagents_checkpoint_run FOREIGN KEY (run_id, tenant_id)
        REFERENCES agent_medusa_runs (run_id, tenant_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_medusa_deepagents_checkpoint_nonempty CHECK (
        user_id <> '' AND session_id <> '' AND policy_decision_id <> ''
        AND run_id <> '' AND thread_id <> '' AND checkpoint_id <> ''
    )
);

CREATE INDEX idx_medusa_deepagents_checkpoints_run
    ON agent_medusa_deepagents_checkpoints (
        tenant_id, run_id, created_at DESC
    );

CREATE TABLE agent_medusa_deepagents_checkpoint_writes (
    tenant_id UUID NOT NULL,
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task_path TEXT NOT NULL DEFAULT '',
    write_index INTEGER NOT NULL,
    channel TEXT NOT NULL,
    value_encoding TEXT NOT NULL,
    value_bytes BYTEA NOT NULL,
    CONSTRAINT pk_medusa_deepagents_checkpoint_write PRIMARY KEY (
        tenant_id, thread_id, checkpoint_ns, checkpoint_id,
        task_id, write_index
    ),
    CONSTRAINT fk_medusa_deepagents_checkpoint_write FOREIGN KEY (
        tenant_id, thread_id, checkpoint_ns, checkpoint_id
    ) REFERENCES agent_medusa_deepagents_checkpoints (
        tenant_id, thread_id, checkpoint_ns, checkpoint_id
    ) ON DELETE CASCADE
);

CREATE INDEX idx_medusa_deepagents_checkpoint_writes_parent
    ON agent_medusa_deepagents_checkpoint_writes (
        tenant_id, thread_id, checkpoint_ns, checkpoint_id, task_id
    );

ALTER TABLE agent_medusa_deepagents_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_medusa_deepagents_checkpoints FORCE ROW LEVEL SECURITY;
CREATE POLICY medusa_deepagents_checkpoints_tenant_isolation
    ON agent_medusa_deepagents_checkpoints FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

ALTER TABLE agent_medusa_deepagents_checkpoint_writes ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_medusa_deepagents_checkpoint_writes FORCE ROW LEVEL SECURITY;
CREATE POLICY medusa_deepagents_checkpoint_writes_tenant_isolation
    ON agent_medusa_deepagents_checkpoint_writes FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE agent_medusa_deepagents_checkpoints IS
    'Governed LangGraph checkpoint snapshots for Deep Agents; lifecycle authority remains in agent_medusa_runs.';
COMMENT ON TABLE agent_medusa_deepagents_checkpoint_writes IS
    'LangGraph intermediate writes. Sensitive contents remain tenant-scoped, never directly exposed to AG-UI.';
