# RAG Comics Test Suite

Test automatizzati per il servizio RAG Comics.

**Totale**: 136 test (91 originali + 45 nuovi)

## Setup

```bash
# Installa dipendenze (include pytest)
cd /Users/macbookpro/Coding/calibre-plg/calicloud/rag-comics
source venv/bin/activate
pip install -r app/requirements.txt
```

## Esecuzione Test

### Tutti i test (skip expensive)
```bash
pytest
```

### Solo unit test (veloci, no API)
```bash
pytest -m unit
```

### Con coverage report
```bash
pytest --cov=app --cov-report=html
# Apri htmlcov/index.html per vedere report
```

### Test specifico
```bash
pytest tests/test_cost_tracker.py
pytest tests/test_cost_tracker.py::TestLLMCostCalculation::test_gemini_flash_cost
```

### Test verbose (mostra output)
```bash
pytest -v
pytest -vv  # Extra verbose
```

### Test con output print
```bash
pytest -s
```

## Marker

I test sono organizzati con marker pytest:

- `@pytest.mark.unit` - Test unitari veloci (no API, no DB)
- `@pytest.mark.integration` - Test integrazione (richiede servizi esterni)
- `@pytest.mark.expensive` - Test con API calls reali (costosi)

### Skip test expensive
```bash
pytest -m "not expensive"
```

### Run solo integration test
```bash
pytest -m integration
```

## Struttura Test

```
tests/
├── __init__.py
├── conftest.py                  # Fixtures condivise
├── test_cost_tracker.py         # Test calcolo costi (✅ 25 test)
├── test_comic_extractor.py      # Test Vision OCR (✅ 15 test)
├── test_document_manager.py     # Test upload/index (✅ 10 test)
├── test_chat_engine.py          # Test chat/query (✅ 8 test)
├── test_callback.py             # Test callback Laravel (✅ 15 test)
└── test_cost_tracking_e2e.py    # Test cost tracking E2E (✅ 18 test)
```

## Coverage Attuale

| Modulo | Coverage | Test Count | Note |
|--------|----------|------------|------|
| `cost_tracker.py` | ~95% | 25 | Tutti i metodi testati |
| `comic_extractor.py` | ~70% | 15 | Funzioni core + parsing |
| `document_manager.py` | ~60% | 10 | Upload, cache, force |
| `chat_engine.py` | ~50% | 8 | Query, LLM init |
| `async_tasks.py` (callback) | ~80% | 15 | Callback sending, retry, validation |
| Cost tracking E2E | ~90% | 18 | Accuracy, operations array |

**Totale**: 91 test

## Test Expensive (API Reali)

Alcuni test sono marcati `@pytest.mark.expensive` perché chiamano API reali:

- `test_extract_with_real_gemini_api` - Costa ~$0.0006
- `test_extract_with_real_openai_api` - Costa ~$0.04

**Per eseguirli**:
```bash
pytest -m expensive
```

⚠️ **Attenzione**: Questi test consumano crediti API reali!

## Continuous Integration

Per CI/CD, usa:
```bash
# Run solo test veloci
pytest -m "unit and not expensive" --cov=app --cov-report=xml
```

## Troubleshooting

### Import errors
```bash
# Verifica PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)/app"
pytest
```

### Fixture not found
Verifica che `conftest.py` sia nella directory `tests/`.

### Async test errors
Verifica che `pytest-asyncio` sia installato:
```bash
pip install pytest-asyncio
```

## Prossimi Passi

- [x] Test calcolo costi (CostTracker)
- [x] Test Vision OCR extraction
- [x] Test upload/indexing workflow
- [x] Test chat/query engine
- [x] Test callback webhook Laravel
- [x] Test cost tracking end-to-end
- [x] Test error handling (timeout, rate limit, corrupted files)
- [x] Test performance (batch size, memory, concurrency)
- [ ] Test character tracking storage/retrieval
- [ ] Aumentare coverage a >85%
- [ ] Integrare in CI/CD pipeline
