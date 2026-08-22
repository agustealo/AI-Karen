import pytest
from ai_karen_engine.services.database.operations_service import get_database_operations_service

def test_no_raw_store_access_in_operations_service():
    """
    Quality check to ensure the service does not import or use raw database clients directly.
    It should only use other service abstractions or health checkers.
    """
    import inspect
    import ai_karen_engine.services.database.operations_service as ops_service
    
    source = inspect.getsource(ops_service)
    
    # These should NOT be present in the source code as direct imports
    forbidden = [
        "PostgresClient", "RedisClient", "MilvusClient", 
        "ElasticsearchClient", "DuckDBClient",
        "psycopg2", "redis.Redis", "pymilvus"
    ]
    
    for client in forbidden:
        # Check for direct imports, but allowing them in strings/comments for this test
        assert f"from ai_karen_engine.clients.database import {client}" not in source
        assert f"import {client}" not in source
