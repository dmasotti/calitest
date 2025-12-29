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

### Goodreads-specific UI (hidden)
- The plugin still includes dialogs/actions that reference Goodreads (linking books, shelves, etc.), but those flows are gated behind a hidden `showGoodreadsFeatures` flag in `sync_calimob/config.py`. For Caliweb we keep it `false`, so the menus/dialogs never appear unless the setting is force-enabled outside the UI (not recommended).

### ⚙️ Inizializzare l’ambiente headless

Per evitare di superare il limite di librerie sul server e avere già pronta la configurazione plugin, esegui questo script prima di lanciare gli script headless:

```bash
CALIMOB_DISCOVERY_URL="http://caliserver.test" \
TEST_USER_EMAIL="dmasotti+test1@gmail.com" \
TEST_USER_PASSWORD="firstsecret" \
tests/plugin/integration/setup_headless_env.sh
```

Lo script:
1. determina l’UUID di `tests/plugin/CalibreTest` (o usa `CALIBRE_LIBRARY_ID`);
2. cancella le librerie esistenti dell’utente (liberando il limite gratuito);
3. crea una nuova libreria via `headless_setup_library.sh`;
4. scrive `generated_sync_calimob.json` con `Goodreads`/`LibraryMappings` + token.

Alla fine stampa le variabili da esportare (`CALIMOB_CONFIG_JSON`, `CALIMOB_LIBRARY_ID`, ecc.) e puoi lanciare direttamente gli script headless (`headless_sync_smoke.sh`, `headless_e2e.py`, `headless_deep_suite.sh`, ecc.).

### ⚠️ Requisiti protocollo

Gli script/integration tests che inviano payload al server devono includere:
- `changes.*.idempotency_key` (stringa ≤191) per ogni modifica
- `changes.*.item.uuid`: il valore UUID dei metadati Calibre (lo script usa `uuid.uuid4()` per le creazioni ad hoc)

I server headless/script di scenario generano `uuid` dinamici prima di fare `POST /api/sync` per rimanere allineati con la validazione lato API.

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

### Smoke test headless (CLI)
Richiede variabili d'ambiente e un file config già pronto:
- `CALIMOB_DISCOVERY_URL`, `CALIMOB_LIBRARY_PATH`, `CALIMOB_LIBRARY_ID`, `CALIMOB_SERVER_LIBRARY_ID`, `CALIMOB_CONFIG_JSON`
- opzionale `CALIMOB_FULL_SYNC=1` per forzare il full sync

```bash
# From project root
tests/plugin/integration/headless_sync_smoke.sh
```

Il test usa `calibre-debug -e sync_calimob/cli.py` con una config temporanea. Se mancano prerequisiti stampa “SKIP”; fallisce solo se il comando esce in errore o se `jq` trova errori nei blocchi `pull`/`push`.

### Headless E2E (scenari approfonditi)
Script: `tests/plugin/integration/headless_e2e.py`

Verifica:
- Full sync (opzionale) restituisce `inventory` compresso
- Incrementale restituisce `inventory_hint`
- Cursor monotono (non regredisce)
Richiede:
- `CALIMOB_DISCOVERY_URL`
- `CALIMOB_LIBRARY_PATH`
- `CALIMOB_LIBRARY_ID`
- `CALIMOB_SERVER_LIBRARY_ID`
- `CALIMOB_CONFIG_JSON`
- `TEST_USER_EMAIL`
- `TEST_USER_PASSWORD`

Lo script esegue un login (`POST /auth/login`) per ottenere un `restToken` temporaneo e aggiorna `plugins/sync_calimob.json` (discoveryUrl + restToken + mapping della libreria) prima di lanciare `calibre-debug`.

```bash
CALIMOB_RUN_FULL=1 \\
python tests/plugin/integration/headless_e2e.py
```

Se `CALIMOB_RUN_FULL` non è impostato, esegue solo l’incrementale.

### Headless Deep Suite (server → Calibre con verifica DB locale)
Script: `tests/plugin/integration/headless_deep_suite.sh`

Verifica:
- Crea/riusa una libreria server per la libreria Calibre locale
- Push di un libro lato server → pull con plugin → verifica titolo nel `metadata.db`
- Update lato server → pull → verifica titolo aggiornato e vecchio titolo assente
- Verifica che `discoveryCache`/`restEndpoint` vengano salvati nella config

Richiede:
- `CALIMOB_DISCOVERY_URL`, `TEST_USER_EMAIL`, `TEST_USER_PASSWORD`
- `CALIMOB_LIBRARY_PATH`, `CALIMOB_LIBRARY_ID`, `CALIMOB_CONFIG_JSON`
- `sqlite3`, `calibre-debug`, `calibre-customize`

```bash
tests/plugin/integration/headless_deep_suite.sh
```

### Scenari specifici (headless)
Script disponibili:
- `tests/plugin/integration/headless_scenario_conflict.sh`
  - Crea un libro via `/api/sync`, poi invia un update con `version` più vecchia → atteso `status=conflict`.
- `tests/plugin/integration/headless_scenario_conflict_e2e.sh`
  - End‑to‑end: server elimina il libro, client fa update in full sync → conflitto `reason=deleted`.
- `tests/plugin/integration/headless_scenario_cover_upload.sh`
  - Crea un libro via `/api/sync`, poi carica una copertina con `PUT /api/items/{id}/cover` e verifica il download.
  - Richiede `CALIMOB_COVER_IMAGE` (file jpg/png locale).
- `tests/plugin/integration/headless_scenario_cover_missing.sh`
  - Imposta `cover_missing=1` via `tools/sql`, verifica che il flag compaia in pull e si azzeri dopo l’upload cover.
  - Richiede `CALIMOB_SUPERADMIN_TOKEN` (superadmin) e `CALIMOB_COVER_IMAGE` opzionale (se mancante crea una PNG temporanea).
- `tests/plugin/integration/headless_scenario_inventory_reconcile.sh`
  - End‑to‑end: pull libro dal server, delete locale, full sync → push delete usando inventory prefetch.
- `tests/plugin/integration/headless_scenario_library_mismatch.sh`
  - Lancia headless con `calibre_library_uuid` sbagliato → attesa risposta 403 “Library ID mismatch”.
- `tests/plugin/integration/headless_scenario_retry_backoff.sh`
  - Verifica retry/backoff del client con un server locale che risponde 503→200.

Variabili richieste (oltre a quelle già usate negli altri test):
- `DISCOVERY_URL`, `TEST_USER_EMAIL`, `TEST_USER_PASSWORD` (lettura anche da `tests/server/.env`)
- `CALIMOB_LIBRARY_ID`, `CALIBRE_LIBRARY_ID` opzionali; se assenti usa la prima libreria dell’utente
- `CALIMOB_COVER_IMAGE` per il test cover upload
- `CALIMOB_SUPERADMIN_TOKEN` per il test cover_missing (tools/sql)

### Setup libreria di test (API)
Script: `tests/plugin/integration/headless_setup_library.sh`

- Crea (o riusa) una libreria in base a `CALIBRE_LIBRARY_ID`.
- Stampa le variabili `CALIMOB_LIBRARY_ID`, `CALIMOB_SERVER_LIBRARY_ID`, `CALIBRE_LIBRARY_ID`.
- Opzionale seeding via `/api/sync`:
  - `SEED_BOOKS=1` o `SEED_BOOKS_COUNT=<n>`
  - `CALIMOB_LIBRARY_NAME` per impostare un nome esplicito

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
