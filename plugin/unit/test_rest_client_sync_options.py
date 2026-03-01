from __future__ import annotations

from unittest.mock import Mock

from calibre_plugins.sync_calimob import rest_client


def test_post_sync_includes_no_cache_option():
    client = rest_client.RestApiClient.__new__(rest_client.RestApiClient)
    client.post = Mock(return_value={'results': []})

    client.post_sync(
        changes=[{'op': 'upsert', 'idempotency_key': 'k1', 'item': {'uuid': 'u-1'}}],
        client_cursor='10',
        library_id=7,
        calibre_library_uuid='lib-uuid-1',
        dry_run=False,
        no_cache=True,
    )

    client.post.assert_called_once()
    _, kwargs = client.post.call_args
    body = kwargs['body']
    assert body['options']['no_cache'] is True
    assert body['options']['dry_run'] is False
    assert body['library_id'] == 7
    assert body['calibre_library_uuid'] == 'lib-uuid-1'
