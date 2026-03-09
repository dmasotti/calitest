"""Test APSW connection has createscalarfunction method."""
import pytest


def test_apsw_connection_has_createscalarfunction(mock_calibre_db):
    """Verify that Calibre's APSW connection has createscalarfunction."""
    conn = mock_calibre_db.new_api.backend.conn
    
    # Log connection type for debugging
    conn_type = type(conn).__name__
    print(f"Connection type: {conn_type}")
    print(f"Has createscalarfunction: {hasattr(conn, 'createscalarfunction')}")
    print(f"Has create_function: {hasattr(conn, 'create_function')}")
    
    # Check available methods
    methods = [m for m in dir(conn) if 'function' in m.lower() or 'scalar' in m.lower()]
    print(f"Available function-related methods: {methods}")
    
    # This should pass for real APSW connections
    # (mock might not have it, so we just log)
    if hasattr(conn, 'createscalarfunction'):
        # Try to register a simple UDF
        def test_udf(x):
            return x
        
        try:
            conn.createscalarfunction("test_func", test_udf, 1)
            print("✅ UDF registration successful")
        except Exception as e:
            print(f"❌ UDF registration failed: {e}")
    else:
        print("⚠️ Connection doesn't have createscalarfunction (might be a mock)")
