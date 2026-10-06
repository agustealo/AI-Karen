CREATE TABLE IF NOT EXISTS memory_items (
    memory_id TEXT PRIMARY KEY,
    tenant_id UUID,
    user_id UUID,
    source TEXT,
    scope TEXT,
    kind TEXT,
    content TEXT,
    embeddings VECTOR(768),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    expires_at TIMESTAMP,
    importance FLOAT DEFAULT 0.5,
    confidence FLOAT DEFAULT 1.0,
    source_type VARCHAR(100) DEFAULT 'system',
    source_ref VARCHAR(255),
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embedding_model VARCHAR(255),
    embedding_version VARCHAR(64),
    embedding_dimension INTEGER,
    embedded_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_scope_kind ON memory_items(scope, kind);
CREATE INDEX IF NOT EXISTS idx_memory_items_tenant_user ON memory_items(tenant_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_items_content_tsv ON memory_items USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS idx_memory_items_embeddings_hnsw ON memory_items USING hnsw (embeddings vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_memory_items_embedding_provenance ON memory_items (embedding_model, embedding_version, tenant_id);