# Test Suite Server - Subscription e Freemium

Suite completa di test per le funzionalità di subscription e limiti freemium.

## Struttura Test

### `SubscriptionApiTest.php`
Test per gli endpoint API di subscription:
- `GET /api/subscription` - Status subscription
- `GET /api/subscription/pricing` - Pricing tiers
- Verifica autenticazione
- Verifica formattazione dati

### `UserSubscriptionModelTest.php`
Test per i metodi del modello User:
- `getSubscriptionLimits()` - Recupero limiti
- `canCreateLibrary()` - Verifica limite librerie
- `canAddBook()` - Verifica limite libri
- `getStorageUsedBytes()` / `getStorageUsedMB()` - Calcolo storage
- `canAddStorage()` - Verifica limite storage
- `hasFeature()` - Verifica feature disponibili
- `isSubscriptionActive()` - Verifica stato subscription

### `SubscriptionLimitsMiddlewareTest.php`
Test per il middleware `CheckSubscriptionLimits`:
- Blocca creazione libreria quando al limite
- Permette superadmin bypass
- Downgrade automatico subscription scadute

### `LibraryLimitsTest.php`
Test per limiti librerie:
- Creazione libreria via API quando sotto limite
- Blocco creazione quando al limite
- Verifica limiti per diversi tier (free, basic)

### `SyncLimitsTest.php`
Test per limiti durante sync:
- Blocco sync quando limite libri raggiunto
- Blocco sync quando limite storage raggiunto
- Permette sync quando sotto limiti
- Dry run non applica limiti
- Stima corretta storage da files

### `SyncInventoryTest.php`
Test per inventario compresso:
- `buildCalibreInventory()` comprime range correttamente
- `expandInventoryIds()` gestisce active/missing

### `SyncPullTest.php`
Test per pull sync:
- `last_modified` precede `updated_at`
- `inventory_hint` solo nelle pagine delta
- `POST /sync/pull` filtra tombstone con client_inventory
- Paginazione e `has_more`

### `SyncPushTest.php`
Test per push sync:
- Idempotency (riuso stesso payload)
- Idempotency con payload diverso (errore)
- `sync_mappings` per books
- Conflitti e `/api/sync/conflicts` + resolve

### `SyncItemMappingTest.php`
Test per mapping di relazioni:
- `buildItemFromUserBook()` include ID autore/tag/serie

### `TombstoneAdminTest.php`
Test per workflow tombstone superadmin:
- Cleanup tombstone rimuove record e mapping
- Resolve tombstone crea mapping

### `StorageCalculationTest.php`
Test per calcolo storage:
- Include file ebook uploaded
- Include cover locali
- Esclude cover Cloudflare
- Esclude file non uploaded
- Gestisce file mancanti

### `SubscriptionConfigTest.php`
Test per configurazione subscription:
- Verifica struttura config
- Verifica limiti per ogni tier
- Verifica pricing
- Verifica trial days

## Esecuzione Test

### Eseguire tutti i test server
```bash
php artisan test --testsuite=Server
```

### Eseguire un singolo test
```bash
php artisan test tests/server/SubscriptionApiTest.php
```

### Eseguire con coverage
```bash
php artisan test --testsuite=Server --coverage
```

### Eseguire con coverage HTML
```bash
php artisan test --testsuite=Server --coverage-html=coverage
```

## Requisiti

- Database SQLite in-memory (configurato in `phpunit.xml`)
- Factory per: User, Library, UserBook, BookFile, Device
- Config `subscription.php` caricato

## Note

- Tutti i test usano `RefreshDatabase` per isolamento
- I test mockano la config subscription per controllare i limiti
- I test verificano sia successi che fallimenti (edge cases)

## Sync E2E (script manuali)

Script end-to-end che colpiscono le API reali (richiedono server attivo).

```bash
DISCOVERY_URL=https://example.com TEST_USER_EMAIL=user@example.com TEST_USER_PASSWORD=secret ./tests/server/sync_comprehensive_test.sh
DISCOVERY_URL=https://example.com TEST_USER_EMAIL=user@example.com TEST_USER_PASSWORD=secret ./tests/server/sync_protocol_contract_test.sh
DISCOVERY_URL=https://example.com TEST_USER_EMAIL=user@example.com TEST_USER_PASSWORD=secret ./tests/server/sync_pull_post_inventory_test.sh
```

### Debugging API failures

Gli script nella directory `tests/server/` ora mostrano automaticamente l’ultima risposta API quando un comando fallisce. Il log `run_sync_http.log` viene tailato alla fine per fornire contesto aggiuntivo e, se impostato `TEST_DEBUG=1`, viene anche estratto il campo `trace` JSON (quando presente, server in modalità `APP_DEBUG=true`) per visualizzare lo stack trace restituito dall’API. Questa modalità aiuta a identificare immediatamente l’end-point e la payload responsabile del fallimento.
