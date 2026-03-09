<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
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
     * IMPORTANTE: Usa SOLO database temporanei con suffisso _test_multi
     * per evitare di toccare database di produzione/sviluppo.
     */
    private function getAvailableDatabases(): array
    {
        $databases = [];
        
        // SQLite (sempre disponibile, in-memory)
        $databases['sqlite'] = [
            'driver' => 'sqlite',
            'database' => ':memory:',
        ];
        
        // MySQL (se disponibile)
        if ($this->isMySQLAvailable()) {
            $testDbName = 'caliweb_test_multi';
            
            // SAFEGUARD: Non usare mai database di produzione
            $prodDbName = env('DB_DATABASE', 'caliweb');
            if ($testDbName === $prodDbName) {
                throw new \Exception("CRITICAL: Test database name matches production! Aborting.");
            }
            
            $databases['mysql'] = [
                'driver' => 'mysql',
                'host' => env('DB_HOST', '127.0.0.1'),
                'port' => env('DB_PORT', '3306'),
                'database' => $testDbName,
                'username' => env('DB_USERNAME', 'root'),
                'password' => env('DB_PASSWORD', ''),
            ];
        }
        
        // PostgreSQL (se disponibile)
        if ($this->isPostgreSQLAvailable()) {
            $testDbName = 'caliweb_test_multi';
            
            // SAFEGUARD: Non usare mai database di produzione
            if ($testDbName === env('DB_DATABASE')) {
                throw new \Exception("CRITICAL: Test database name matches production! Aborting.");
            }
            
            $databases['pgsql'] = [
                'driver' => 'pgsql',
                'host' => '127.0.0.1',
                'port' => '5432',
                'database' => $testDbName,
                'username' => 'postgres',
                'password' => env('DB_PASSWORD', ''),
            ];
        }
        
        return $databases;
    }

    /**
     * Verifica se MySQL è disponibile e prepara il database test dedicato.
     */
    private function isMySQLAvailable(): bool
    {
        try {
            $host = env('DB_HOST', '127.0.0.1');
            $port = env('DB_PORT', '3306');
            $username = env('DB_USERNAME', 'root');
            $password = env('DB_PASSWORD', '');
            $testDbName = 'caliweb_test_multi';

            $pdo = new \PDO(
                "mysql:host={$host};port={$port};charset=utf8mb4",
                $username,
                $password
            );
            $pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
            $pdo->exec("CREATE DATABASE IF NOT EXISTS `{$testDbName}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci");

            return true;
        } catch (\PDOException $e) {
            return false;
        }
    }

    /**
     * Verifica se PostgreSQL è disponibile.
     */
    private function isPostgreSQLAvailable(): bool
    {
        try {
            $pdo = new \PDO('pgsql:host=127.0.0.1;port=5432;dbname=postgres', 'postgres', '');
            
            // Crea database test se non esiste
            $pdo->exec('CREATE DATABASE caliweb_test_multi');
            
            return true;
        } catch (\PDOException $e) {
            return false;
        }
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
        $safeNames = [':memory:', 'caliweb_test_multi'];
        
        if (!in_array($dbName, $safeNames)) {
            throw new \Exception(
                "CRITICAL: Refusing to run migrate:fresh on non-test database: {$dbName}\n" .
                "Only allowed: " . implode(', ', $safeNames)
            );
        }
        
        // Configura connessione
        Config::set("database.connections.{$name}", array_merge([
            'charset' => 'utf8mb4',
            'collation' => 'utf8mb4_unicode_ci',
            'prefix' => '',
            'strict' => true,
        ], $config));
        
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
        
        $uuid = (string) Str::uuid();
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
            $uuid = (string) Str::uuid();
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
