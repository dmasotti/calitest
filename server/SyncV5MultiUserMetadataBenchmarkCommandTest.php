<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class SyncV5MultiUserMetadataBenchmarkCommandTest extends TestCase
{
    use RefreshDatabase;

    private function extractReportPath(string $output): string
    {
        preg_match('/report=([^\s]+)/', $output, $matches);
        $this->assertNotEmpty($matches[1] ?? null, 'Benchmark command must print a report path');

        return (string) $matches[1];
    }

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

    public function test_command_asset_profile_emits_cover_and_file_breakdown(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Asset benchmark command progress is validated on MySQL/PostgreSQL.');
        }

        $exitCode = Artisan::call('sync:benchmark-multiuser-metadata', [
            '--users' => 1,
            '--min-books' => 6,
            '--max-books' => 6,
            '--seed' => 20260313,
            '--max-passes' => 3,
            '--fixture-db' => 'tests/plugin/fixtures/CalibreLargeLocal/metadata.db',
            '--allow-pre-1970' => DB::getDriverName() === 'pgsql' ? '1' : '0',
            '--sync-files' => '1',
            '--sync-covers' => '1',
            '--asset-profile' => 'mixed',
        ]);

        $output = Artisan::output();

        $this->assertSame(0, $exitCode);
        $this->assertStringContainsString('loop_missing_covers_ms', $output);
        $this->assertStringContainsString('loop_missing_files_ms', $output);
        $this->assertStringContainsString('loop_updates_cover_payload_ms', $output);
        $this->assertStringContainsString('loop_updates_files_payload_ms', $output);
        $this->assertStringContainsString('cover_downloads', $output);
        $this->assertStringContainsString('file_uploads', $output);
    }

    public function test_command_persists_report_with_zero_asset_activity_when_profile_is_none(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Asset benchmark command progress is validated on MySQL/PostgreSQL.');
        }

        $exitCode = Artisan::call('sync:benchmark-multiuser-metadata', [
            '--users' => 1,
            '--min-books' => 6,
            '--max-books' => 6,
            '--seed' => 20260323,
            '--max-passes' => 3,
            '--fixture-db' => 'tests/plugin/fixtures/CalibreLargeLocal/metadata.db',
            '--allow-pre-1970' => DB::getDriverName() === 'pgsql' ? '1' : '0',
            '--sync-files' => 'yes',
            '--sync-covers' => 'on',
            '--asset-profile' => 'none',
        ]);

        $output = Artisan::output();
        $reportPath = $this->extractReportPath($output);

        $this->assertSame(0, $exitCode);
        $this->assertFileExists($reportPath);

        $report = json_decode((string) file_get_contents($reportPath), true, 512, JSON_THROW_ON_ERROR);
        $this->assertTrue((bool) ($report['sync_files_enabled'] ?? false));
        $this->assertTrue((bool) ($report['sync_covers_enabled'] ?? false));
        $this->assertSame('none', $report['asset_profile'] ?? null);
        $this->assertSame(0, (int) data_get($report, 'user_results.0.download_profile.cover_downloads', -1));
        $this->assertSame(0, (int) data_get($report, 'user_results.0.download_profile.file_downloads', -1));
        $this->assertSame(0, (int) data_get($report, 'user_results.0.upload_profile.cover_uploads', -1));
        $this->assertSame(0, (int) data_get($report, 'user_results.0.upload_profile.file_uploads', -1));
    }

    public function test_command_boolean_like_asset_flags_enable_file_only_profile(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Asset benchmark command progress is validated on MySQL/PostgreSQL.');
        }

        $exitCode = Artisan::call('sync:benchmark-multiuser-metadata', [
            '--users' => 1,
            '--min-books' => 8,
            '--max-books' => 8,
            '--seed' => 20260324,
            '--max-passes' => 4,
            '--fixture-db' => 'tests/plugin/fixtures/CalibreLargeLocal/metadata.db',
            '--allow-pre-1970' => DB::getDriverName() === 'pgsql' ? '1' : '0',
            '--sync-files' => 'true',
            '--sync-covers' => 'off',
            '--asset-profile' => 'mixed',
        ]);

        $output = Artisan::output();
        $reportPath = $this->extractReportPath($output);

        $this->assertSame(0, $exitCode);
        $this->assertFileExists($reportPath);

        $report = json_decode((string) file_get_contents($reportPath), true, 512, JSON_THROW_ON_ERROR);
        $this->assertTrue((bool) ($report['sync_files_enabled'] ?? false));
        $this->assertFalse((bool) ($report['sync_covers_enabled'] ?? true));
        $this->assertSame('mixed', $report['asset_profile'] ?? null);
        $this->assertGreaterThan(0, (int) data_get($report, 'user_results.0.download_profile.file_downloads', 0));
        $this->assertGreaterThan(0, (int) data_get($report, 'user_results.0.upload_profile.file_uploads', 0));
        $this->assertSame(0, (int) data_get($report, 'user_results.0.download_profile.cover_downloads', -1));
        $this->assertSame(0, (int) data_get($report, 'user_results.0.upload_profile.cover_uploads', -1));
    }
}
