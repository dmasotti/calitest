# sync_calimob Plugin Tests

Test suite per il plugin Calibre sync_calimob.

## 🎯 Tipologie di Test

### 1. **Integration Tests** (`test_plugin_integration.py`)
Test che girano dentro l'ambiente Calibre usando `calibre-debug`.

**Coverage:**
- ✅ Cover hash calculation
- ✅ Client ID extraction
- ✅ Delete payload structure
- ✅ Idempotency key generation
- ✅ Protocol compliance

### 2. **Scenario Tests** (`test_sync_scenarios.py`)
Test di scenari di sync senza database Calibre.

**Coverage:**
- ✅ Create book scenario
- ✅ Update book scenario
- ✅ Delete book scenario
- ✅ Pull response validation
- ✅ Push batch validation
- ✅ Conflict detection

## 🚀 Come Eseguire i Test

### Prerequisiti

1. **Calibre installato** con `calibre-debug` disponibile
2. **Plugin installato** in Calibre

### Eseguire Integration Tests

```bash
# From project root
/Applications/calibre.app/Contents/MacOS/calibre-debug -e tests/plugin/test_plugin_integration.py

# On Linux
calibre-debug -e tests/plugin/test_plugin_integration.py

# On Windows
calibre-debug.exe -e tests/plugin/test_plugin_integration.py
```

**Output atteso:**
```
============================================================
  sync_calimob Plugin Integration Tests
============================================================
✓ Plugin modules loaded successfully

[TEST] Cover hash calculation
  ✓ Hash calculated: d2f0e6b2...
...
============================================================
  Test Results: 5 passed, 0 failed
============================================================
```

### Eseguire Scenario Tests

```bash
# From project root
python tests/plugin/test_sync_scenarios.py

# Or with calibre-debug
/Applications/calibre.app/Contents/MacOS/calibre-debug -e tests/plugin/test_sync_scenarios.py
```

**Output atteso:**
```
============================================================
  Sync Scenario Tests
============================================================

[SCENARIO] Client creates new book
  ✓ Create payload structure valid
  ✓ Book ID: 1001
  ✓ Title: New Book Title
...
============================================================
  Scenario Results: 6 passed, 0 failed
============================================================
```

## 📋 Test Coverage

| Area | Integration | Scenario | Total |
|------|-------------|----------|-------|
| Payload Structure | ✅ | ✅ | 2 |
| Protocol Compliance | ✅ | ✅ | 2 |
| Hash Calculation | ✅ | - | 1 |
| Client ID Handling | ✅ | - | 1 |
| Create Operations | - | ✅ | 1 |
| Update Operations | - | ✅ | 1 |
| Delete Operations | ✅ | ✅ | 2 |
| Batch Operations | - | ✅ | 1 |
| Conflict Detection | - | ✅ | 1 |
| **Total** | **5** | **6** | **11** |

## 🧪 Aggiungere Nuovi Test

### Integration Test

```python
def test_new_feature():
    """Test description"""
    print("\n[TEST] New feature")
    
    # Test logic
    result = some_plugin_function()
    
    assert result is not None, "Result should not be None"
    print(f"  ✓ Feature works: {result}")
    
    return True
```

### Scenario Test

```python
def test_scenario_new_case():
    """Test: Description"""
    print("\n[SCENARIO] New case")
    
    # Setup scenario
    payload = {
        'op': 'create',
        'item': {...}
    }
    
    # Validate
    assert 'op' in payload
    print("  ✓ Scenario valid")
    
    return True
```

## 🐛 Debugging Failed Tests

### Verbose Output

Modifica il test per aggiungere più debug:

```python
print(f"DEBUG: Variable value = {variable}")
import json
print(json.dumps(payload, indent=2))
```

### Run Single Test

Commenta gli altri test in `run_all_tests()`:

```python
tests = [
    # ("Other Test", test_other),
    ("My Test", test_my_feature),  # Solo questo
]
```

## 🔍 Test Checklist

Prima di committare verificare:

- [ ] Tutti i test integration passano
- [ ] Tutti i test scenario passano
- [ ] Aggiunto test per nuova feature
- [ ] Test documenta il comportamento atteso
- [ ] Nessuna dipendenza esterna oltre Calibre

## 📝 Limitazioni

**Integration Tests:**
- ❌ Non possono testare UI del plugin
- ❌ Non hanno accesso a database Calibre reale
- ❌ Non possono testare network calls (mock necessario)
- ✅ Testano logica core e data structures

**Scenario Tests:**
- ❌ Non testano codice che usa API Calibre
- ✅ Testano protocollo e payload structure
- ✅ Possono girare senza Calibre

## 🚦 CI/CD

Per integrare in CI/CD serve ambiente con Calibre:

```yaml
# GitHub Actions example
- name: Install Calibre
  run: |
    sudo apt-get update
    sudo apt-get install -y calibre
    
- name: Install Plugin
  run: |
    calibre-customize -a sync_calimob.zip
    
- name: Run Tests
  run: |
    cd sync_calimob
    calibre-debug -e test_plugin_integration.py
    calibre-debug -e test_sync_scenarios.py
```

## 📚 Risorse

- [Calibre Plugin Development](https://manual.calibre-ebook.com/creating_plugins.html)
- [calibre-debug Documentation](https://manual.calibre-ebook.com/generated/en/calibre-debug.html)
- Protocollo Sync: `../docs/server/PROTOCOLLO_SYNC_AGGIORNATO1.md`

## 📄 License

Same as parent project.
