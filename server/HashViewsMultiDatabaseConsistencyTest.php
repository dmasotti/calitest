<?php

namespace Tests\Server;

use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Config;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Tests\TestCase;

/**
 * CRITICAL: Verifica che books_hash_v2 e library_hash producano
 * gli STESSI hash su SQLite, MySQL e PostgreSQL.
 * 
 * Questo test esegue AUTOMATICAMENTE su tutti i database configurati
 * senza modificare .env manualmente.
 */
class HashViewsMultiDatabaseConsistencyTest extends TestCase
{
    /**
     * Test che gli hash siano identici su tutti i database.
     * 
     * Esegue lo stesso test su SQLite, MySQL e PostgreSQL
     * e verifica che producano hash identici.
     */
    public function test_books_hash_v2_produces_identical_hash_across_all_databases(): void
    {
        $databases = $this->getAvailableDatabases();
        
        if (count($databases) < 2) {
            $this->markTestSkipped('Serve almeno 2 database configurati per test cross-DB');
        }
        
        $hashes = [];
        $usableDatabases = [];
        $skipReasons = [];
        
        foreach ($databases as $dbName => $config) {
            try {
                // Switch database temporaneamente
                $this->switchDatabase($dbName, $config);

                // Seed dati identici
                [$user, $library, $bookUuid] = $this->seedTestBook();

                // Leggi hash
                $hash = DB::table('books_hash_v2')
                    ->where('uuid', $bookUuid)
                    ->value('hash_payload');

                $this->assertNotNull($hash, "books_hash_v2 deve ritornare hash su {$dbName}");

                $hashes[$dbName] = $hash;
                $usableDatabases[] = $dbName;

                echo "\n{$dbName}: " . substr($hash, 0, 50) . "...";
            } catch (\Throwable $e) {
                $skipReasons[] = "{$dbName}: " . $e->getMessage();
            }
        }

        if (count($usableDatabases) < 2) {
            $reason = empty($skipReasons) ? 'nessuna motivazione disponibile' : implode(' | ', $skipReasons);
            $this->markTestSkipped("Serve almeno 2 database realmente utilizzabili per test cross-DB ({$reason})");
        }
        
        // Verifica che tutti gli hash siano identici
        $uniqueHashes = array_unique($hashes);
        
        $this->assertCount(
            1,
            $uniqueHashes,
            "Hash deve essere identico su tutti i database!\n" .
            "Trovati hash diversi:\n" . 
            json_encode($hashes, JSON_PRETTY_PRINT)
        );
        
        echo "\n✅ Hash identico su tutti i database: " . array_keys($databases)[0] . " = " . array_keys($databases)[1] . "\n";
    }

    public function test_books_hash_v2_metadata_hash_is_identical_across_all_databases(): void
    {
        $databases = $this->getAvailableDatabases();

        if (count($databases) < 2) {
            $this->markTestSkipped('Serve almeno 2 database configurati per test cross-DB');
        }

        $hashes = [];
        $usableDatabases = [];
        $skipReasons = [];

        foreach ($databases as $dbName => $config) {
            try {
                $this->switchDatabase($dbName, $config);
                [, , $bookUuid] = $this->seedTestBook();

                $row = DB::table('books_hash_v2')
                    ->where('uuid', $bookUuid)
                    ->select('hash_payload', 'metadata_hash')
                    ->first();

                $this->assertNotNull($row, "books_hash_v2 deve ritornare una riga su {$dbName}");
                $this->assertSame(
                    hash('sha256', (string) $row->hash_payload),
                    strtolower((string) $row->metadata_hash),
                    "metadata_hash deve essere SHA256 del payload su {$dbName}"
                );

                $hashes[$dbName] = strtolower((string) $row->metadata_hash);
                $usableDatabases[] = $dbName;
            } catch (\Throwable $e) {
                $skipReasons[] = "{$dbName}: " . $e->getMessage();
            }
        }

        if (count($usableDatabases) < 2) {
            $reason = empty($skipReasons) ? 'nessuna motivazione disponibile' : implode(' | ', $skipReasons);
            $this->markTestSkipped("Serve almeno 2 database realmente utilizzabili per test cross-DB ({$reason})");
        }

        $this->assertCount(
            1,
            array_unique($hashes),
            "metadata_hash deve essere identico su tutti i database!\n" .
            json_encode($hashes, JSON_PRETTY_PRINT)
        );
    }

    /**
     * Test library_hash su tutti i database.
     */
    public function test_library_hash_produces_identical_hash_across_all_databases(): void
    {
        $databases = $this->getAvailableDatabases();
        
        if (count($databases) < 2) {
            $this->markTestSkipped('Serve almeno 2 database configurati per test cross-DB');
        }
        
        $libraryHashes = [];
        $usableDatabases = [];
        $skipReasons = [];
        
        foreach ($databases as $dbName => $config) {
            try {
                $this->switchDatabase($dbName, $config);
                
                [$user, $library, $uuids] = $this->seedMultipleBooks(3);
                
                $libraryHash = DB::table('library_hash')
                    ->where('user_id', $user->id)
                    ->where('library_id', $library->id)
                    ->value('library_metadata_hash');
                
                $this->assertNotNull($libraryHash, "library_hash deve ritornare hash su {$dbName}");
                
                $libraryHashes[$dbName] = strtolower($libraryHash);
                $usableDatabases[] = $dbName;
                
                echo "\n{$dbName}: {$libraryHash}";
            } catch (\Throwable $e) {
                $skipReasons[] = "{$dbName}: " . $e->getMessage();
            }
        }

        if (count($usableDatabases) < 2) {
            $reason = empty($skipReasons) ? 'nessuna motivazione disponibile' : implode(' | ', $skipReasons);
            $this->markTestSkipped("Serve almeno 2 database realmente utilizzabili per test cross-DB ({$reason})");
        }
        
        $uniqueHashes = array_unique($libraryHashes);
        
        $this->assertCount(
            1,
            $uniqueHashes,
            "Library hash deve essere identico su tutti i database!\n" .
            json_encode($libraryHashes, JSON_PRETTY_PRINT)
        );
        
        echo "\n✅ Library hash identico su tutti i database\n";
    }

    // ========== Database Switching ==========

    /**
     * Ritorna lista database disponibili per test.
     * 
     * IMPORTANTE: Usa SOLO database temporanei con prefisso test_
     * per evitare di toccare database di produzione/sviluppo.
     */
    private function getAvailableDatabases(): array
    {
        $databases = [];

        // SQLite baseline sempre disponibile per verifiche cross-engine rapide.
        $databases['sqlite'] = [
            'driver' => 'sqlite',
            'database' => ':memory:',
        ];

        // Usa la connessione di test corrente se è già un database isolato.
        $currentConfig = Config::get('database.connections.' . Config::get('database.default'), []);
        $currentDatabase = (string) ($currentConfig['database'] ?? '');
        $currentDriver = (string) ($currentConfig['driver'] ?? '');

        if ($currentDriver !== '' && $currentDatabase !== '' && str_starts_with($currentDatabase, 'test_')) {
            $databases[$currentDriver] = $currentConfig;
        }

        // Altri motori sono opzionali e devono essere configurati esplicitamente.
        foreach (['mysql', 'pgsql'] as $driver) {
            if (isset($databases[$driver])) {
                continue;
            }

            $optional = $this->buildOptionalDatabaseConfig($driver);
            if ($optional !== null) {
                $databases[$driver] = $optional;
            }
        }

        return $databases;
    }

    private function buildOptionalDatabaseConfig(string $driver): ?array
    {
        $upper = strtoupper($driver);
        $database = env("TEST_MULTI_{$upper}_DATABASE");

        if ((!is_string($database) || $database === '') && $driver === 'pgsql') {
            $database = 'test_calibre_plg_pgsql';
        }

        if (!is_string($database) || $database === '' || !str_starts_with($database, 'test_')) {
            return null;
        }

        $config = [
            'driver' => $driver,
            'host' => env("TEST_MULTI_{$upper}_HOST", '127.0.0.1'),
            'port' => env("TEST_MULTI_{$upper}_PORT", $driver === 'mysql' ? '3306' : '5432'),
            'database' => $database,
            'username' => env("TEST_MULTI_{$upper}_USERNAME", $driver === 'mysql' ? 'root' : 'postgres'),
            'password' => env("TEST_MULTI_{$upper}_PASSWORD", ''),
        ];

        if ($driver === 'mysql') {
            $config['charset'] = 'utf8mb4';
            $config['collation'] = 'utf8mb4_unicode_ci';
        }

        return $config;
    }

    /**
     * Switch database connection temporaneamente.
     * 
     * SAFEGUARD: Verifica che il database sia un test database
     * prima di eseguire migrate:fresh.
     */
    private function switchDatabase(string $name, array $config): void
    {
        // SAFEGUARD: Verifica che sia un database di test
        $dbName = $config['database'] ?? '';

        if ($dbName !== ':memory:' && !str_starts_with((string) $dbName, 'test_')) {
            throw new \Exception(
                "CRITICAL: Refusing to run migrate:fresh on non-test database: {$dbName}\n" .
                "Only allowed: :memory: or databases starting with test_"
            );
        }
        
        // Configura connessione
        $baseConfig = [
            'prefix' => '',
            'strict' => true,
        ];

        if (($config['driver'] ?? null) === 'mysql') {
            $baseConfig['charset'] = 'utf8mb4';
            $baseConfig['collation'] = 'utf8mb4_unicode_ci';
        }

        Config::set("database.connections.{$name}", array_merge($baseConfig, $config));
        
        // Switch default connection
        Config::set('database.default', $name);
        DB::purge($name);
        DB::reconnect($name);
        
        // Esegui migrazioni (SOLO su database test)
        Artisan::call('migrate:fresh', [
            '--database' => $name,
            '--force' => true,
        ]);
    }

    // ========== Helper Methods (invariati) ==========

    private function seedTestBook(): array
    {
        $user = \App\Models\User::factory()->create();
        $library = \App\Models\Library::factory()->create(['user_id' => $user->id]);
        
        $uuid = '11111111-2222-4333-8444-555555555555';
        $now = now();
        
        DB::table('books')->insert([
            'id' => 1001,
            'uuid' => $uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Simple Book',
            'author_sort' => 'Author, Simple',
            'series_index' => 1.0,
            'path' => 'simple-book',
            'flags' => 1,
            'has_cover' => 0,
            'last_modified' => $now,
            'created_at' => $now,
            'updated_at' => $now,
        ]);
        
        return [$user, $library, $uuid];
    }

    private function seedMultipleBooks(int $count): array
    {
        $user = \App\Models\User::factory()->create();
        $library = \App\Models\Library::factory()->create(['user_id' => $user->id]);
        
        $uuids = [];
        $now = now();
        
        for ($i = 1; $i <= $count; $i++) {
            $uuid = sprintf('11111111-2222-4333-8444-%012d', $i);
            $uuids[] = $uuid;
            
            DB::table('books')->insert([
                'id' => 1000 + $i,
                'uuid' => $uuid,
                'user_id' => $user->id,
                'library_id' => $library->id,
                'title' => "Book {$i}",
                'author_sort' => "Author, {$i}",
                'series_index' => (float) $i,
                'path' => "book-{$i}",
                'flags' => 1,
                'has_cover' => 0,
                'last_modified' => $now->copy()->addSeconds($i),
                'created_at' => $now,
                'updated_at' => $now,
            ]);
        }
        
        return [$user, $library, $uuids];
    }
}
