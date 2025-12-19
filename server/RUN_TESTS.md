# Guida Esecuzione Test Server

**⚠️ IMPORTANTE**: **Tutti i test** sono stati spostati da `html/tests/` a `tests/` (nella root del progetto) per **non includerli nel deploy di produzione**. Questo mantiene pulito il deploy e separa completamente i test dal codice di produzione.

## Prerequisiti

1. Database SQLite in-memory (configurato in `phpunit.xml` nella root)
2. Factory create per: User, Library, UserBook, BookFile, Device (in `html/database/factories/`)
3. Config `subscription.php` presente (in `html/config/`)
4. `phpunit.xml` nella root del progetto che punta a `html/` per Laravel

## Struttura

```
calibre-plg/
├── html/                    # Laravel application (deployato in produzione)
│   ├── app/
│   ├── config/
│   ├── database/
│   └── ...                  # NO tests/ qui!
├── tests/                   # Tutti i test (NON deployati)
│   ├── TestCase.php         # Base test case con autoloader personalizzato
│   ├── Feature/             # Test feature Laravel
│   ├── Unit/                # Test unit Laravel
│   └── server/              # Test server subscription/freemium
│       ├── SubscriptionApiTest.php
│       └── ...
├── phpunit.xml              # Config PHPUnit nella root
└── scripts/
    └── upTest               # Script per eseguire test sul server remoto
```

## Esecuzione Test sul Server Remoto (Consigliato)

**⚠️ IMPORTANTE**: I test devono essere eseguiti sul server remoto, non in locale.

Usa lo script `scripts/upTest` che si connette al server e esegue i test:

### Tutti i test server
```bash
./scripts/upTest --testsuite=Server
```

### Con coverage
```bash
./scripts/upTest --testsuite=Server --coverage
```

### Con coverage HTML (dettagliato)
```bash
./scripts/upTest --testsuite=Server --coverage-html=coverage/server
```

### Singolo file di test
```bash
./scripts/upTest tests/server/SubscriptionApiTest.php
```

### Singolo test specifico
```bash
./scripts/upTest --filter test_get_subscription_status_returns_correct_data
```

### Con output verbose
```bash
./scripts/upTest --testsuite=Server -v
```

### Con stop on failure
```bash
./scripts/upTest --testsuite=Server --stop-on-failure
```

### Combinazioni
```bash
# Test Server con coverage e verbose
./scripts/upTest --testsuite=Server --coverage -v

# Test specifico con stop on failure
./scripts/upTest --filter SubscriptionApiTest --stop-on-failure

# Tutti i test con coverage HTML
./scripts/upTest --coverage-html=coverage/server
```

### Esempi Pratici
```bash
# Esegui solo SubscriptionApiTest
./scripts/upTest --filter SubscriptionApiTest

# Esegui solo test di storage
./scripts/upTest --filter StorageCalculationTest

# Esegui test con coverage e mostra solo summary
./scripts/upTest --testsuite=Server --coverage --min=80

# Esegui tutti i test (nessun filtro)
./scripts/upTest
```

## Esecuzione Test in Locale (Solo per sviluppo)

**⚠️ NOTA**: Questi comandi funzionano solo se hai PHP e Laravel configurati localmente.

### Tutti i test server
```bash
# Dalla root del progetto
./html/vendor/bin/phpunit -c phpunit.xml --testsuite=Server
```

### Con coverage
```bash
./html/vendor/bin/phpunit -c phpunit.xml --testsuite=Server --coverage
```

### Con coverage HTML (dettagliato)
```bash
./html/vendor/bin/phpunit -c phpunit.xml --testsuite=Server --coverage-html=coverage/server
```

### Singolo file di test
```bash
./html/vendor/bin/phpunit -c phpunit.xml tests/server/SubscriptionApiTest.php
```

### Singolo test specifico
```bash
./html/vendor/bin/phpunit -c phpunit.xml --filter test_get_subscription_status_returns_correct_data
```

### Con output verbose
```bash
./html/vendor/bin/phpunit -c phpunit.xml --testsuite=Server -v
```

### Con stop on failure
```bash
./html/vendor/bin/phpunit -c phpunit.xml --testsuite=Server --stop-on-failure
```

## Test Disponibili

### 1. SubscriptionApiTest (8 test)
- Test endpoint API subscription
- Verifica autenticazione
- Verifica formattazione dati

### 2. UserSubscriptionModelTest (15 test)
- Test metodi User model
- Verifica calcolo storage
- Verifica limiti

### 3. SubscriptionLimitsMiddlewareTest (5 test)
- Test middleware limiti
- Verifica superadmin bypass
- Verifica downgrade automatico

### 4. LibraryLimitsTest (4 test)
- Test limiti librerie API
- Test limiti librerie web

### 5. SyncLimitsTest (5 test)
- Test limiti durante sync
- Verifica stima storage
- Verifica dry run

### 6. StorageCalculationTest (6 test)
- Test calcolo storage
- Verifica inclusione/esclusione file
- Verifica gestione errori

### 7. SubscriptionConfigTest (7 test)
- Test configurazione
- Verifica limiti tier
- Verifica pricing

### 8. SubscriptionIntegrationTest (4 test)
- Test integrazione end-to-end
- Test upgrade subscription
- Test flussi completi

**Totale: ~54 test**

## Troubleshooting

### Error: Factory not found
Assicurati che le factory siano create:
- `database/factories/UserFactory.php`
- `database/factories/LibraryFactory.php`
- `database/factories/UserBookFactory.php`
- `database/factories/BookFileFactory.php`
- `database/factories/DeviceFactory.php`

### Error: Config not found
Verifica che `config/subscription.php` esista e sia valido.

### Error: Migration failed
Esegui le migration:
```bash
php artisan migrate
```

### Error: Database connection
Verifica che `phpunit.xml` abbia:
```xml
<env name="DB_CONNECTION" value="sqlite"/>
<env name="DB_DATABASE" value=":memory:"/>
```

## Coverage Target

- SubscriptionController: 100%
- User model subscription methods: 100%
- CheckSubscriptionLimits middleware: 100%
- LibraryController limit checks: 100%
- SyncController limit checks: 100%

## Note

- Tutti i test sono isolati (RefreshDatabase)
- Database SQLite in-memory per velocità
- Config mockato per controllare limiti
- Factory create per tutti i modelli necessari
