<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class SyncV5MultiUserMetadataBenchmarkCommandTest extends TestCase
{
    use RefreshDatabase;

    public function test_command_emits_progress_lines_during_real_small_run(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Benchmark command progress is validated on MySQL/PostgreSQL.');
        }

        $exitCode = Artisan::call('sync:benchmark-multiuser-metadata', [
            '--users' => 1,
            '--min-books' => 6,
            '--max-books' => 6,
            '--seed' => 20260310,
            '--max-passes' => 3,
            '--fixture-db' => 'tests/plugin/fixtures/CalibreLargeLocal/metadata.db',
            '--allow-pre-1970' => DB::getDriverName() === 'pgsql' ? '1' : '0',
        ]);

        $output = Artisan::output();

        $this->assertSame(0, $exitCode);
        $this->assertStringContainsString('[PERF][SYNC_V5_MULTIUSER_METADATA][PROGRESS]', $output);
        $this->assertStringContainsString('user_start', $output);
        $this->assertStringContainsString('seed_complete', $output);
        $this->assertStringContainsString('pass_start', $output);
        $this->assertStringContainsString('phase_complete', $output);
        $this->assertStringContainsString('pass_complete', $output);
        $this->assertStringContainsString('preflight_ms', $output);
        $this->assertStringContainsString('sync_ms', $output);
        $this->assertStringContainsString('loop_missing_from_server_ms', $output);
        $this->assertStringContainsString('loop_updates_for_client_ms', $output);
        $this->assertStringContainsString('user_complete', $output);
        $this->assertStringContainsString('[PERF][SYNC_V5_MULTIUSER_METADATA] report=', $output);
    }
}
