<?php

namespace Tests\Server;

use App\Support\PostgresCliBootstrap;
use PHPUnit\Framework\TestCase;
use Tests\CreatesApplication;

class CreatesApplicationPathBootstrapTest extends TestCase
{
    public function test_shared_bootstrap_resolver_prepends_candidate_when_psql_missing(): void
    {
        $path = '/usr/bin:/bin';
        $candidate = sys_get_temp_dir() . '/pgsql-bin-' . uniqid('', true);
        mkdir($candidate, 0777, true);
        file_put_contents($candidate . '/psql', "#!/bin/sh\nexit 0\n");
        chmod($candidate . '/psql', 0755);

        try {
            $resolved = PostgresCliBootstrap::resolvePathWithPsql($path, [$candidate]);

            $this->assertSame($candidate . PATH_SEPARATOR . $path, $resolved);
        } finally {
            @unlink($candidate . '/psql');
            @rmdir($candidate);
        }
    }

    public function test_shared_bootstrap_resolver_can_be_used_for_process_env_path(): void
    {
        $candidate = sys_get_temp_dir() . '/pgsql-bin-' . uniqid('', true);
        mkdir($candidate, 0777, true);
        file_put_contents($candidate . '/psql', "#!/bin/sh\nexit 0\n");
        chmod($candidate . '/psql', 0755);

        try {
            $resolved = PostgresCliBootstrap::resolvePathWithPsql('/usr/bin:/bin', [$candidate]);
            $this->assertStringStartsWith($candidate, (string) $resolved);
        } finally {
            @unlink($candidate . '/psql');
            @rmdir($candidate);
        }
    }

    public function test_resolve_postgres_cli_path_prepends_candidate_when_psql_missing(): void
    {
        $path = '/usr/bin:/bin';
        $candidate = sys_get_temp_dir() . '/pgsql-bin-' . uniqid('', true);
        mkdir($candidate, 0777, true);
        file_put_contents($candidate . '/psql', "#!/bin/sh\nexit 0\n");
        chmod($candidate . '/psql', 0755);

        try {
            $resolved = CreatesApplicationHarness::resolvePostgresCliPath($path, [$candidate]);

            $this->assertSame($candidate . PATH_SEPARATOR . $path, $resolved);
        } finally {
            @unlink($candidate . '/psql');
            @rmdir($candidate);
        }
    }

    public function test_resolve_postgres_cli_path_keeps_existing_psql_path(): void
    {
        $candidate = sys_get_temp_dir() . '/pgsql-bin-' . uniqid('', true);
        mkdir($candidate, 0777, true);
        file_put_contents($candidate . '/psql', "#!/bin/sh\nexit 0\n");
        chmod($candidate . '/psql', 0755);
        $path = $candidate . PATH_SEPARATOR . '/usr/bin:/bin';

        try {
            $resolved = CreatesApplicationHarness::resolvePostgresCliPath($path, ['/missing/pgsql/bin', $candidate]);

            $this->assertSame($path, $resolved);
        } finally {
            @unlink($candidate . '/psql');
            @rmdir($candidate);
        }
    }
}

class CreatesApplicationHarness
{
    use CreatesApplication;
}
