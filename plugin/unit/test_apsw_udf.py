"""Test UDF registration with APSW (Calibre production environment)."""
import sys
import os

# Add sync_calimob to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sync_calimob'))

from mapping_table import (
    _ensure_hash_views,
    sha256_udf,
    _HASH_VIEWS_READY_KEYS,
)


class MockAPSWConnection:
    """Mock Calibre's APSW connection."""
    
    def __init__(self):
        self.registered_functions = {}
    
    def createscalarfunction(self, name, func, nargs):
        """APSW method signature."""
        self.registered_functions[name] = (func, nargs)
        print(f"[MOCK] Registered UDF '{name}' with {nargs} args via APSW")


class MockSQLite3Connection:
    """Mock sqlite3 connection."""
    
    def __init__(self):
        self.registered_functions = {}
    
    def create_function(self, name, nargs, func):
        """sqlite3 method signature."""
        self.registered_functions[name] = (func, nargs)
        print(f"[MOCK] Registered UDF '{name}' with {nargs} args via sqlite3")


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class MockViewConnection:
    """Mock connection with execute support to test 'create once' behavior."""

    def __init__(self):
        self.register_calls = 0
        self.create_view_calls = 0

    def createscalarfunction(self, name, func, nargs):
        _ = (name, func, nargs)
        self.register_calls += 1

    def execute(self, sql, params=None):
        _ = params
        if sql == 'PRAGMA database_list':
            return _FakeCursor([(0, 'main', '/tmp/mock-metadata.db')])
        if 'CREATE VIEW' in sql:
            self.create_view_calls += 1
        return _FakeCursor([])


def test_apsw_registration():
    """Test that UDF registers correctly with APSW."""
    _HASH_VIEWS_READY_KEYS.clear()
    conn = MockAPSWConnection()
    _ensure_hash_views(conn)
    
    assert 'sha256' in conn.registered_functions, "UDF not registered"
    func, nargs = conn.registered_functions['sha256']
    assert func == sha256_udf, "Wrong function registered"
    assert nargs == 1, f"Expected 1 arg, got {nargs}"
    print("✅ APSW registration works")


def test_sqlite3_registration():
    """Test that UDF still works with sqlite3."""
    _HASH_VIEWS_READY_KEYS.clear()
    conn = MockSQLite3Connection()
    _ensure_hash_views(conn)
    
    assert 'sha256' in conn.registered_functions, "UDF not registered"
    func, nargs = conn.registered_functions['sha256']
    assert func == sha256_udf, "Wrong function registered"
    assert nargs == 1, f"Expected 1 arg, got {nargs}"
    print("✅ sqlite3 registration works")


def test_no_method_available():
    """Test graceful failure when neither method exists."""
    
    class NoMethodConnection:
        pass
    
    conn = NoMethodConnection()
    _ensure_hash_views(conn)  # Should not crash
    print("✅ Graceful failure when no method available")


def test_hash_views_created_only_once_per_db():
    """Second call on same DB should no-op (no re-register/recreate VIEWs)."""
    _HASH_VIEWS_READY_KEYS.clear()
    conn = MockViewConnection()

    _ensure_hash_views(conn)
    create_calls_after_first = conn.create_view_calls
    _ensure_hash_views(conn)

    assert conn.register_calls == 2
    assert create_calls_after_first > 0
    assert conn.create_view_calls == create_calls_after_first


if __name__ == '__main__':
    print("Testing APSW UDF registration...")
    test_apsw_registration()
    test_sqlite3_registration()
    test_no_method_available()
    print("\n✅ All tests passed!")
