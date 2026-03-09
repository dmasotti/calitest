"""
Client-side ID conformance tests for sync payload generation.

These tests validate that client IDs are treated as optional hints:
- included when available
- omitted when missing
- stable across repeated payload generation
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock


plugin_path = Path(__file__).parent.parent.parent.parent / "sync_calimob"
sync_mapper_path = plugin_path / "sync_mapper.py"
spec = importlib.util.spec_from_file_location("sync_mapper", str(sync_mapper_path))
sync_mapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_mapper)


def _base_metadata():
    md = Mock()
    md.title = "ID Conformance Book"
    md.sort = None
    md.title_sort = None
    md.author_sort = None
    md.authors = ["Author One", "Author Two"]
    md.series = "Series Name"
    md.series_index = 1.0
    md.isbn = None
    md.identifiers = {}
    md.publisher = None
    md.pubdate = None
    md.languages = ["eng"]
    md.tags = ["tag-a", "tag-b"]
    md.rating = 0
    md.comments = ""
    md.uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    md.timestamp = None
    md.last_modified = None
    md.get = lambda *_args, **_kwargs: None
    return md


def test_includes_author_tag_series_ids_when_available():
    md = _base_metadata()
    md.author_ids = [101, 102]
    md.tag_ids = [201, 202]
    md.series_id = 301

    item = sync_mapper.calibre_to_json_item(book_id=10, metadata=md, library_id="lib-1")

    assert [a.get("id") for a in item["authors"]] == [101, 102]
    assert [t.get("id") for t in item["tags"]] == [201, 202]
    assert [a.get("position") for a in item["authors"]] == [0, 1]
    assert [t.get("position") for t in item["tags"]] == [0, 1]
    assert item["series"].get("id") == 301


def test_omits_ids_when_not_available():
    md = _base_metadata()
    md.author_ids = []
    md.tag_ids = []
    md.series_id = None

    item = sync_mapper.calibre_to_json_item(book_id=10, metadata=md, library_id="lib-1")

    assert all("id" not in author for author in item["authors"])
    assert all("id" not in tag for tag in item["tags"])
    assert "id" not in item["series"]


def test_payload_is_stable_across_successive_generations():
    md = _base_metadata()
    md.author_ids = [111, 222]
    md.tag_ids = [333, 444]
    md.series_id = 555

    item1 = sync_mapper.calibre_to_json_item(book_id=77, metadata=md, library_id="lib-1")
    item2 = sync_mapper.calibre_to_json_item(book_id=77, metadata=md, library_id="lib-1")
    stable1 = {
        "id": item1["id"],
        "uuid": item1["uuid"],
        "authors": [(a.get("name"), a.get("id")) for a in item1["authors"]],
        "tags": [(t.get("name"), t.get("id"), t.get("position")) for t in item1["tags"]],
        "series": (item1["series"].get("name"), item1["series"].get("id")),
    }
    stable2 = {
        "id": item2["id"],
        "uuid": item2["uuid"],
        "authors": [(a.get("name"), a.get("id")) for a in item2["authors"]],
        "tags": [(t.get("name"), t.get("id"), t.get("position")) for t in item2["tags"]],
        "series": (item2["series"].get("name"), item2["series"].get("id")),
    }
    assert stable1 == stable2
