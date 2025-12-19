# Quick Start - Test Plugin sync_calimob

Guida rapida per iniziare a testare il plugin Calibre.

## 🚀 Setup Iniziale

### 1. Installa Dipendenze

```bash
cd tests/plugin
pip install -r requirements.txt
```

### 2. Verifica Setup

```bash
pytest --version
# Dovrebbe mostrare: pytest 7.4.0 o superiore
```

## 🧪 Esegui i Primi Test

### Test Esistenti

```bash
# Esegui tutti i test
pytest

# Esegui solo unit test (più veloci)
pytest unit/

# Esegui con output verbose
pytest -v

# Esegui con output dettagliato
pytest -v -s
```

### Test Specifici

```bash
# Test singolo
pytest unit/test_sync_mapper.py::test_calibre_to_json_item_basic

# Test con pattern
pytest -k "test_calibre_to_json"

# Test con marker
pytest -m unit
```

## 📝 Scrivi il Primo Test

### Esempio: Test Unit

Crea `tests/plugin/unit/test_my_function.py`:

```python
"""Test per la mia funzione."""

import pytest
from sync_calimob import my_module

def test_my_function_basic():
    """Test base della mia funzione."""
    result = my_module.my_function('input')
    assert result == 'expected_output'

def test_my_function_with_none():
    """Test con input None."""
    result = my_module.my_function(None)
    assert result is None
```

### Esempio: Test Integration

Crea `tests/plugin/integration/test_my_api.py`:

```python
"""Test per API client."""

import pytest
import responses
from sync_calimob import rest_client

@responses.activate
def test_my_api_call():
    """Test chiamata API."""
    responses.add(
        responses.GET,
        'https://api.example.com/api/test',
        json={'status': 'ok'},
        status=200
    )
    
    client = rest_client.RestApiClient()
    result = client.get_test()
    
    assert result['status'] == 'ok'
```

## 🎯 Struttura Test

### Pattern AAA (Arrange, Act, Assert)

```python
def test_example():
    # ARRANGE: Setup dati di test
    metadata = Metadata('Test Book')
    book_id = 123
    
    # ACT: Esegui operazione
    result = sync_mapper.calibre_to_json_item(book_id, metadata, 'lib-id')
    
    # ASSERT: Verifica risultato
    assert result['title'] == 'Test Book'
    assert result['calibre_book_id'] == 123
```

## 🔧 Fixtures Disponibili

Le fixtures sono definite in `conftest.py`:

- `mock_calibre_metadata` - Metadata Calibre mockato
- `mock_calibre_db` - Database Calibre mockato
- `mock_calibre_gui` - GUI Calibre mockata
- `mock_plugin_config` - Configurazione plugin mockata
- `sample_json_item` - Esempio JSON item dal server
- `sample_calibre_book` - Esempio libro Calibre

### Uso Fixtures

```python
def test_with_fixture(mock_calibre_db, sample_json_item):
    """Test usando fixtures."""
    result = sync_mapper.json_item_to_calibre(
        sample_json_item,
        mock_calibre_db
    )
    assert result['title'] == 'Test Book'
```

## 🐛 Debugging

### Verbose Output

```bash
pytest -v -s
```

### Debugger Interattivo

```bash
pytest --pdb
```

### Breakpoint nel Codice

```python
def test_with_breakpoint():
    import pytest
    pytest.set_trace()  # Breakpoint qui
    # ... resto del test
```

## 📊 Coverage

### Genera Report Coverage

```bash
# Coverage terminale
pytest --cov=sync_calimob --cov-report=term

# Coverage HTML (apri htmlcov/index.html)
pytest --cov=sync_calimob --cov-report=html

# Coverage XML (per CI/CD)
pytest --cov=sync_calimob --cov-report=xml
```

## ✅ Checklist per Nuovo Test

- [ ] Test ha nome descrittivo (`test_<function>_<scenario>`)
- [ ] Test ha docstring che spiega cosa testa
- [ ] Test usa pattern AAA (Arrange, Act, Assert)
- [ ] Test è isolato (non dipende da altri test)
- [ ] Test verifica sia successi che fallimenti
- [ ] Test usa fixtures quando appropriato
- [ ] Test ha assertions chiari e specifici

## 📚 Documentazione

- **README.md** - Panoramica generale
- **STRATEGY.md** - Strategia completa di testing
- **QUICKSTART.md** - Questo file (guida rapida)

## 🆘 Troubleshooting

### Import Error

```python
# Se vedi: ImportError: No module named 'sync_calimob'
# Assicurati che il path sia corretto in conftest.py
```

### Qt Error

```python
# Se vedi errori Qt, usa pytest-qt:
pytest --qt-no-exception-capture
```

### Mock Non Funziona

```python
# Assicurati di usare @patch correttamente:
from unittest.mock import patch

@patch('calibre_plugins.sync_calimob.config.plugin_prefs')
def test_with_patch(mock_prefs):
    # ...
```

## 🎓 Esempi Completi

Vedi i file di test esistenti:
- `unit/test_sync_mapper.py` - Esempi unit test
- `unit/test_library_utils.py` - Esempi unit test
- `integration/test_rest_client.py` - Esempi integration test

## 🚀 Prossimi Passi

1. ✅ Leggi `STRATEGY.md` per strategia completa
2. ✅ Esplora test esistenti per capire pattern
3. ✅ Scrivi il tuo primo test
4. ✅ Esegui test e verifica che passino
5. ✅ Aggiungi coverage per nuove funzionalità

## 💡 Tips

- **Inizia piccolo**: Scrivi test semplici prima di quelli complessi
- **Usa fixtures**: Riutilizza setup comune
- **Mock tutto**: Mocka dipendenze esterne
- **Test isolati**: Ogni test deve essere indipendente
- **Naming chiaro**: Nome del test deve spiegare cosa testa
