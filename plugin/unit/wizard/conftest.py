"""Ensure Qt wizard stubs are available for wizard page tests.

test_core_helpers.py (and possibly other unit tests) overwrite
sys.modules['qt.core'] / sys.modules['PyQt5.Qt'] at import time
with a bare SimpleNamespace that lacks wizard-related symbols.

This conftest uses an autouse session fixture that runs before any
wizard test, re-injecting the required stubs into whatever objects
currently sit in sys.modules.  It also invalidates any cached
(broken) imports of wizard page modules so they get re-imported
against the repaired stubs.
"""

import sys
import pytest


class _WizardStubBase:
    """Minimal Qt widget base that silently absorbs calls/signals."""
    def __init__(self, *a, **kw):
        pass
    def __getattr__(self, name):
        _SIGNALS = frozenset((
            'clicked', 'linkActivated', 'toggled', 'currentIndexChanged',
            'textChanged', 'valueChanged', 'activated', 'pressed',
            'released', 'returnPressed', 'completeChanged',
        ))
        if name in _SIGNALS:
            class _Sig:
                def connect(self, *a, **kw): pass
                def disconnect(self, *a, **kw): pass
                def emit(self, *a, **kw): pass
            sig = _Sig()
            object.__setattr__(self, name, sig)
            return sig
        return lambda *a, **kw: None


# All Qt widget symbols that wizard pages import — must accept constructor args
_ALL_NEEDED = {
    'QWizard', 'QWizardPage', 'QRadioButton', 'QButtonGroup',
    'QVBoxLayout', 'QHBoxLayout', 'QLabel', 'QLineEdit', 'QPushButton',
    'QComboBox', 'QFrame', 'QSpacerItem', 'QProgressBar', 'QTextEdit',
    'QWidget', 'QThread', 'QObject',
}

def _needs_replacement(obj):
    """Return True if the object is not a proper stub (e.g. bare type() without __init__)."""
    if not callable(obj):
        return True
    # If the class __init__ is object.__init__, it won't accept extra args
    try:
        init = getattr(obj, '__init__', None)
        if init is object.__init__:
            return True
    except Exception:
        pass
    return False

_WIZARD_ATTRS = {
    'ModernStyle': 0,
    'NoBackButtonOnStartPage': 1,
    'NoCancelButton': 2,
}


def _repair_qt_stubs():
    """Inject missing Qt stubs into every known Qt stub module.

    Some test files (e.g. test_core_helpers.py) replace sys.modules['qt.core']
    with a bare SimpleNamespace at import time.  Python's ``from X import Y``
    requires X to be a real ``types.ModuleType``, so we must convert it back.
    """
    import types as _types

    for key in ('qt.core', 'PyQt5.Qt', 'PyQt5.QtCore', 'PyQt5.QtWidgets'):
        mod = sys.modules.get(key)
        if mod is None:
            continue

        # If the module has been replaced with a SimpleNamespace, convert
        # it back to a real ModuleType so ``from ... import`` works.
        if not isinstance(mod, _types.ModuleType):
            real_mod = _types.ModuleType(key)
            # Copy all existing attributes
            for attr in dir(mod):
                if attr.startswith('__'):
                    continue
                setattr(real_mod, attr, getattr(mod, attr))
            sys.modules[key] = real_mod
            mod = real_mod

        # Inject / replace all needed widget stubs
        for name in _ALL_NEEDED:
            existing = getattr(mod, name, None)
            if existing is None or _needs_replacement(existing):
                cls = type(name, (_WizardStubBase,), {})
                setattr(mod, name, cls)

        # QWizard constants
        qw = getattr(mod, 'QWizard', None)
        if qw is not None:
            for attr, val in _WIZARD_ATTRS.items():
                if not hasattr(qw, attr):
                    setattr(qw, attr, val)
        # QLineEdit echo modes
        qle = getattr(mod, 'QLineEdit', None)
        if qle is not None and not hasattr(qle, 'Password'):
            qle.Password = 2
            qle.Normal = 0
        # QTextEdit.NoWrap
        qte = getattr(mod, 'QTextEdit', None)
        if qte is not None and not hasattr(qte, 'NoWrap'):
            qte.NoWrap = 0
            qte.LineWrapMode = type('LineWrapMode', (), {'NoWrap': 0})
        # pyqtSignal stub
        if not hasattr(mod, 'pyqtSignal'):
            def _fake_signal(*args, **kwargs):
                class _Sig:
                    def connect(self, *a, **kw): pass
                    def disconnect(self, *a, **kw): pass
                    def emit(self, *a, **kw): pass
                return _Sig()
            setattr(mod, 'pyqtSignal', _fake_signal)

    # Evict cached (broken) imports of wizard page modules so they re-import cleanly
    for key in list(sys.modules):
        if 'wizard.pages.' in key:
            del sys.modules[key]


@pytest.fixture(autouse=True)
def _wizard_qt_stubs():
    """Per-test fixture that repairs Qt stubs before each wizard test."""
    _repair_qt_stubs()
    yield
