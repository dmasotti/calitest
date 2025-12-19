# Test Suite Plugin Calibre - sync_calimob

Strategia completa di testing per il plugin Calibre `sync_calimob`.

## 🎯 Strategia di Testing

### Livelli di Test

1. **Unit Test** - Funzioni pure senza dipendenze esterne
2. **Integration Test** - Componenti con dipendenze mockate
3. **End-to-End Test** - Flussi completi con server mockato

## 📋 Componenti da Testare

### 1. Unit Test (Funzioni Pure)

#### `sync_mapper.py`
- ✅ `calibre_to_json_item()` - Conversione metadati Calibre → JSON
- ✅ `json_item_to_calibre()` - Conversione JSON → metadati Calibre
- ✅ `calculate_cover_hash()` - Calcolo hash SHA256 copertine
- ✅ Gestione custom columns (progress_percent, favorite)
- ✅ Mappatura tag → status

#### `library_utils.py`
- ✅ `_read_library_metadata()` - Lettura metadata.db
- ✅ `get_calibre_library_id()` - Estrazione UUID libreria
- ✅ `get_calibre_library_name()` - Estrazione nome libreria
- ✅ `_normalize_path()` - Normalizzazione path
- ✅ `_find_config_dirs()` - Trovare directory config Calibre

### 2. Integration Test (Con Mock)

#### `rest_client.py`
- ✅ `RestApiClient.__init__()` - Inizializzazione con config
- ✅ `_normalize_endpoint()` - Normalizzazione URL endpoint
- ✅ `_get_headers()` - Generazione headers HTTP
- ✅ `_request()` - Chiamate HTTP con retry/backoff
- ✅ `test_connection()` - Test connessione server
- ✅ `get_libraries()` - Lista librerie
- ✅ `create_library()` - Creazione libreria
- ✅ `pull_changes()` - Pull modifiche server
- ✅ `push_changes()` - Push modifiche client
- ✅ `upload_cover()` - Upload copertina
- ✅ `download_cover()` - Download copertina
- ✅ Gestione errori HTTP (401, 403, 404, 500)
- ✅ Retry logic con exponential backoff

#### `sync_worker.py`
- ✅ `SyncWorker.__init__()` - Inizializzazione worker
- ✅ `pull_sync()` - Sincronizzazione pull (server → Calibre)
- ✅ `push_sync()` - Sincronizzazione push (Calibre → server)
- ✅ `sync()` - Sincronizzazione bidirezionale completa
- ✅ `full_sync()` - Sincronizzazione completa (ignora cursor)
- ✅ Gestione cursor (save/get/reset)
- ✅ Gestione conflitti
- ✅ Upload/download copertine batch
- ✅ Gestione errori e recovery

#### `config.py`
- ✅ `ConfigWidget` - UI configurazione
- ✅ Salvataggio/caricamento impostazioni
- ✅ Validazione endpoint URL
- ✅ Validazione token
- ✅ Associazione librerie

### 3. End-to-End Test (Con Server Mockato)

#### Flussi Completi
- ✅ Sincronizzazione completa (pull + push)
- ✅ Creazione nuovo libro su server
- ✅ Aggiornamento libro esistente
- ✅ Eliminazione libro
- ✅ Upload copertina
- ✅ Download copertina
- ✅ Gestione conflitti (stesso libro modificato su entrambi i lati)
- ✅ Sincronizzazione incrementale (con cursor)
- ✅ Sincronizzazione completa (senza cursor)
- ✅ Gestione errori di rete
- ✅ Recovery dopo errore

## 🛠️ Strumenti e Librerie

### Framework di Test
- **pytest** - Framework principale per test Python
- **pytest-mock** - Mocking avanzato
- **pytest-qt** - Test per componenti Qt
- **responses** - Mock HTTP requests
- **unittest.mock** - Mock standard library

### Mock Necessari

#### Calibre
- `calibre.gui2` - GUI components
- `calibre.db` - Database Calibre
- `calibre.ebooks.metadata` - Metadata objects
- `calibre.utils.config` - Config storage

#### Qt
- `qt.core` / `PyQt5.Qt` - Widget Qt
- `QApplication` - Application Qt

#### HTTP
- `httplib2` - HTTP client
- Server REST API responses

## 📁 Struttura Directory

```
tests/
├── plugin/                          # Test plugin Calibre
│   ├── README.md                    # Questo file
│   ├── conftest.py                  # Fixtures comuni pytest
│   ├── unit/                        # Unit test (funzioni pure)
│   │   ├── test_sync_mapper.py
│   │   └── test_library_utils.py
│   ├── integration/                 # Integration test (con mock)
│   │   ├── test_rest_client.py
│   │   ├── test_sync_worker.py
│   │   └── test_config.py
│   ├── e2e/                        # End-to-end test
│   │   ├── test_sync_flows.py
│   │   └── test_conflict_resolution.py
│   ├── fixtures/                    # Dati di test
│   │   ├── sample_books.json
│   │   ├── sample_metadata.db
│   │   └── sample_covers/
│   └── mocks/                       # Mock helpers
│       ├── calibre_mock.py
│       ├── qt_mock.py
│       └── server_mock.py
└── ...
```

## 🧪 Esempi di Test

### Unit Test - sync_mapper

```python
def test_calibre_to_json_item_basic():
    """Test conversione base metadati Calibre → JSON"""
    from calibre.ebooks.metadata.book.base import Metadata
    from sync_calimob.sync_mapper import calibre_to_json_item
    
    metadata = Metadata('Test Book')
    metadata.authors = ['Author One', 'Author Two']
    metadata.series = 'Test Series'
    metadata.series_index = 1.0
    
    item = calibre_to_json_item(123, metadata, 'lib-uuid')
    
    assert item['title'] == 'Test Book'
    assert len(item['authors']) == 2
    assert item['series']['name'] == 'Test Series'
    assert item['series']['index'] == 1.0
```

### Integration Test - rest_client

```python
import responses
from sync_calimob.rest_client import RestApiClient

@responses.activate
def test_get_libraries_success():
    """Test recupero librerie dal server"""
    responses.add(
        responses.GET,
        'https://api.example.com/api/libraries',
        json={'libraries': [{'id': '1', 'name': 'Test Lib'}]},
        status=200
    )
    
    client = RestApiClient()
    client.endpoint = 'https://api.example.com/api'
    client.token = 'test-token'
    
    result = client.get_libraries()
    
    assert 'libraries' in result
    assert len(result['libraries']) == 1
```

### E2E Test - Sync Flow

```python
def test_full_sync_flow(mock_calibre_db, mock_server):
    """Test flusso completo di sincronizzazione"""
    worker = SyncWorker(mock_calibre_db.gui, mock_calibre_db.db, 'lib-id', 'calimob-lib-id')
    
    # Setup: server ha 2 libri, Calibre ha 1 libro diverso
    mock_server.add_book({'id': 1, 'title': 'Server Book 1'})
    mock_server.add_book({'id': 2, 'title': 'Server Book 2'})
    mock_calibre_db.add_book({'id': 3, 'title': 'Local Book 1'})
    
    # Esegui sync
    summary = worker.sync()
    
    # Verifica: Calibre ha tutti e 3 i libri
    assert len(mock_calibre_db.get_all_books()) == 3
    # Verifica: server ha tutti e 3 i libri
    assert len(mock_server.get_all_books()) == 3
```

## 🚀 Setup e Esecuzione

### Installazione Dipendenze

```bash
pip install pytest pytest-mock pytest-qt responses
```

### Esecuzione Test

```bash
# Tutti i test plugin
pytest tests/plugin/

# Solo unit test
pytest tests/plugin/unit/

# Solo integration test
pytest tests/plugin/integration/

# Solo e2e test
pytest tests/plugin/e2e/

# Con coverage
pytest tests/plugin/ --cov=sync_calimob --cov-report=html

# Test specifico
pytest tests/plugin/unit/test_sync_mapper.py::test_calibre_to_json_item_basic
```

## 📊 Coverage Target

- **Unit Test**: 80%+ coverage su funzioni pure
- **Integration Test**: 70%+ coverage su componenti principali
- **E2E Test**: Copertura di tutti i flussi critici

## 🔍 Mock Strategy

### Calibre Mock
- Mock database senza file system reale
- Mock metadata objects
- Mock GUI components (senza Qt reale)

### Server Mock
- `responses` per mock HTTP requests
- Server fake con stato in-memory
- Simulazione errori di rete

### Qt Mock
- `pytest-qt` per test Qt senza GUI reale
- Mock QApplication
- Mock dialog/widget

## 📝 Note

- I test NON richiedono Calibre installato (usa mock)
- I test NON richiedono Qt GUI reale (usa pytest-qt)
- I test possono essere eseguiti in CI/CD
- Database Calibre mockato in-memory
- Server REST mockato con `responses`

## 🐛 Debugging

### Eseguire test con output verbose
```bash
pytest tests/plugin/ -v -s
```

### Eseguire test con debugger
```bash
pytest tests/plugin/ --pdb
```

### Eseguire test specifico con breakpoint
```python
import pytest
pytest.set_trace()  # Breakpoint nel test
```
