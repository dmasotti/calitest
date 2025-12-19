# Coverage Test Suite - Subscription e Freemium

## Panoramica

Suite completa di test per verificare il funzionamento corretto di subscription, limiti freemium e API correlate.

## File di Test

### 1. `SubscriptionApiTest.php` (8 test)
- ✅ GET /api/subscription - Status subscription
- ✅ GET /api/subscription - Richiede autenticazione
- ✅ GET /api/subscription - Percentuali usage corrette
- ✅ GET /api/subscription/pricing - Restituisce tutti i tier
- ✅ GET /api/subscription/pricing - Pricing formattato correttamente
- ✅ Subscription status con subscription scaduta
- ✅ Subscription status con subscription attiva

### 2. `UserSubscriptionModelTest.php` (15 test)
- ✅ getSubscriptionLimits() restituisce limiti corretti
- ✅ canCreateLibrary() quando sotto limite
- ✅ canCreateLibrary() quando al limite
- ✅ canAddBook() quando sotto limite
- ✅ canAddBook() quando al limite
- ✅ getStorageUsedBytes() calcola correttamente
- ✅ getStorageUsedMB() restituisce valore corretto
- ✅ canAddStorage() quando sotto limite
- ✅ canAddStorage() quando supererebbe limite
- ✅ canAddStorage() considera storage esistente
- ✅ hasFeature() per feature disponibile
- ✅ hasFeature() per feature non disponibile
- ✅ isSubscriptionActive() per free tier
- ✅ isSubscriptionActive() per subscription scaduta
- ✅ isSubscriptionActive() per subscription cancellata
- ✅ Storage conta solo file uploaded

### 3. `SubscriptionLimitsMiddlewareTest.php` (5 test)
- ✅ Middleware permette creazione libreria quando sotto limite
- ✅ Middleware blocca creazione libreria quando al limite
- ✅ Middleware permette superadmin bypass
- ✅ Middleware downgrade subscription scaduta
- ✅ Middleware non downgrade subscription attiva

### 4. `LibraryLimitsTest.php` (4 test)
- ✅ POST /api/libraries - Success quando sotto limite
- ✅ POST /api/libraries - Fallisce quando al limite
- ✅ Basic tier può creare 3 librerie
- ✅ POST /library (web) - Stesso enforcement limiti

### 5. `SyncLimitsTest.php` (5 test)
- ✅ POST /api/sync - Blocca quando limite libri raggiunto
- ✅ POST /api/sync - Blocca quando limite storage raggiunto
- ✅ POST /api/sync - Permette quando sotto limiti
- ✅ POST /api/sync - Dry run non applica limiti
- ✅ Sync stima storage correttamente da files

### 6. `StorageCalculationTest.php` (6 test)
- ✅ Storage include file ebook
- ✅ Storage include multipli file ebook
- ✅ Storage include cover locali
- ✅ Storage esclude cover Cloudflare
- ✅ Storage esclude file non uploaded
- ✅ Storage gestisce file cover mancanti

### 7. `SubscriptionConfigTest.php` (7 test)
- ✅ Config subscription caricato correttamente
- ✅ Free tier ha limiti corretti
- ✅ Basic tier ha limiti corretti
- ✅ Pro tier ha limiti corretti
- ✅ Enterprise tier ha limiti corretti
- ✅ Pricing configurato correttamente
- ✅ Trial days config esiste
- ✅ Default tier config esiste

### 8. `SubscriptionIntegrationTest.php` (4 test)
- ✅ Utente free raggiunge tutti i limiti
- ✅ Upgrade da free a basic sblocca limiti
- ✅ Storage limit enforcement durante sync
- ✅ Subscription status riflette usage corrente

## Totale Test: ~54 test

## Esecuzione

### Tutti i test server
```bash
php artisan test --testsuite=Server
```

### Con coverage
```bash
php artisan test --testsuite=Server --coverage
```

### Con coverage HTML
```bash
php artisan test --testsuite=Server --coverage-html=coverage/server
```

### Singolo file
```bash
php artisan test tests/server/SubscriptionApiTest.php
```

### Con verbose
```bash
php artisan test --testsuite=Server -v
```

## Coverage Target

- **SubscriptionController**: 100%
- **User model subscription methods**: 100%
- **CheckSubscriptionLimits middleware**: 100%
- **LibraryController limit checks**: 100%
- **SyncController limit checks**: 100%
- **Config subscription**: 100%

## Note

- Tutti i test usano database SQLite in-memory
- Factory create per: User, Library, UserBook, BookFile, Device
- Test isolati con `RefreshDatabase`
- Mock config per controllare limiti
