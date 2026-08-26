# AI Karen Engine - Database Layer

The database layer provides multi-tenant data persistence for the AI Karen platform. It supports multiple database backends including PostgreSQL, Redis, DuckDB, and vector databases for comprehensive data management.

## Architecture Overview

The database layer is designed with multi-tenancy as a core principle:

```
Database Layer
├── Multi-Tenant Client      # Primary database interface
├── Models                   # SQLAlchemy data models
├── Migration Manager        # Schema migration system
├── Memory Manager          # Conversation memory storage
├── Conversation Manager    # Chat conversation management
├── Tenant Manager          # Multi-tenant operations
└── Integration Manager     # External system integration
```

## Core Components

### Multi-Tenant PostgreSQL Client (`client.py`)

Primary database interface with multi-tenant support:

- **Connection Management**: Connection pooling and lifecycle
- **Tenant Isolation**: Data isolation per tenant
- **Query Interface**: High-level query operations
- **Transaction Management**: ACID transaction support

#### Usage Example
```python
from ai_karen_engine.database import MultiTenantPostgresClient

# Initialize client
db_client = MultiTenantPostgresClient(
    host="localhost",
    port=5433,
    database="karen_db",
    username="karen_user",
    password="secure_password"
)

# Tenant-specific operations
async with db_client.get_tenant_session("tenant_123") as session:
    # Query tenant data
    users = await session.query(User).filter(
        User.tenant_id == "tenant_123"
    ).all()

    # Create new record
    new_user = User(
        tenant_id="tenant_123",
        email="user@kari.ai",
        name="John Doe"
    )
    session.add(new_user)
    await session.commit()
```

### Data Models (`models.py`)

SQLAlchemy models for all system entities:

#### Core Models
- **Base**: Base model with common fields
- **Tenant**: Tenant information and configuration
- **User**: User accounts and profiles
- **TenantConversation**: Conversation records per tenant
- **TenantMemoryEntry**: Memory entries per tenant

#### Model Definitions
```python
from ai_karen_engine.database import Base, Tenant, User

# Access model classes
class CustomModel(Base):
    __tablename__ = 'custom_data'

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
```

### Migration Manager (`migrations.py`)

Handles database schema migrations:

- **Version Control**: Track schema versions
- **Migration Scripts**: SQL and Python migration support
- **Rollback Support**: Safe migration rollbacks
- **Multi-Tenant Migrations**: Tenant-specific schema changes

#### Migration Usage
```python
from ai_karen_engine.database import MigrationManager

migration_manager = MigrationManager(db_client)

# Run pending migrations
await migration_manager.migrate()

# Check migration status
status = await migration_manager.get_migration_status()

# Rollback to specific version
await migration_manager.rollback_to_version("001_initial")
```

### Memory Manager (`memory_manager.py`)

Manages conversation memory and context:

- **Memory Storage**: Persistent conversation memory
- **Context Retrieval**: Semantic search and retrieval
- **Memory Embeddings**: Vector embeddings for similarity search
- **Memory Cleanup**: Automatic memory cleanup and archival

#### Memory Operations
```python
from ai_karen_engine.database.memory_manager import MemoryManager

memory_manager = MemoryManager(db_client)

# Store conversation memory
await memory_manager.store_memory(
    tenant_id="tenant_123",
    user_id="user_456",
    conversation_id="conv_789",
    content="User asked about Python programming",
    memory_type="conversation",
    metadata={"topic": "programming", "language": "python"}
)

# Retrieve relevant memories
memories = await memory_manager.retrieve_memories(
    tenant_id="tenant_123",
    user_id="user_456",
    query="Python programming questions",
    limit=10
)

# Search memories by similarity
similar_memories = await memory_manager.search_similar_memories(
    tenant_id="tenant_123",
    embedding_vector=[0.1, 0.2, 0.3, ...],
    threshold=0.8
)
```

### Conversation Manager (`conversation_manager.py`)

Manages chat conversations and message history:

- **Conversation Lifecycle**: Create, update, archive conversations
- **Message Management**: Store and retrieve messages
- **Conversation Search**: Search conversations by content
- **Export/Import**: Conversation data export and import

#### Conversation Operations
```python
from ai_karen_engine.database.conversation_manager import ConversationManager

conv_manager = ConversationManager(db_client)

# Create new conversation
conversation = await conv_manager.create_conversation(
    tenant_id="tenant_123",
    user_id="user_456",
    title="AI Assistant Chat",
    metadata={"type": "general", "priority": "normal"}
)

# Add message to conversation
message = await conv_manager.add_message(
    conversation_id=conversation.id,
    role="user",
    content="Hello, how can you help me?",
    metadata={"timestamp": datetime.utcnow()}
)

# Get conversation history
history = await conv_manager.get_conversation_history(
    conversation_id=conversation.id,
    limit=50
)
```

### Tenant Manager (`tenant_manager.py`)

Manages multi-tenant operations:

- **Tenant Provisioning**: Create and configure tenants
- **Resource Allocation**: Manage tenant resources
- **Data Isolation**: Ensure tenant data separation
- **Tenant Analytics**: Usage and performance metrics

#### Tenant Operations
```python
from ai_karen_engine.database.tenant_manager import TenantManager

tenant_manager = TenantManager(db_client)

# Create new tenant
tenant = await tenant_manager.create_tenant(
    name="Acme Corporation",
    plan="enterprise",
    configuration={
        "max_users": 1000,
        "storage_limit": "100GB",
        "ai_model_access": ["gpt-4", "claude-3"]
    }
)

# Get tenant usage statistics
usage = await tenant_manager.get_tenant_usage(tenant.id)

# Update tenant configuration
await tenant_manager.update_tenant_config(
    tenant.id,
    {"max_users": 1500}
)
```

## Database Backends

### PostgreSQL (Primary)

Main relational database for structured data:

- **Connection String**: `postgresql://user:pass@host:port/db`
- **Features**: ACID transactions, complex queries, JSON support
- **Extensions**: Vector extensions for embeddings
- **Pooling**: Connection pooling with SQLAlchemy

### Redis (Caching)

High-performance caching and session storage:

- **Connection**: Redis client with connection pooling
- **Use Cases**: Session storage, caching, real-time features
- **Data Types**: Strings, hashes, lists, sets, sorted sets
- **Expiration**: Automatic key expiration

### DuckDB (Analytics)

Embedded analytics database:

- **File-based**: Local file storage for analytics
- **Use Cases**: Data analysis, reporting, aggregations
- **Performance**: Optimized for analytical queries
- **Integration**: Direct Python integration

### Vector Databases

For AI embeddings and similarity search:

- **Milvus**: Distributed vector database
- **Chroma**: Lightweight vector store
- **Integration**: Seamless embedding storage and retrieval

## Configuration

### Database Configuration
```python
# Environment variables
POSTGRES_URL = "postgresql://user:pass@localhost:5433/karen_db"
REDIS_URL = "redis://localhost:6379/0"
DUCKDB_PATH = "/data/analytics.duckdb"
MILVUS_HOST = "localhost"
MILVUS_PORT = 19530

# Connection pooling
DB_POOL_SIZE = 20
DB_MAX_OVERFLOW = 30
DB_POOL_TIMEOUT = 30
```

### Multi-Tenant Configuration
```python
# Tenant isolation strategy
TENANT_ISOLATION = "schema"  # or "database" or "row_level"

# Default tenant settings
DEFAULT_TENANT_CONFIG = {
    "max_users": 100,
    "storage_limit": "10GB",
    "retention_days": 365
}
```

## Performance Optimization

### Connection Pooling
```python
from sqlalchemy.pool import QueuePool

engine = create_async_engine(
    POSTGRES_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    pool_recycle=3600
)
```

### Query Optimization
```python
# Use indexes for common queries
class User(Base):
    __tablename__ = 'users'

    id = Column(UUID, primary_key=True)
    tenant_id = Column(String, index=True)  # Indexed for tenant queries
    email = Column(String, unique=True, index=True)  # Indexed for lookups
    created_at = Column(DateTime, index=True)  # Indexed for time-based queries

# Efficient bulk operations
async def bulk_insert_users(session, users_data):
    await session.execute(
        insert(User),
        users_data
    )
    await session.commit()
```

### Caching Strategy
```python
from ai_karen_engine.database.cache import CacheManager

cache_manager = CacheManager(redis_client)

# Cache frequently accessed data
@cache_manager.cached(ttl=3600)  # Cache for 1 hour
async def get_user_profile(user_id: str):
    return await db_client.get_user(user_id)

# Cache invalidation
await cache_manager.invalidate(f"user_profile:{user_id}")
```

## Security

### Data Encryption
```python
# Encrypt sensitive fields
from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine

class User(Base):
    __tablename__ = 'users'

    id = Column(UUID, primary_key=True)
    email = Column(String)
    # Encrypt sensitive data
    personal_data = Column(EncryptedType(JSON, secret_key, AesEngine, 'pkcs5'))
```

### Access Control
```python
# Row-level security for multi-tenancy
async def get_tenant_data(session, tenant_id: str, user_id: str):
    # Ensure user belongs to tenant
    user = await session.query(User).filter(
        User.id == user_id,
        User.tenant_id == tenant_id
    ).first()

    if not user:
        raise AuthorizationError("Access denied")

    # Return tenant-specific data
    return await session.query(Data).filter(
        Data.tenant_id == tenant_id
    ).all()
```

## Monitoring

### Database Metrics
```python
from prometheus_client import Counter, Histogram

# Database operation metrics
DB_QUERIES = Counter('db_queries_total', 'Database queries', ['operation', 'table'])
DB_QUERY_DURATION = Histogram('db_query_duration_seconds', 'Query duration')

# Usage in database operations
@DB_QUERY_DURATION.time()
async def execute_query(query):
    DB_QUERIES.labels(operation='select', table='users').inc()
    return await session.execute(query)
```

### Health Checks
```python
async def check_database_health():
    try:
        # Test database connection
        await db_client.execute("SELECT 1")

        # Test Redis connection
        await redis_client.ping()

        return {"status": "healthy", "databases": ["postgresql", "redis"]}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

## Migration Scripts

### SQL Migrations
```sql
-- migrations/001_create_users_table.sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_tenant_id ON users(tenant_id);
CREATE INDEX idx_users_email ON users(email);
```

### Python Migrations
```python
# migrations/002_add_user_preferences.py
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('users', sa.Column('preferences', sa.JSON))

def downgrade():
    op.drop_column('users', 'preferences')
```

## Testing

### Database Testing
```python
import pytest
from ai_karen_engine.database import MultiTenantPostgresClient

@pytest.fixture
async def db_client():
    client = MultiTenantPostgresClient(TEST_DATABASE_URL)
    await client.initialize()
    yield client
    await client.cleanup()

async def test_user_creation(db_client):
    async with db_client.get_tenant_session("test_tenant") as session:
        user = User(
            tenant_id="test_tenant",
            email="test@example.com",
            name="Test User"
        )
        session.add(user)
        await session.commit()

        # Verify user was created
        created_user = await session.query(User).filter(
            User.email == "test@example.com"
        ).first()
        assert created_user is not None
        assert created_user.name == "Test User"
```

## Best Practices

### Database Design
1. **Normalization**: Properly normalize data structures
2. **Indexing**: Add indexes for frequently queried columns
3. **Constraints**: Use database constraints for data integrity
4. **Partitioning**: Partition large tables for performance
5. **Archival**: Implement data archival strategies

### Multi-Tenancy
1. **Isolation**: Ensure complete tenant data isolation
2. **Performance**: Optimize queries for multi-tenant scenarios
3. **Scalability**: Design for horizontal scaling
4. **Security**: Implement tenant-level security controls

### Performance
1. **Connection Pooling**: Use appropriate connection pool sizes
2. **Query Optimization**: Optimize slow queries
3. **Caching**: Implement effective caching strategies
4. **Monitoring**: Monitor database performance metrics

## Contributing

When contributing to the database layer:

1. Follow the established multi-tenant patterns
2. Include comprehensive tests for all database operations
3. Consider performance implications of schema changes
4. Update migration scripts for schema modifications
5. Ensure proper error handling and logging
6. Follow security best practices for data handling


Schema migration execution is deployment-owned. Runtime code is read-only with respect to schema evolution.
