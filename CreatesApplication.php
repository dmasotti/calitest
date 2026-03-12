<?php

namespace Tests;

use App\Support\PostgresCliBootstrap;
use Illuminate\Contracts\Console\Kernel;

trait CreatesApplication
{
    /**
     * Creates the application.
     *
     * @return \Illuminate\Foundation\Application
     */
    public function createApplication()
    {
        $this->ensurePostgresCliOnPathIfNeeded();
        // Default to an isolated SQLite DB only when the runner did not
        // explicitly request a concrete engine such as pgsql/mysql.
        $this->forceDedicatedTestingDatabaseIfNeeded();
        $this->guardAgainstNonTestDatabases();

        $app = require __DIR__.'/../html/bootstrap/app.php';

        $app->make(Kernel::class)->bootstrap();

        return $app;
    }

    protected function ensurePostgresCliOnPathIfNeeded(): void
    {
        PostgresCliBootstrap::ensureOnPathIfNeeded();
    }

    public static function resolvePostgresCliPath(?string $currentPath, ?array $candidateDirs = null): ?string
    {
        return PostgresCliBootstrap::resolvePathWithPsql($currentPath, $candidateDirs);
    }

    private function forceDedicatedTestingDatabaseIfNeeded(): void
    {
        $requestedDriver = getenv('DB_CONNECTION') ?: ($_ENV['DB_CONNECTION'] ?? $_SERVER['DB_CONNECTION'] ?? null);
        $forceSqlite = getenv('FORCE_TEST_SQLITE') === '1';
        if (!$forceSqlite && is_string($requestedDriver) && $requestedDriver !== '' && strtolower($requestedDriver) !== 'sqlite') {
            return;
        }

        // Use a dedicated sqlite file per test process to avoid cross-run corruption
        // and "table migrations already exists" collisions.
        $token = getenv('TEST_TOKEN') ?: ('pid' . getmypid());
        $dbPath = '/tmp/calimob_server_test_' . preg_replace('/[^A-Za-z0-9_\-]/', '_', (string) $token) . '.sqlite';

        // Reset file only once per process bootstrap. RefreshDatabase then manages
        // schema lifecycle without losing tables between test methods.
        static $bootstrapped = [];
        if (!isset($bootstrapped[$dbPath])) {
            if (is_file($dbPath)) {
                @unlink($dbPath);
            }
            touch($dbPath);
            $bootstrapped[$dbPath] = true;
        } elseif (!is_file($dbPath)) {
            touch($dbPath);
        }

        $env = [
            'APP_ENV' => 'testing',
            'DB_CONNECTION' => 'sqlite',
            'DB_DATABASE' => $dbPath,
            'SESSION_DRIVER' => 'array',
            'CACHE_STORE' => 'array',
            'QUEUE_CONNECTION' => 'sync',
        ];

        foreach ($env as $key => $value) {
            putenv($key.'='.$value);
            $_ENV[$key] = $value;
            $_SERVER[$key] = $value;
        }
    }

    private function guardAgainstNonTestDatabases(): void
    {
        $driver = strtolower((string) ($this->readEnvValue('DB_CONNECTION') ?: 'sqlite'));
        $database = (string) ($this->readEnvValue('DB_DATABASE') ?: '');

        if ($driver === 'sqlite') {
            return;
        }

        if ($database === '') {
            throw new \RuntimeException(sprintf(
                'Refusing to bootstrap PHPUnit with DB_CONNECTION=%s and empty DB_DATABASE. Use an isolated testing DB.',
                $driver
            ));
        }

        if ($this->isAllowedTestingDatabase($database)) {
            return;
        }

        throw new \RuntimeException(sprintf(
            'Refusing to bootstrap PHPUnit against non-test database "%s" (driver=%s). Allowed non-SQLite DBs must start with "test_".',
            $database,
            $driver
        ));
    }

    private function isAllowedTestingDatabase(string $database): bool
    {
        $normalized = strtolower(trim($database));

        if ($normalized === '') {
            return false;
        }

        return str_starts_with($normalized, 'test_');
    }

    private function readEnvValue(string $key): ?string
    {
        $value = getenv($key);
        if ($value !== false && $value !== null && $value !== '') {
            return (string) $value;
        }

        foreach ([&$_ENV, &$_SERVER] as $source) {
            if (isset($source[$key]) && $source[$key] !== '') {
                return (string) $source[$key];
            }
        }

        return null;
    }
}
