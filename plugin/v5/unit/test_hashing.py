import importlib.util
import os
import sys
import types
import unittest


def _install_stub(module_name):
    if module_name in sys.modules:
        return sys.modules[module_name]
    module = types.ModuleType(module_name)
    sys.modules[module_name] = module
    return module


# Stub PyQt5 to avoid dependency during unit tests
pyqt5 = _install_stub("PyQt5")
qtcore = _install_stub("PyQt5.QtCore")
setattr(qtcore, "QByteArray", object)

# Stub calibre modules used by sync_worker imports
calibre = _install_stub("calibre")
_install_stub("calibre.ebooks")
_install_stub("calibre.ebooks.metadata")
_install_stub("calibre.ebooks.metadata.book")
calibre_book_base = _install_stub("calibre.ebooks.metadata.book.base")
setattr(calibre_book_base, "Metadata", object)

calibre_constants = _install_stub("calibre.constants")
setattr(calibre_constants, "DEBUG", False)

calibre_devices = _install_stub("calibre.devices")
_install_stub("calibre.devices.usbms")
calibre_usb_driver = _install_stub("calibre.devices.usbms.driver")
setattr(calibre_usb_driver, "debug_print", lambda *args, **kwargs: None)

calibre_utils = _install_stub("calibre.utils")
calibre_utils_date = _install_stub("calibre.utils.date")
setattr(calibre_utils_date, "utcnow", lambda: None)

# Stub plugin modules referenced at import time
_install_stub("config")
_install_stub("rest_client")
_install_stub("sync_mapper")
_install_stub("mapping_table")
_install_stub("sync_logger")
logging_utils = _install_stub("logging_utils")
setattr(logging_utils, "calimob_debug", lambda *args, **kwargs: None)
_install_stub("calibre_plugins")
_install_stub("calibre_plugins.sync_calimob")
_install_stub("calibre_plugins.sync_calimob.config")
_install_stub("calibre_plugins.sync_calimob.rest_client")
_install_stub("calibre_plugins.sync_calimob.sync_mapper")
_install_stub("calibre_plugins.sync_calimob.mapping_table")
_install_stub("calibre_plugins.sync_calimob.sync_logger")
calibre_logging_utils = _install_stub("calibre_plugins.sync_calimob.logging_utils")
setattr(calibre_logging_utils, "calimob_debug", lambda *args, **kwargs: None)

SYNC_WORKER_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "..",
        "sync_calimob",
        "sync_worker.py",
    )
)
spec = importlib.util.spec_from_file_location("sync_worker", SYNC_WORKER_PATH)
sync_worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_worker)


class SyncWorkerHashingTests(unittest.TestCase):
    def _make_worker(self):
        worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
        # Minimal attributes used by hashing helpers
        worker._target_debug_uuid = None
        worker._hash_debug_logged = True
        return worker

    def test_compute_files_signature_empty(self):
        worker = self._make_worker()
        self.assertIsNone(worker._compute_files_signature([]))
        self.assertIsNone(worker._compute_files_signature(None))

    def test_compute_files_signature_sorts_and_normalizes(self):
        worker = self._make_worker()
        files = [
            {"format": "EPUB", "file_hash": "abcd"},
            {"format": "PDF", "file_hash": "sha256:ffff"},
            {"format": "MOBI", "hash": "1234"},
        ]
        signature = worker._compute_files_signature(files)
        self.assertEqual(signature, "sha256:1234,sha256:abcd,sha256:ffff")

    def test_normalize_file_hash(self):
        worker = self._make_worker()
        self.assertEqual(worker._normalize_file_hash("abcd"), "sha256:abcd")
        self.assertEqual(worker._normalize_file_hash("sha256:abcd"), "sha256:abcd")
        self.assertEqual(worker._normalize_file_hash({"hash": "abcd"}), "sha256:abcd")
        self.assertIsNone(worker._normalize_file_hash(None))

    def test_compute_metadata_signature_stable(self):
        worker = self._make_worker()
        item = {
            "uuid": "u1",
            "title": "Title",
            "authors": [{"name": "Author", "role": "author", "position": 0}],
            "tags": [{"name": "t1"}, {"name": "t2"}],
            "languages": ["ita", "eng"],
            "series": {"name": "s1", "series_index": 1.0},
        }
        sig1 = worker._compute_metadata_signature(item, {}, None)
        sig2 = worker._compute_metadata_signature(item, {}, None)
        self.assertEqual(sig1, sig2)


if __name__ == "__main__":
    unittest.main()
