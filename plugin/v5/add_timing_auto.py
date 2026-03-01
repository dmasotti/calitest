#!/usr/bin/env python3
"""
Aggiunge la Timer class e il supporto --timing a test_sync_v5_advanced.py
se non sono già presenti. Idempotente: esegibile più volte senza duplicare.

Uso:
  python3 tests/add_timing_auto.py
  # oppure
  python3 tests/add_timing_auto.py /path/to/test_sync_v5_advanced.py
"""

import re
import sys
from pathlib import Path

# Blocco da iniettare dopo "def log_warning(...)"
TIMING_BLOCK = '''
# ========== PERFORMANCE TIMING (--timing) ==========

_timings = []
TIMING_ENABLED = "--timing" in sys.argv  # Set at import time

class Timer:
    """Context manager per misurare tempo in ms. Usare con: with Timer('label'): ..."""
    def __init__(self, label):
        self.label = label
        self.start = None

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed_ms = (time.perf_counter() - self.start) * 1000
        _timings.append((self.label, round(elapsed_ms, 2)))
        return False


def _print_timing_summary(test_name=""):
    """Stampa i timing raccolti per il test corrente."""
    if not _timings:
        return
    total = sum(ms for _, ms in _timings)
    for label, ms in _timings:
        print(f"  [TIMING] {label}: {ms:>10.2f} ms")
    print(f"  [TIMING] TOTAL ({test_name}): {total:.2f} ms")

'''


def main():
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = Path(__file__).resolve().parent / "test_sync_v5_advanced.py"

    if not path.exists():
        print(f"File non trovato: {path}", file=sys.stderr)
        sys.exit(1)

    content = path.read_text(encoding="utf-8")

    if "class Timer" in content and "_timings" in content:
        print("Timer class e _timings già presenti, nessuna modifica.")
        sys.exit(0)

    # Cercare il punto di inserimento: dopo "def log_warning(msg):" e il corpo (fino alla riga vuota / prossima def)
    # Inseriamo dopo "def log_warning(msg):\\n    log(...)"
    pattern = r'(def log_warning\s*\([^)]*\)\s*\n\s+log\([^\n]+\n)\n'
    match = re.search(pattern, content)
    if not match:
        print("Impossibile trovare il punto di inserimento (dopo log_warning).", file=sys.stderr)
        sys.exit(1)

    insert_pos = match.end()
    new_content = content[:insert_pos] + TIMING_BLOCK + content[insert_pos:]

    path.write_text(new_content, encoding="utf-8")
    print(f"Aggiunto blocco Timer e _print_timing_summary in {path}")
    print("Aggiungi manualmente i 'with Timer(...):' nei test usando tests/TIMING_QUICK_ADD.md")


if __name__ == "__main__":
    main()
