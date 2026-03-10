<?php

namespace Tests;

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
        // Default to an isolated SQLite DB only when the runner did not
        // explicitly request a concrete engine such as pgsql/mysql.
        $this->forceDedicatedTestingDatabaseIfNeeded();

        $app = require __DIR__.'/../html/bootstrap/app.php';

        $app->make(Kernel::class)->bootstrap();

        return $app;
    }

    private function forceDedicatedTestingDatabaseIfNeeded(): void
    {
        $requestedDriver = getenv('DB_CONNECTION') ?: ($_ENV['DB_CONNECTION'] ?? $_SERVER['DB_CONNECTION'] ?? null);
        if (is_string($requestedDriver) && $requestedDriver !== '' && strtolower($requestedDriver) !== 'sqlite') {
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
}
