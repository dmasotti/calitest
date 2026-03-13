# Locust Sync Load Harness

Questo harness serve a simulare concorrenza reale sul dominio sync.
Il focus non e solo throughput HTTP, ma workflow multi-step con stato utente.
Il file principale e `locustfile.py`.
Il runner consigliato e `run_locust.sh`.
Il flusso supporta:
- `library-hash` / preflight
- `sync/v5` con inventory minimale o con UUID client forniti via env
- presigned upload opzionale `start -> PUT -> complete -> verify`

## Requisiti

- `locust`
- token API valido
- server locale o remoto raggiungibile

Installazione minima:

```bash
python3 -m pip install -r tests/performance/locust/requirements.txt
```

## Variabili ambiente principali

- `CALIMOB_LOCUST_BASE_URL`
  - default: `http://caliserver.test`
- `CALIMOB_LOCUST_API_TOKEN`
  - Bearer token obbligatorio
- `CALIMOB_LOCUST_LIBRARY_ID`
  - opzionale; se assente il client prova a scoprirlo da `/api/libraries`
- `CALIMOB_LOCUST_LIBRARY_UUID`
  - opzionale; se assente il client prova a derivarlo dalla library
- `CALIMOB_LOCUST_BOOK_UUID`
  - opzionale; se assente il presigned flow prova a scoprirlo da `/api/user-books`
- `CALIMOB_LOCUST_CLIENT_UUIDS`
  - opzionale; lista CSV di UUID da mandare in `client_books`
- `CALIMOB_LOCUST_SYNC_FILES`
  - `on|off`, default `off`
- `CALIMOB_LOCUST_SYNC_COVERS`
  - `on|off`, default `off`
- `CALIMOB_LOCUST_ENABLE_PRESIGNED`
  - `on|off`, default `off`
- `CALIMOB_LOCUST_WAIT_MIN_MS`
  - default `250`
- `CALIMOB_LOCUST_WAIT_MAX_MS`
  - default `1250`
- `CALIMOB_LOCUST_BATCH_SIZE`
  - default `100`
- `CALIMOB_LOCUST_CLIENT_BATCH_SIZE`
  - default `100`
- `CALIMOB_LOCUST_API_PREFIX`
  - default `/api`

## Esempi

Solo preflight + sync minimale:

```bash
CALIMOB_LOCUST_API_TOKEN="..." \
CALIMOB_LOCUST_BASE_URL="http://caliserver.test" \
tests/performance/locust/run_locust.sh \
  --users 5 \
  --spawn-rate 2 \
  --run-time 2m
```

Sync con UUID client reali:

```bash
CALIMOB_LOCUST_API_TOKEN="..." \
CALIMOB_LOCUST_CLIENT_UUIDS="uuid-1,uuid-2,uuid-3" \
CALIMOB_LOCUST_SYNC_FILES=on \
CALIMOB_LOCUST_SYNC_COVERS=on \
tests/performance/locust/run_locust.sh \
  --users 10 \
  --spawn-rate 5 \
  --run-time 5m
```

Presigned upload concorrente:

```bash
CALIMOB_LOCUST_API_TOKEN="..." \
CALIMOB_LOCUST_ENABLE_PRESIGNED=on \
CALIMOB_LOCUST_BOOK_UUID="..." \
tests/performance/locust/run_locust.sh \
  --users 3 \
  --spawn-rate 1 \
  --run-time 3m
```

## Note operative

- Il presigned flow scrive davvero oggetti temporanei nello storage del server configurato.
- Per i primi run conviene iniziare con pochi utenti e un `--run-time` corto.
- Se vuoi stressare solo gli endpoint HTTP e non i workflow completi, resta preferibile un harness `k6` separato.
