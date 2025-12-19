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
