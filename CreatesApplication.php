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
        $this->ensurePostgresCliOnPathIfNeeded();
        // Default to an isolated SQLite DB only when the runner did not
        // explicitly request a concrete engine such as pgsql/mysql.
        $this->forceDedicatedTestingDatabaseIfNeeded();

        $app = require __DIR__.'/../html/bootstrap/app.php';

        $app->make(Kernel::class)->bootstrap();

        return $app;
    }

    protected function ensurePostgresCliOnPathIfNeeded(): void
    {
        $requestedDriver = getenv('DB_CONNECTION') ?: ($_ENV['DB_CONNECTION'] ?? $_SERVER['DB_CONNECTION'] ?? null);
        if (!is_string($requestedDriver) || strtolower($requestedDriver) !== 'pgsql') {
            return;
        }

        $currentPath = getenv('PATH') ?: ($_ENV['PATH'] ?? $_SERVER['PATH'] ?? '');
        $updatedPath = static::resolvePostgresCliPath($currentPath);
        if ($updatedPath === null || $updatedPath === $currentPath) {
            return;
        }

        putenv('PATH=' . $updatedPath);
        $_ENV['PATH'] = $updatedPath;
        $_SERVER['PATH'] = $updatedPath;
    }

    public static function resolvePostgresCliPath(?string $currentPath, ?array $candidateDirs = null): ?string
    {
        $currentPath = (string) ($currentPath ?? '');
        $segments = array_values(array_filter(explode(PATH_SEPARATOR, $currentPath), static fn ($segment) => $segment !== ''));
        foreach ($segments as $segment) {
            if (is_executable(rtrim($segment, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . 'psql')) {
                return $currentPath;
            }
        }

        $candidateDirs ??= [
            '/Applications/Postgres.app/Contents/Versions/latest/bin',
            '/Applications/Postgres.app/Contents/Versions/18/bin',
            '/Applications/Postgres.app/Contents/Versions/17/bin',
            '/Applications/Postgres.app/Contents/Versions/16/bin',
            '/opt/homebrew/bin',
            '/usr/local/bin',
        ];

        foreach ($candidateDirs as $dir) {
            $normalized = rtrim((string) $dir, DIRECTORY_SEPARATOR);
            if ($normalized === '' || !is_executable($normalized . DIRECTORY_SEPARATOR . 'psql')) {
                continue;
            }

            if (in_array($normalized, $segments, true)) {
                return $currentPath;
            }

            return $normalized . ($currentPath !== '' ? PATH_SEPARATOR . $currentPath : '');
        }

        return $currentPath;
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
