# Come Ho Creato la Suite di Test

Spiegazione dettagliata del processo seguito per creare la suite completa di test.

---

## 1. Analisi Test Esistenti

### Step 1.1: Ho studiato i test esistenti
Ho letto `tests/Feature/Auth/AuthenticationTest.php` per capire il pattern:

```php
class AuthenticationTest extends TestCase
{
    use RefreshDatabase;  // ← Reset database per ogni test
    
    public function test_login_screen_can_be_rendered(): void
    {
        $response = $this->get('/login');
        $response->assertStatus(200);
    }
    
    public function test_users_can_authenticate(): void
    {
        $user = User::factory()->create();  // ← Usa factory
        $response = $this->post('/login', [...]);
        $this->assertAuthenticated();
    }
}
```

**Pattern identificato**:
- Estende `Tests\TestCase`
- Usa `RefreshDatabase` per isolamento
- Usa `User::factory()->create()` per creare dati
- Usa `$this->get()`, `$this->post()`, `$this->getJson()` per chiamate HTTP
- Usa `assertStatus()`, `assertJson()`, `assertDatabaseHas()` per verifiche

---

## 2. Identificazione Dipendenze

### Step 2.1: Ho verificato quali Factory esistevano
```bash
# Ho cercato factory esistenti
glob_file_search: *Factory.php in database/factories
```

**Risultato**: Solo `UserFactory.php` esisteva.

### Step 2.2: Ho identificato modelli necessari per i test
Dai test che volevo creare, servivano:
- ✅ `User` - già aveva factory
- ❌ `Library` - serviva factory
- ❌ `UserBook` - serviva factory  
- ❌ `BookFile` - serviva factory
- ❌ `Device` - serviva factory

---

## 3. Creazione Factory

### Step 3.1: Ho letto i modelli per capire struttura
Ho letto `app/Models/Library.php`:
```php
protected $fillable = [
    'user_id',
    'name',
    'description',
    'calibre_library_id',
    'stats_cached',
];
```

### Step 3.2: Ho creato LibraryFactory.php
```php
class LibraryFactory extends Factory
{
    protected $model = Library::class;
    
    public function definition(): array
    {
        return [
            'user_id' => User::factory(),  // ← Relazione automatica
            'name' => fake()->words(3, true) . ' Library',
            'description' => fake()->sentence(),
            'calibre_library_id' => fake()->uuid(),
            'stats_cached' => false,
        ];
    }
}
```

**Pattern**:
- `protected $model` - specifica il modello
- `definition()` - ritorna array con dati fake
- `User::factory()` - crea relazione automaticamente

### Step 3.3: Ho ripetuto per altri modelli
- `UserBookFactory` - con `user_id`, `library_id`, `calibre_book_id`, `custom_metadata`
- `BookFileFactory` - con `book_id`, `uncompressed_size`, `is_uploaded`
- `DeviceFactory` - con `user_id`, `device_uuid`, `platform`

---

## 4. Strutturazione Test

### Step 4.1: Ho organizzato per funzionalità
Invece di un unico file gigante, ho creato file separati per ogni area:

```
tests/server/
├── SubscriptionApiTest.php          # Test endpoint API
├── UserSubscriptionModelTest.php    # Test metodi User model
├── SubscriptionLimitsMiddlewareTest.php  # Test middleware
├── LibraryLimitsTest.php            # Test limiti librerie
├── SyncLimitsTest.php               # Test limiti sync
├── StorageCalculationTest.php       # Test calcolo storage
├── SubscriptionConfigTest.php       # Test configurazione
└── SubscriptionIntegrationTest.php  # Test integrazione
```

### Step 4.2: Ho seguito il pattern Arrange-Act-Assert

Ogni test segue questo pattern:

```php
public function test_something(): void
{
    // ARRANGE: Setup dati di test
    $user = User::factory()->create(['subscription_tier' => 'free']);
    Sanctum::actingAs($user);
    
    // ACT: Esegui azione da testare
    $response = $this->getJson('/api/subscription');
    
    // ASSERT: Verifica risultato
    $response->assertStatus(200)
        ->assertJson(['subscription' => ['tier' => 'free']]);
}
```

---

## 5. Creazione Test Specifici

### Step 5.1: Test API Endpoints

**Esempio**: `SubscriptionApiTest.php`

```php
public function test_get_subscription_status_returns_correct_data(): void
{
    // 1. Creo utente con subscription free
    $user = User::factory()->create([
        'subscription_tier' => 'free',
        'subscription_status' => 'active',
    ]);
    
    // 2. Autentico con Sanctum (per API)
    Sanctum::actingAs($user);
    
    // 3. Chiamo endpoint
    $response = $this->getJson('/api/subscription');
    
    // 4. Verifico struttura JSON
    $response->assertStatus(200)
        ->assertJsonStructure([
            'subscription' => ['tier', 'status', 'is_active'],
            'limits' => ['max_libraries', 'max_books', 'max_storage_mb'],
            'usage' => ['libraries', 'books', 'storage_mb'],
        ]);
    
    // 5. Verifico valori specifici
    $response->assertJson([
        'subscription' => ['tier' => 'free'],
        'limits' => ['max_libraries' => 1],
    ]);
}
```

**Perché questo approccio**:
- Testa il comportamento reale dell'endpoint
- Verifica struttura JSON (importante per API)
- Verifica valori attesi
- Isolato (RefreshDatabase)

### Step 5.2: Test Model Methods

**Esempio**: `UserSubscriptionModelTest.php`

```php
public function test_can_create_library_when_under_limit(): void
{
    // ARRANGE
    $user = User::factory()->create(['subscription_tier' => 'free']);
    // Nessuna libreria creata ancora
    
    // ACT
    $canCreate = $user->canCreateLibrary();
    
    // ASSERT
    $this->assertTrue($canCreate);
}

public function test_cannot_create_library_when_at_limit(): void
{
    // ARRANGE
    $user = User::factory()->create(['subscription_tier' => 'free']);
    Library::factory()->create(['user_id' => $user->id]); // Crea 1 libreria (max per free)
    
    // ACT
    $canCreate = $user->canCreateLibrary();
    
    // ASSERT
    $this->assertFalse($canCreate);
}
```

**Perché questo approccio**:
- Testa logica business direttamente
- Testa sia caso positivo che negativo
- Veloce (no HTTP overhead)

### Step 5.3: Test Middleware

**Esempio**: `SubscriptionLimitsMiddlewareTest.php`

```php
public function test_middleware_blocks_library_creation_when_at_limit(): void
{
    // ARRANGE
    $user = User::factory()->create(['subscription_tier' => 'free']);
    Library::factory()->create(['user_id' => $user->id]); // Al limite
    Sanctum::actingAs($user);
    
    // ACT: Provo a creare seconda libreria
    $response = $this->postJson('/api/libraries', [
        'name' => 'Second Library',
        'calibre_library_id' => 'test-uuid',
    ]);
    
    // ASSERT: Deve essere bloccato
    $response->assertStatus(403)
        ->assertJson([
            'error' => 'Limite librerie raggiunto (1). Upgrade richiesto.',
            'upgrade_required' => true,
        ]);
}
```

**Perché questo approccio**:
- Testa middleware nel contesto reale (HTTP request)
- Verifica risposta HTTP corretta
- Verifica messaggio di errore

### Step 5.4: Test Storage Calculation

**Esempio**: `StorageCalculationTest.php`

```php
public function test_storage_includes_ebook_files(): void
{
    // ARRANGE: Creo utente con libro e file
    $user = User::factory()->create();
    $library = Library::factory()->create(['user_id' => $user->id]);
    $userBook = UserBook::factory()->create([
        'user_id' => $user->id,
        'library_id' => $library->id,
    ]);
    
    // Creo file da 10 MB
    BookFile::factory()->create([
        'book_id' => $userBook->id,
        'uncompressed_size' => 10 * 1024 * 1024, // 10 MB
        'is_uploaded' => true,
    ]);
    
    // ACT: Calcolo storage
    $storageMB = $user->getStorageUsedMB();
    
    // ASSERT: Deve essere 10 MB
    $this->assertEquals(10.0, $storageMB);
}
```

**Perché questo approccio**:
- Testa calcolo complesso (somma file + cover)
- Verifica logica business critica
- Testa edge cases (file mancanti, Cloudflare vs local)

---

## 6. Setup Config nei Test

### Step 6.1: Ho mockato la config in setUp()

```php
protected function setUp(): void
{
    parent::setUp();
    
    // Mock config per controllare limiti nei test
    Config::set('subscription.tiers', [
        'free' => [
            'max_libraries' => 1,
            'max_books' => 50,
            'max_storage_mb' => 500,
        ],
    ]);
}
```

**Perché**:
- Controllo totale sui limiti nei test
- Test indipendenti dalla config reale
- Facile cambiare limiti per test specifici

---

## 7. Test di Integrazione

### Step 7.1: Ho creato test end-to-end

**Esempio**: `SubscriptionIntegrationTest.php`

```php
public function test_free_user_reaches_all_limits(): void
{
    $user = User::factory()->create(['subscription_tier' => 'free']);
    Sanctum::actingAs($user);
    
    // 1. Creo libreria (OK)
    $response = $this->postJson('/api/libraries', [...]);
    $response->assertStatus(201);
    
    // 2. Provo seconda libreria (FAIL)
    $response = $this->postJson('/api/libraries', [...]);
    $response->assertStatus(403);
    
    // 3. Creo 50 libri (al limite)
    UserBook::factory()->count(50)->create([...]);
    
    // 4. Provo sync nuovo libro (FAIL)
    $response = $this->postJson('/api/sync', [...]);
    $response->assertStatus(403);
    
    // 5. Verifico status mostra limiti raggiunti
    $response = $this->getJson('/api/subscription');
    $data = $response->json();
    $this->assertEquals(100.0, $data['usage_percentages']['libraries']);
}
```

**Perché questo approccio**:
- Testa flusso completo end-to-end
- Verifica interazione tra componenti
- Simula scenario reale utente

---

## 8. Autenticazione nei Test API

### Step 8.1: Ho usato Sanctum per API

```php
// Per test API
Sanctum::actingAs($user);
$response = $this->getJson('/api/subscription');

// Per test web
$this->actingAs($user);
$response = $this->post('/library', [...]);
```

**Differenza**:
- `Sanctum::actingAs()` - per route API (Sanctum token)
- `$this->actingAs()` - per route web (session)

---

## 9. Verifiche Assert

### Step 9.1: Ho usato assert appropriati

```php
// Status HTTP
$response->assertStatus(200);
$response->assertStatus(403);

// Struttura JSON
$response->assertJsonStructure(['subscription' => ['tier']]);

// Valori JSON
$response->assertJson(['subscription' => ['tier' => 'free']]);

// Database
$this->assertDatabaseHas('libraries', ['user_id' => $user->id]);

// Valori diretti
$this->assertTrue($user->canCreateLibrary());
$this->assertEquals(10.0, $storageMB);
```

---

## 10. Edge Cases

### Step 10.1: Ho testato casi limite

```php
// Test: Storage esclude file non uploaded
public function test_storage_excludes_non_uploaded_files(): void
{
    // Crea file uploaded (conta) + non uploaded (non conta)
    BookFile::factory()->create(['is_uploaded' => true]);
    BookFile::factory()->create(['is_uploaded' => false]);
    
    // Verifica che solo uploaded conta
    $this->assertEquals(5.0, $user->getStorageUsedMB());
}

// Test: File cover mancanti non causano errori
public function test_storage_handles_missing_cover_files(): void
{
    $userBook->cover_optimized_path = 'images/covers/nonexistent.jpg';
    
    // Non deve lanciare eccezione
    $storageMB = $user->getStorageUsedMB();
    $this->assertEquals(0.0, $storageMB);
}
```

---

## 11. Organizzazione File

### Step 11.1: Ho creato struttura logica

```
tests/server/
├── SubscriptionApiTest.php              # API endpoints
├── UserSubscriptionModelTest.php        # Model methods
├── SubscriptionLimitsMiddlewareTest.php  # Middleware
├── LibraryLimitsTest.php                # Library limits
├── SyncLimitsTest.php                   # Sync limits
├── StorageCalculationTest.php           # Storage logic
├── SubscriptionConfigTest.php            # Config validation
├── SubscriptionIntegrationTest.php      # E2E tests
├── README.md                            # Overview
├── TEST_COVERAGE.md                     # Coverage details
├── RUN_TESTS.md                         # How to run
└── HOW_I_DID_IT.md                      # This file
```

**Perché questa organizzazione**:
- Facile trovare test specifici
- Ogni file ha responsabilità chiara
- Scalabile (facile aggiungere nuovi test)

---

## 12. Configurazione phpunit.xml

### Step 12.1: Ho aggiunto testsuite "Server"

```xml
<testsuites>
    <testsuite name="Unit">
        <directory>tests/Unit</directory>
    </testsuite>
    <testsuite name="Feature">
        <directory>tests/Feature</directory>
    </testsuite>
    <testsuite name="Server">  <!-- ← Aggiunto -->
        <directory>tests/server</directory>
    </testsuite>
</testsuites>
```

**Perché**:
- Permette di eseguire solo test server: `--testsuite=Server`
- Separazione logica dei test
- Facile escludere/includere gruppi

---

## 13. Pattern Comuni Usati

### Pattern 1: Setup Config
```php
protected function setUp(): void
{
    parent::setUp();
    Config::set('subscription.tiers', [...]); // Mock config
}
```

### Pattern 2: Creazione Dati
```php
$user = User::factory()->create(['subscription_tier' => 'free']);
$library = Library::factory()->create(['user_id' => $user->id]);
```

### Pattern 3: Test Positivo + Negativo
```php
public function test_can_do_X_when_allowed() { /* ... */ }
public function test_cannot_do_X_when_blocked() { /* ... */ }
```

### Pattern 4: Verifica Limiti
```php
// Crea dati fino al limite
Library::factory()->create(['user_id' => $user->id]);

// Prova ad andare oltre
$response = $this->postJson('/api/libraries', [...]);

// Verifica blocco
$response->assertStatus(403);
```

---

## 14. Cosa Ho Testato

### ✅ Cosa SÌ
- Endpoint API (`GET /api/subscription`, `GET /api/subscription/pricing`)
- Metodi User model (tutti i metodi subscription)
- Middleware (blocchi, bypass superadmin)
- Limit enforcement (librerie, libri, storage)
- Calcolo storage (ebook + cover locali)
- Config subscription (struttura, limiti, pricing)
- Flussi integrazione (end-to-end)

### ❌ Cosa NO (non ancora)
- Stripe integration (webhook, checkout)
- UI/Views (Blade templates)
- Email notifications
- Analytics/metriche

---

## 15. Risultato Finale

### File Creati
- **8 file di test** (~54 test totali)
- **4 factory** (Library, UserBook, BookFile, Device)
- **4 file documentazione**

### Coverage
- SubscriptionController API: ✅
- User model methods: ✅
- Middleware: ✅
- Limit enforcement: ✅
- Storage calculation: ✅

### Esecuzione
```bash
php artisan test --testsuite=Server
```

---

## Domande Frequenti

### Q: Perché RefreshDatabase?
**A**: Ogni test parte da database pulito, garantendo isolamento e risultati riproducibili.

### Q: Perché mockare la config?
**A**: Per controllare esattamente i limiti nei test, indipendentemente dalla config reale.

### Q: Perché Sanctum::actingAs() per API?
**A**: Le route API usano Sanctum token, non session. `Sanctum::actingAs()` simula token valido.

### Q: Perché test separati per ogni cosa?
**A**: Test piccoli e focalizzati sono più facili da debuggare e mantenere. Un test fallisce = un problema specifico.

### Q: Come aggiungere nuovi test?
**A**: Aggiungi nuovo metodo `public function test_qualcosa(): void` nella classe appropriata, seguendo il pattern Arrange-Act-Assert.

---

## Prossimi Passi

1. Eseguire i test: `php artisan test --testsuite=Server`
2. Verificare coverage: `php artisan test --testsuite=Server --coverage`
3. Aggiungere test mancanti se necessario
4. Integrare in CI/CD se presente
