"""Guardrail tests for sync_entrypoints imports in action sync paths."""

from pathlib import Path


def _method_block(source: str, method_name: str) -> str:
    needle = f"def {method_name}("
    start = source.find(needle)
    assert start != -1, f"{method_name} not found in action.py"

    next_def = source.find("\n    def ", start + len(needle))
    if next_def == -1:
        return source[start:]
    return source[start:next_def]


def test_sync_methods_import_sync_entrypoints_before_run_ui_sync():
    root = Path(__file__).resolve().parents[3]
    source = (root / "sync_calimob" / "action.py").read_text(encoding="utf-8")

    for method_name in ("sync_with_calimob", "_start_background_sync", "full_sync_with_calimob"):
        block = _method_block(source, method_name)
        assert "from calibre_plugins.sync_calimob import sync_entrypoints" in block
        assert "sync_entrypoints.run_ui_sync(" in block

