"""Test VIEW creation with real APSW connection."""
import pytest


@pytest.mark.skip(reason="Mock doesn't support fetchall iteration")
def test_view_creation_with_apsw(mock_calibre_db):
    """Test that VIEWs can be created with APSW connection."""
    from calibre_plugins.sync_calimob import mapping_table as mt
    
    conn = mock_calibre_db.new_api.backend.conn
    
    # This should work without errors
    try:
        mt._ensure_hash_views(conn)
        print("✅ VIEWs created successfully")
    except Exception as e:
        import traceback
        print(f"❌ VIEW creation failed: {e}")
        print(f"Traceback:\n{traceback.format_exc()}")
        pytest.fail(f"VIEW creation failed: {e}")
    
    # Verify VIEWs exist
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view' AND name LIKE 'calimob%'")
    views = [row[0] for row in cursor.fetchall()]
    print(f"Created views: {views}")
    
    assert 'calimob_books_hash_v2' in views
    assert 'calimob_library_hash_payload' in views
