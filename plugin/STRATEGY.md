# Strategia Completa di Testing per sync_calimob Plugin

## 📊 Panoramica

Questo documento descrive la strategia completa per testare il plugin Calibre `sync_calimob`, che sincronizza metadati e copertine tra Calibre e un server REST esterno.

## 🎯 Obiettivi di Testing

1. **Affidabilità**: Garantire che il plugin funzioni correttamente in tutti gli scenari
2. **Manutenibilità**: Facilitare modifiche future con test che documentano il comportamento
3. **Qualità**: Rilevare bug prima della produzione
4. **Documentazione**: I test servono come documentazione vivente del comportamento

## 🏗️ Architettura di Testing

### Livelli di Test (Pyramid)

```
        /\
       /E2E\          ← Pochi test end-to-end completi
      /------\
     /Integration\   ← Test di integrazione con mock
    /------------\
   /   Unit Test  \   ← Molti test unitari veloci
  /----------------\
```

### 1. Unit Test (70% dei test)

**Scopo**: Testare funzioni pure senza dipendenze esterne

**Caratteristiche**:
- ✅ Veloce (< 1ms per test)
- ✅ Deterministici
- ✅ Nessuna dipendenza esterna
- ✅ Facili da debuggare

**Componenti**:
- `sync_mapper.py` - Funzioni di conversione
- `library_utils.py` - Utility per librerie Calibre
- Funzioni helper pure

**Esempio**:
```python
def test_calibre_to_json_item_basic():
    metadata = Metadata('Test Book')
    item = calibre_to_json_item(123, metadata, 'lib-id')
    assert item['title'] == 'Test Book'
```

### 2. Integration Test (20% dei test)

**Scopo**: Testare componenti con dipendenze mockate

**Caratteristiche**:
- ✅ Testano interazioni tra componenti
- ✅ Usano mock per dipendenze esterne
- ✅ Più lenti dei unit test ma ancora veloci

**Componenti**:
- `rest_client.py` - Client HTTP con server mockato
- `sync_worker.py` - Worker con database mockato
- `config.py` - Configurazione con storage mockato

**Esempio**:
```python
@responses.activate
def test_get_libraries():
    responses.add(GET, '/api/libraries', json={'libraries': []})
    result = client.get_libraries()
    assert 'libraries' in result
```

### 3. End-to-End Test (10% dei test)

**Scopo**: Testare flussi completi end-to-end

**Caratteristiche**:
- ✅ Testano scenari reali completi
- ✅ Più lenti ma più realistici
- ✅ Verificano integrazione completa

**Scenari**:
- Sincronizzazione completa (pull + push)
- Gestione conflitti
- Upload/download copertine
- Creazione/aggiornamento/eliminazione libri

**Esempio**:
```python
def test_full_sync_flow():
    # Setup: server ha 2 libri, Calibre ha 1 libro
    # Esegui sync
    # Verifica: entrambi hanno 3 libri
```

## 🛠️ Stack Tecnologico

### Framework
- **pytest** - Framework principale
- **pytest-mock** - Mock avanzato
- **pytest-qt** - Test Qt senza GUI
- **responses** - Mock HTTP requests

### Mock Strategy

#### Calibre Mock
```python
mock_db = Mock()
mock_db.get_metadata = Mock(return_value=metadata)
mock_db.library_path = '/tmp/test_library'
```

#### Qt Mock
```python
# pytest-qt gestisce automaticamente QApplication
# Non serve GUI reale
```

#### Server Mock
```python
@responses.activate
def test_api_call():
    responses.add(GET, '/api/test', json={'data': 'test'})
    result = client.get_test()
```

## 📁 Struttura Directory

```
tests/plugin/
├── README.md              # Documentazione generale
├── STRATEGY.md            # Questo file
├── conftest.py            # Fixtures comuni
├── pytest.ini             # Configurazione pytest
├── requirements.txt       # Dipendenze test
│
├── unit/                  # Unit test (70%)
│   ├── test_sync_mapper.py
│   └── test_library_utils.py
│
├── integration/           # Integration test (20%)
│   ├── test_rest_client.py
│   ├── test_sync_worker.py
│   └── test_config.py
│
├── e2e/                   # End-to-end test (10%)
│   ├── test_sync_flows.py
│   └── test_conflict_resolution.py
│
├── fixtures/              # Dati di test
│   ├── sample_books.json
│   └── sample_covers/
│
└── mocks/                 # Mock helpers
    ├── calibre_mock.py
    └── server_mock.py
```

## 🧪 Casi di Test Principali

### Unit Test

#### sync_mapper.py
- ✅ Conversione Calibre → JSON (tutti i campi)
- ✅ Conversione JSON → Calibre (tutti i campi)
- ✅ Gestione valori None/null
- ✅ Gestione custom columns
- ✅ Mappatura tag → status
- ✅ Calcolo hash copertine

#### library_utils.py
- ✅ Lettura metadata.db
- ✅ Estrazione library_id
- ✅ Estrazione library_name
- ✅ Normalizzazione path
- ✅ Gestione errori (file mancanti, DB corrotto)

### Integration Test

#### rest_client.py
- ✅ Inizializzazione client
- ✅ Normalizzazione endpoint
- ✅ Generazione headers
- ✅ GET/POST/PUT/DELETE requests
- ✅ Gestione errori HTTP (401, 403, 404, 500)
- ✅ Retry logic con backoff
- ✅ Upload/download copertine
- ✅ Pull/push changes

#### sync_worker.py
- ✅ Inizializzazione worker
- ✅ Pull sync (server → Calibre)
- ✅ Push sync (Calibre → server)
- ✅ Sync completo (pull + push)
- ✅ Gestione cursor
- ✅ Gestione conflitti
- ✅ Upload/download copertine batch
- ✅ Recovery dopo errori

### E2E Test

#### Flussi Completi
- ✅ Sincronizzazione completa (pull + push)
- ✅ Creazione nuovo libro
- ✅ Aggiornamento libro esistente
- ✅ Eliminazione libro
- ✅ Upload copertina
- ✅ Download copertina
- ✅ Conflitto: stesso libro modificato su entrambi i lati
- ✅ Sincronizzazione incrementale (con cursor)
- ✅ Sincronizzazione completa (senza cursor)
- ✅ Recovery dopo errore di rete

## 📊 Coverage Target

- **Unit Test**: 80%+ coverage
- **Integration Test**: 70%+ coverage
- **E2E Test**: Copertura di tutti i flussi critici

**Totale**: 75%+ coverage complessiva

## 🚀 Esecuzione Test

### Setup
```bash
cd tests/plugin
pip install -r requirements.txt
```

### Esecuzione
```bash
# Tutti i test
pytest

# Solo unit test
pytest unit/

# Solo integration test
pytest integration/

# Solo e2e test
pytest e2e/

# Con coverage
pytest --cov=sync_calimob --cov-report=html

# Test specifico
pytest unit/test_sync_mapper.py::test_calibre_to_json_item_basic
```

### CI/CD Integration
```yaml
# .github/workflows/test.yml
- name: Run plugin tests
  run: |
    cd tests/plugin
    pytest --cov=sync_calimob --cov-report=xml
```

## 🔍 Debugging

### Verbose Output
```bash
pytest -v -s
```

### Debugger
```bash
pytest --pdb
```

### Breakpoint nel codice
```python
import pytest
pytest.set_trace()  # Breakpoint
```

## 📝 Best Practices

1. **Naming**: `test_<function>_<scenario>()`
2. **AAA Pattern**: Arrange, Act, Assert
3. **Isolation**: Ogni test è indipendente
4. **Fixtures**: Riutilizzare setup comune
5. **Mock**: Mockare tutto tranne il codice sotto test
6. **Assertions**: Assert specifici e chiari
7. **Documentation**: Docstring per ogni test

## 🐛 Gestione Errori

### Test di Errori
```python
def test_error_handling():
    with pytest.raises(RestApiError) as exc_info:
        client.get_invalid_endpoint()
    assert exc_info.value.status_code == 404
```

### Test di Edge Cases
```python
def test_empty_data():
    result = mapper.convert({})
    assert result == {}
```

## 📈 Metriche

- **Tempo esecuzione**: < 30 secondi per tutti i test
- **Coverage**: 75%+ complessiva
- **Test count**: ~100-150 test totali
  - Unit: ~70-100 test
  - Integration: ~20-30 test
  - E2E: ~10-20 test

## 🔄 Manutenzione

### Quando aggiungere test
- ✅ Nuova funzionalità
- ✅ Bug fix
- ✅ Refactoring importante

### Quando aggiornare test
- ✅ Cambio API
- ✅ Cambio comportamento
- ✅ Bug trovato in produzione

## 📚 Risorse

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-mock Documentation](https://pytest-mock.readthedocs.io/)
- [responses Documentation](https://github.com/getsentry/responses)
