<?php

namespace Tests\Server;

use App\Services\Sync\Benchmark\MultiUserMetadataConvergenceBenchmarkService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class MultiUserMetadataConvergenceBenchmarkTest extends TestCase
{
    use RefreshDatabase;

    public function test_small_multi_user_metadata_benchmark_converges_with_upload_and_download_mix(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Multi-user metadata convergence benchmark is validated on MySQL/PostgreSQL.');
        }

        $events = [];

        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 2,
            'min_books' => 12,
            'max_books' => 12,
            'seed' => 20260310,
            'max_passes' => 4,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
        ], function (array $event) use (&$events): void {
            $events[] = $event;
        });

        $this->assertSame(DB::getDriverName(), $stats['driver']);
        $this->assertSame(2, $stats['users']);
        $this->assertCount(2, $stats['user_results']);
        $this->assertGreaterThan(0, $stats['totals']['uploads_applied']);
        $this->assertGreaterThan(0, $stats['totals']['downloads_applied']);
        $this->assertNotEmpty($events);
        $this->assertSame('user_start', $events[0]['event']);
        $this->assertContains('seed_complete', array_column($events, 'event'));
        $this->assertContains('pass_start', array_column($events, 'event'));
        $this->assertContains('phase_complete', array_column($events, 'event'));
        $this->assertContains('pass_complete', array_column($events, 'event'));
        $this->assertSame('user_complete', $events[array_key_last($events)]['event']);

        $phaseCompleteEvents = array_values(array_filter($events, static fn (array $event): bool => ($event['event'] ?? null) === 'phase_complete'));
        $this->assertNotEmpty($phaseCompleteEvents);
        $this->assertArrayHasKey('phase', $phaseCompleteEvents[0]);
        $this->assertArrayHasKey('elapsed_ms', $phaseCompleteEvents[0]);
        $syncPhaseEvents = array_values(array_filter(
            $phaseCompleteEvents,
            static fn (array $event): bool => ($event['phase'] ?? null) === 'sync'
        ));
        $this->assertNotEmpty($syncPhaseEvents);
        $this->assertArrayHasKey('sync_profile', $syncPhaseEvents[0]);
        $this->assertArrayHasKey('loop_missing_from_server_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('loop_updates_for_client_ms', $syncPhaseEvents[0]['sync_profile']);

        $passCompleteEvents = array_values(array_filter($events, static fn (array $event): bool => ($event['event'] ?? null) === 'pass_complete'));
        $this->assertNotEmpty($passCompleteEvents);
        $this->assertArrayHasKey('preflight_ms', $passCompleteEvents[0]);
        $this->assertArrayHasKey('sync_ms', $passCompleteEvents[0]);
        $this->assertArrayHasKey('uploads_ms', $passCompleteEvents[0]);
        $this->assertArrayHasKey('downloads_ms', $passCompleteEvents[0]);

        foreach ($stats['user_results'] as $userResult) {
            $this->assertTrue($userResult['converged']);
            $this->assertLessThanOrEqual(4, $userResult['passes']);
            $this->assertSame($userResult['final_client_root'], $userResult['final_server_root']);
            $this->assertArrayHasKey('preflight_ms', $userResult);
            $this->assertArrayHasKey('sync_ms', $userResult);
            $this->assertArrayHasKey('uploads_ms', $userResult);
            $this->assertArrayHasKey('downloads_ms', $userResult);
            $this->assertGreaterThanOrEqual(0, $userResult['preflight_ms']);
            $this->assertGreaterThanOrEqual(0, $userResult['sync_ms']);
            $this->assertGreaterThanOrEqual(0, $userResult['uploads_ms']);
            $this->assertGreaterThanOrEqual(0, $userResult['downloads_ms']);
        }
    }
}
