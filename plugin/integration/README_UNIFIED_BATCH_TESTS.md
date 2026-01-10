# Unified Batch Sync Tests

Test suite per verificare il funzionamento corretto del nuovo sistema di sync unificato con batch atomici.

## 📋 Test Coverage

### **test_unified_batch_sync.py** (Unit/Integration Tests)

Test funzionalità base del unified batch sync:

1. ✅ **test_basic_batch_sync_flow**
   - Verifica flusso PULL → PUSH interleaved
   - Controllo batches_completed, pull_changes
   - Verifica salvataggio cursor

2. ✅ **test_empty_batch_with_has_more**
   - Batch vuoto con has_more=true
   - Verifica avanzamento cursor
   - Skip batch vuoti

3. ✅ **test_progress_calculation**
   - Calcolo progress bar (0.5 pull + 0.5 push)
   - Verifica (current, total) corretti
   - Progress fluido 0% → 100%

4. ✅ **test_cancellation_during_sync**
   - Cancel button durante sync
   - Verifica stop immediato
   - Nessun lavoro extra dopo cancel

5. ✅ **test_error_resilience**
   - Errori non critici non bloccano sync
   - Continue processing dopo errore
   - Errori loggati in summary

6. ✅ **test_conflicts_detection**
   - Conflicts dal server rilevati
   - Logging conflicts
   - Summary contiene conflicts

7. ✅ **test_cursor_persistence**
   - Cursor salvato dopo ogni batch
   - Ordine cursor corretto
   - Resume da cursor salvato

8. ✅ **test_total_errors_in_summary**
   - total_errors per UI
   - Formato corretto per error dialog
   - Distinzione critical vs warning

### **test_cancel_resume_stress.py** (Stress Tests)

Test scenari realistici di cancellazione e ripresa:

1. ✅ **test_cancel_after_first_batch**
   - Cancel dopo batch completo
   - Cursor salvato correttamente
   - Nessun batch extra processato

2. ✅ **test_resume_from_saved_cursor**
   - Resume da cursor salvato
   - No re-lavoro libri già processati
   - Continua da dove interrotto

3. ✅ **test_cancel_during_long_apply**
   - Cancel durante operazione lunga
   - Risposta veloce (<1s)
   - Non tutti i libri processati

4. ✅ **test_no_data_corruption_on_cancel**
   - Nessun cursor salvato su cancel incompleto
   - Partial applies tracciati
   - Stato consistente

5. ✅ **test_progress_resumes_correctly**
   - Progress bar non accumula tra run
   - Ogni run parte da 0
   - Total estimate corretto

### **TestCancellationCheckpoints** (Checkpoint Tests)

Test checkpoints di cancellazione:

1. ✅ **test_checkpoint_at_batch_start**
   - Cancel prima di start batch
   - Nessuna API call fatta
   - Exit immediato

2. ✅ **test_checkpoint_during_apply_loop**
   - Cancel durante apply changes
   - Stop al checkpoint corretto
   - Numero applies limitato

3. ✅ **test_checkpoint_during_cover_download**
   - Cancel durante download cover
   - Stop al checkpoint
   - Numero download limitato

---

## 🚀 Come Eseguire i Test

### **Esegui tutti i test**:
```bash
cd /Users/macbookpro/Coding/calibre-plg/tests/plugin/integration

# Test base
python test_unified_batch_sync.py

# Test stress
python test_cancel_resume_stress.py

# Entrambi con verbose
python test_unified_batch_sync.py -v
python test_cancel_resume_stress.py -v
```

### **Esegui test specifico**:
```bash
# Singolo test
python test_unified_batch_sync.py TestUnifiedBatchSync.test_basic_batch_sync_flow

# Classe intera
python test_unified_batch_sync.py TestUnifiedBatchSync

# Con pytest (se installato)
pytest test_unified_batch_sync.py -v
pytest test_cancel_resume_stress.py -v -s  # Con output
```

### **Esegui con coverage**:
```bash
# Install coverage
pip install coverage

# Run con coverage
coverage run -m unittest discover -s . -p "test_*.py"
coverage report
coverage html  # Genera report HTML
```

---

## 📊 Expected Output

### **Success Case**:
```
test_basic_batch_sync_flow (__main__.TestUnifiedBatchSync) ... ok
test_cancellation_during_sync (__main__.TestUnifiedBatchSync) ... ok
test_conflicts_detection (__main__.TestUnifiedBatchSync) ... ok
test_cursor_persistence (__main__.TestUnifiedBatchSync) ... ok
test_empty_batch_with_has_more (__main__.TestUnifiedBatchSync) ... ok
test_error_resilience (__main__.TestUnifiedBatchSync) ... ok
test_progress_calculation (__main__.TestUnifiedBatchSync) ... ok
test_total_errors_in_summary (__main__.TestUnifiedBatchSync) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.523s

OK
```

### **Failure Case**:
```
FAIL: test_cancellation_during_sync (__main__.TestUnifiedBatchSync)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "test_unified_batch_sync.py", line 156, self.assertIn('cancel', str(ctx.exception).lower())
AssertionError: 'cancel' not found in 'other error'
```

---

## 🐛 Troubleshooting

### **Import Errors**:
```
ImportError: No module named 'sync_worker'
```
**Fix**: Verifica path del plugin:
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sync_calimob'))
```

### **Mock Errors**:
```
AttributeError: Mock object has no attribute 'post_sync_pull'
```
**Fix**: Verifica mock setup in setUp():
```python
self.mock_client.post_sync_pull = Mock(return_value={...})
```

### **Test Timeout**:
Se test impiegano troppo tempo (>5s):
- Riduci batch size nei test
- Riduci numero di libri fake
- Usa `time.sleep(0)` invece di `time.sleep(0.01)`

---

## 📝 Test Checklist

Prima di rilasciare, verifica:

### **Functionality**:
- [ ] Tutti i test passano
- [ ] Coverage >80%
- [ ] No deprecation warnings

### **Performance**:
- [ ] Test suite completa <10 secondi
- [ ] Nessun memory leak (run 100x)
- [ ] Timeout gestiti correttamente

### **Edge Cases**:
- [ ] Empty batches
- [ ] Server errors (500, timeout)
- [ ] Network interruption
- [ ] Concurrent cancellation
- [ ] Very large batches (1000+ books)

---

## 🔄 CI/CD Integration

### **GitHub Actions** (esempio):
```yaml
name: Test Unified Batch Sync

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.8'
      - name: Install dependencies
        run: pip install coverage
      - name: Run tests
        run: |
          cd tests/plugin/integration
          python -m unittest discover -v
      - name: Coverage report
        run: |
          coverage run -m unittest discover
          coverage report --fail-under=80
```

---

## 📚 Documentazione Correlata

- **Architecture**: `docs/UNIFIED_BATCH_SYNC_ARCHITECTURE.md`
- **Test Plan**: `docs/TEST_PLAN_UNIFIED_BATCH_SYNC.md`
- **SQL Optimization**: `docs/OPTIMIZATION_SQL_ORDER_BY.md`

---

**Ultimo aggiornamento**: 2026-01-10  
**Maintainer**: Plugin Development Team  
**Status**: ✅ Ready for CI/CD
