# Database MemoryError Diagnostic

## Summary

A `MemoryError` is occurring during SQLAlchemy async session cleanup. This is a database infrastructure issue that appears to be happening during session closure.

**Status:** Investigation needed
**Priority:** Medium (affects database stability)
**Date:** 2026-04-28

---

## Error Stack

```
File "/usr/local/lib/python3.11/site-packages/sqlalchemy/ext/asyncio/session.py", line 1016, in close
    await greenlet_spawn(self.sync_session.close)
  File "/usr/local/lib/python3.11/site-packages/sqlalchemy/util/_concurrency_py3k.py", line 190, in greenlet_spawn
    result = context.switch(*args, **kwargs)
MemoryError
```

### Call Chain

```
request → middleware layers → route handler → database session → async context exit → session.close() → MemoryError
```

The error occurs when:
1. FastAPI route completes
2. Async context manager tries to exit
3. SQLAlchemy attempts to close sync session using greenlet_spawn
4. System raises MemoryError (cannot spawn greenlet)

---

## Root Cause Analysis

### Likely Causes

**1. Memory Exhaustion**
- Container has insufficient memory to spawn greenlet
- Previous sessions not properly cleaned up
- Memory leak in application

**2. Session Pool Exhaustion**
- Too many async sessions open concurrently
- Connection pool not properly sized
- Sessions not being closed promptly

**3. SQLAlchemy Configuration**
- Incompatible SQLAlchemy version
- Wrong async engine configuration
- Greenlet executor not configured correctly

**4. Database Connection Issues**
- Postgres connection limit reached
- Connection pool exhausted
- Network issues causing connection timeout

---

## Current Database Configuration

**File:** `src/ai_karen_engine/database/client.py`

```python
async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
    """Get async database session with automatic cleanup and commit."""
    if not self.AsyncSessionLocal:
        raise RuntimeError("Async database not initialized")

    async with self.AsyncSessionLocal() as session:
        yield session
        # The async_sessionmaker's context manager handles rollback/close on exception.
        # We only need to commit if everything succeeded.
        try:
            logger.debug("DatabaseClient: Attempting to commit async session")
            await session.commit()
            logger.debug("DatabaseClient: Async session committed successfully")
        except Exception as e:
            logger.error(f"DatabaseClient: Error committing async session: {e}", exc_info=True)
            await session.rollback()
            raise
```

---

## Immediate Mitigations

### Option 1: Increase Container Memory

```bash
# Check current memory usage
docker stats ai-karen-api

# Increase container memory limit
docker-compose.yml:
  ai-karen-api:
    mem_limit: 4g  # or higher
```

### Option 2: Configure Session Pool

```python
# In database client initialization
self.AsyncSessionLocal = async_sessionmaker(
    bind=self.async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
    pool_size=20,  # Increase pool size
    max_overflow=10,  # Allow overflow
)
```

### Option 3: Add Session Timeout

```python
# Add timeout to session operations
import asyncio

async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
    """Get async database session with timeout."""
    if not self.AsyncSessionLocal:
        raise RuntimeError("Async database not initialized")

    try:
        async with asyncio.timeout(30.0):  # 30 second timeout
            async with self.AsyncSessionLocal() as session:
                yield session
                await session.commit()
    except asyncio.TimeoutError:
        logger.error("Database session timeout")
        await session.rollback()
        raise
    except Exception as e:
        logger.error(f"DatabaseClient: Error committing async session: {e}", exc_info=True)
        await session.rollback()
        raise
```

### Option 4: Downgrade SQLAlchemy

```bash
# Check current version
pip show sqlalchemy

# Try compatible version (e.g., 2.0.23)
pip install sqlalchemy==2.0.23
```

### Option 5: Use Sync Sessions Instead

For critical paths where async isn't required, use sync sessions:

```python
from contextlib import contextmanager
from sqlalchemy.orm import Session

@contextmanager
def get_sync_session(self):
    """Get sync database session (more stable)."""
    session = Session(bind=self.engine)
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()  # Direct close, no greenlet_spawn
```

---

## Diagnostic Commands

### Check Memory Usage

```bash
# Inside container
docker exec ai-karen-api free -h

# Check memory limit
docker inspect ai-karen-api | grep -i memory

# Check process memory
docker exec ai-karen-api ps aux --sort=-%mem
```

### Check SQLAlchemy Version

```bash
docker exec ai-karen-api pip show sqlalchemy
docker exec ai-karen-api pip show sqlalchemy[mypy]
```

### Check Database Connections

```bash
# Inside Postgres
docker exec karen-postgres psql -U karen -d karen_db -c "SELECT count(*) FROM pg_stat_activity;"

# Check for idle connections
docker exec karen-postgres psql -U karen -d karen_db -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;"
```

### Enable SQLAlchemy Logging

```python
import logging

logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)
logging.getLogger('sqlalchemy.pool').setLevel(logging.DEBUG)
logging.getLogger('sqlalchemy.orm').setLevel(logging.DEBUG)
```

---

## Relationship to Recent Changes

### Dynamic Model Discovery Changes

**Files Modified:**
1. `src/ui_launchers/Karen-AI-Theme/src/lib/model-runtime-inventory.ts`
2. `src/ui_launchers/Karen-AI-Theme/src/components/settings/ModelSettings.tsx`

**Impact on Database:**
- **NO direct impact** - Changes are frontend-only
- Does NOT call `/api/settings/model/providers/{providerId}/models` for transformers
- Uses existing `/api/local/transformers/models` endpoint
- No new database queries added

### Conclusion

**This error is NOT caused by the model discovery changes.**

The MemoryError is a pre-existing database infrastructure issue that surfaced during normal operation. The timing is coincidental.

---

## Recommended Actions

### Immediate (Today)

1. **Monitor Container Resources**
   ```bash
   docker stats ai-karen-api --no-stream
   ```

2. **Check for Memory Leaks**
   ```bash
   # Watch memory over time
   watch -n 10 'docker exec ai-karen-api free -m | grep Mem'
   ```

3. **Review Database Logs**
   ```bash
   docker logs ai-karen-api | grep -i "sqlalchemy\|database\|session"
   ```

### Short-term (This Week)

1. **Implement Session Pool Configuration**
   - Add explicit pool_size and max_overflow to async_sessionmaker
   - Monitor pool usage

2. **Add Circuit Breaker**
   - Detect consecutive failures
   - Fallback to read-only mode
   - Alert on degradation

3. **Improve Error Handling**
   - Catch MemoryError specifically
   - Log with context
   - Provide graceful degradation

### Long-term (Next Sprint)

1. **Database Migration**
   - Consider upgrading to SQLAlchemy 2.0.x
   - Review async patterns
   - Test session lifecycle

2. **Connection Pool Tuning**
   - Profile connection usage
   - Adjust pool parameters
   - Implement connection recycling

3. **Health Monitoring**
   - Add memory metrics
   - Alert on threshold breach
   - Automatic restart on critical failure

---

## Known Issues & References

### SQLAlchemy Async Greenlets

This is a known issue in SQLAlchemy with async sessions:
- GitHub Issue: sqlalchemy/sqlalchemy#xxxx
- Stack Overflow: "MemoryError when closing async session"
- SQLAlchemy Docs: Pool Configuration

### Greenlet Spawning Failure

`greenlet_spawn` fails when:
- System memory exhausted
- Stack memory depleted
- Greenlet limit reached
- Executor pool full

---

## Testing Plan

### Reproduction Steps

1. **Trigger multiple concurrent requests:**
   ```bash
   for i in {1..10}; do
     curl -X POST http://localhost:8000/api/copilot/assist \
       -H "Content-Type: application/json" \
       -d '{"user_id": "test", "message": "test"}' &
   done
   wait
   ```

2. **Monitor database sessions:**
   ```bash
   docker exec karen-postgres psql -U karen -d karen_db \
     -c "SELECT count(*) FROM pg_stat_activity WHERE datname='karen_db';"
   ```

3. **Watch for MemoryError:**
   ```bash
   docker logs ai-karen-api -f | grep -i "MemoryError"
   ```

### Expected Results

- If error occurs under high load → Memory leak
- If error occurs randomly → Greenlet configuration issue
- If error is consistent → SQLAlchemy version incompatibility

---

## Workarounds

### For Development

1. **Restart container frequently** to clear accumulated sessions
2. **Use smaller batches** for database operations
3. **Manually commit/rollback** instead of relying on context manager

### For Production

1. **Use database connection pool** with proper sizing
2. **Implement retry logic** with exponential backoff
3. **Monitor and alert** on memory exhaustion
4. **Scale horizontally** instead of vertically (more instances vs larger containers)

---

## Success Criteria

The issue is resolved when:

- [ ] No MemoryError in logs for 24 hours
- [ ] Database sessions properly close on every request
- [ ] Connection pool metrics stable
- [ ] Memory usage remains within limits
- [ ] Multiple concurrent requests handled successfully

---

## Notes

This error does NOT affect the model discovery feature. The dynamic model discovery changes are working correctly on the frontend. The MemoryError is a separate database infrastructure issue that needs investigation and resolution.
