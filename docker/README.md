# Docker Services Tests

Test automatizzati per i servizi Docker (RAG, Converter, etc).

## Struttura

```
docker/
└── rag-comics/          # Test RAG Comics service
    ├── __init__.py
    ├── conftest.py                  # Fixtures condivise
    ├── test_cost_tracker.py         # Test calcolo costi (25 test)
    ├── test_comic_extractor.py      # Test Vision OCR (15 test)
    ├── test_document_manager.py     # Test upload/index (10 test)
    ├── test_chat_engine.py          # Test chat/query (8 test)
    ├── test_callback.py             # Test callback Laravel (15 test)
    ├── test_cost_tracking_e2e.py    # Test cost tracking E2E (18 test)
    ├── README.md                    # Documentazione dettagliata
    ├── pytest.ini                   # Configurazione pytest
    └── run_tests.sh                 # Test runner
```

## Quick Start

```bash
# Setup (una volta)
cd /Users/macbookpro/Coding/calibre-plg/calicloud/rag-comics
source venv/bin/activate
pip install -r app/requirements.txt

# Run test
cd /Users/macbookpro/Coding/calibre-plg/tests/docker/rag-comics
./run_tests.sh unit
```

## Test Disponibili

### RAG Comics (91 test)
- **Cost Tracker** (25 test): Calcolo costi LLM, Vision, Embedding
- **Comic Extractor** (15 test): Vision OCR, parsing, character tracking
- **Document Manager** (10 test): Upload, indexing, cache, force reindex
- **Chat Engine** (8 test): Query RAG, LLM initialization
- **Callback** (15 test): Webhook Laravel, retry, validation
- **Cost Tracking E2E** (18 test): Accuracy, operations array

## Comandi

```bash
# Test veloci (2-5s)
./run_tests.sh unit

# Tutti i test (skip expensive)
./run_tests.sh all

# Con coverage report
./run_tests.sh coverage

# Test specifico
cd /Users/macbookpro/Coding/calibre-plg/tests/docker/rag-comics
pytest test_cost_tracker.py -v
```

## Note

- I test usano il venv di `calicloud/rag-comics/`
- Mock tutte le API esterne (no costi)
- Test expensive sono skip by default
- Coverage target: 85%

Per dettagli completi, vedi `rag-comics/README.md`.
