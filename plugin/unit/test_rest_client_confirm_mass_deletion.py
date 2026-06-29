"""The server has a mass-deletion backstop: a deletion batch larger than the
server cap is refused unless options.confirm_mass_deletion is set. The plugin
must send that flag ONLY when its own local guard confirmed a deliberate large
delete — never by default — so a buggy/restored library cannot silently wipe the
server, while an intentional confirmed delete still goes through."""
from __future__ import annotations

from unittest.mock import Mock

from calibre_plugins.sync_calimob import rest_client


def _client():
    client = rest_client.RestApiClient.__new__(rest_client.RestApiClient)
    client.post = Mock(return_value={'updates_for_client': []})
    client._log = lambda *a, **k: None
    return client


def test_confirm_flag_absent_by_default():
    client = _client()
    client.sync_v5(
        library_id=7, calibre_library_uuid='lib-uuid-1',
        client_books={'b': {}, 'd': ['u-1', 'u-2']},
    )
    _, kwargs = client.post.call_args
    options = kwargs['body']['options']
    assert 'confirm_mass_deletion' not in options


def test_confirm_flag_sent_only_when_requested():
    client = _client()
    client.sync_v5(
        library_id=7, calibre_library_uuid='lib-uuid-1',
        client_books={'b': {}, 'd': ['u-1', 'u-2']},
        confirm_mass_deletion=True,
    )
    _, kwargs = client.post.call_args
    assert kwargs['body']['options']['confirm_mass_deletion'] is True
