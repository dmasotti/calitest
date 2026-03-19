<?php

namespace Tests\Server;

use App\Services\Sync\Benchmark\MultiUserMetadataConvergenceBenchmarkService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class MultiUserMetadataConvergenceBenchmarkTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Multi-user metadata convergence benchmark is validated on MySQL/PostgreSQL.');
        }
    }

    public function test_small_multi_user_metadata_benchmark_converges_with_upload_and_download_mix(): void
    {
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
        $this->assertArrayHasKey('prime_server_batch_hash_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('authors_map_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('series_map_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('tags_map_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('publishers_map_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('languages_map_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('identifiers_map_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('files_map_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('all_server_books_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('prime_client_set_hash_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('all_files_map_ms', $syncPhaseEvents[0]['sync_profile']);
        $this->assertArrayHasKey('all_identifiers_map_ms', $syncPhaseEvents[0]['sync_profile']);
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

    public function test_small_multi_user_metadata_benchmark_seeds_valid_v2_metadata_hash_cache(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 4,
            'max_books' => 4,
            'seed' => 20260311,
            'max_passes' => 2,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
        ]);

        $libraryId = (int) ($stats['user_results'][0]['library_id'] ?? 0);
        $this->assertGreaterThan(0, $libraryId);

        $caches = DB::table('books')
            ->where('library_id', $libraryId)
            ->pluck('metadata_hash_cache')
            ->filter()
            ->values()
            ->all();

        $this->assertNotEmpty($caches);
        foreach ($caches as $cache) {
            $this->assertMatchesRegularExpression('/^v2:[0-9a-f]{64}:\d+$/', (string) $cache);
        }
    }

    public function test_small_multi_user_metadata_benchmark_can_run_twice_without_user_or_library_id_collisions(): void
    {
        $config = [
            'users' => 1,
            'min_books' => 4,
            'max_books' => 4,
            'seed' => 20260312,
            'max_passes' => 2,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
        ];

        $first = app(MultiUserMetadataConvergenceBenchmarkService::class)->run($config);
        $second = app(MultiUserMetadataConvergenceBenchmarkService::class)->run($config);

        $this->assertTrue($first['user_results'][0]['converged']);
        $this->assertTrue($second['user_results'][0]['converged']);
        $this->assertNotSame(
            $first['user_results'][0]['library_id'],
            $second['user_results'][0]['library_id'],
            'Sequential benchmark runs must create isolated libraries without id collisions'
        );
        $this->assertSame(2, DB::table('users')->count());
        $this->assertSame(2, DB::table('libraries')->count());
    }

    public function test_small_multi_user_metadata_benchmark_can_converge_in_one_pass_after_apply_side_effects(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 4,
            'max_books' => 4,
            'seed' => 20260312,
            'max_passes' => 1,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
        ]);

        $this->assertTrue($stats['user_results'][0]['converged']);
        $this->assertSame(1, (int) $stats['user_results'][0]['passes']);
    }

    public function test_small_multi_user_asset_benchmark_reports_cover_and_file_phase_breakdown(): void
    {
        $events = [];

        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 8,
            'max_books' => 8,
            'seed' => 20260313,
            'max_passes' => 4,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'sync_covers_enabled' => true,
            'sync_files_enabled' => true,
            'asset_profile' => 'mixed',
        ], function (array $event) use (&$events): void {
            $events[] = $event;
        });

        $this->assertTrue($stats['user_results'][0]['converged']);
        $this->assertGreaterThan(0, $stats['totals']['uploads_applied']);
        $this->assertGreaterThan(0, $stats['totals']['downloads_applied']);

        $syncPhaseEvents = array_values(array_filter(
            $events,
            static fn (array $event): bool => ($event['event'] ?? null) === 'phase_complete'
                && ($event['phase'] ?? null) === 'sync'
        ));
        $this->assertNotEmpty($syncPhaseEvents);
        $syncProfile = (array) ($syncPhaseEvents[0]['sync_profile'] ?? []);
        $this->assertArrayHasKey('loop_missing_metadata_ms', $syncProfile);
        $this->assertArrayHasKey('loop_missing_covers_ms', $syncProfile);
        $this->assertArrayHasKey('loop_missing_files_ms', $syncProfile);
        $this->assertArrayHasKey('loop_updates_metadata_payload_ms', $syncProfile);
        $this->assertArrayHasKey('loop_updates_cover_payload_ms', $syncProfile);
        $this->assertArrayHasKey('loop_updates_files_payload_ms', $syncProfile);

        $downloadPhaseEvents = array_values(array_filter(
            $events,
            static fn (array $event): bool => ($event['event'] ?? null) === 'phase_complete'
                && ($event['phase'] ?? null) === 'downloads'
        ));
        $this->assertNotEmpty($downloadPhaseEvents);
        $downloadProfile = (array) ($downloadPhaseEvents[0]['download_profile'] ?? []);
        $this->assertArrayHasKey('metadata_downloads', $downloadProfile);
        $this->assertArrayHasKey('cover_downloads', $downloadProfile);
        $this->assertArrayHasKey('file_downloads', $downloadProfile);
        $this->assertArrayHasKey('metadata_apply_ms', $downloadProfile);
        $this->assertArrayHasKey('cover_apply_ms', $downloadProfile);
        $this->assertArrayHasKey('file_apply_ms', $downloadProfile);

        $uploadPhaseEvents = array_values(array_filter(
            $events,
            static fn (array $event): bool => ($event['event'] ?? null) === 'phase_complete'
                && ($event['phase'] ?? null) === 'uploads'
        ));
        $this->assertNotEmpty($uploadPhaseEvents);
        $uploadProfile = (array) ($uploadPhaseEvents[0]['upload_profile'] ?? []);
        $this->assertArrayHasKey('metadata_uploads', $uploadProfile);
        $this->assertArrayHasKey('cover_uploads', $uploadProfile);
        $this->assertArrayHasKey('file_uploads', $uploadProfile);
        $this->assertArrayHasKey('metadata_apply_ms', $uploadProfile);
        $this->assertArrayHasKey('cover_apply_ms', $uploadProfile);
        $this->assertArrayHasKey('file_apply_ms', $uploadProfile);

        $userResult = $stats['user_results'][0];
        $this->assertArrayHasKey('download_profile', $userResult);
        $this->assertArrayHasKey('upload_profile', $userResult);
        $this->assertArrayHasKey('cover_downloads', $userResult['download_profile']);
        $this->assertArrayHasKey('file_uploads', $userResult['upload_profile']);
    }

    public function test_small_multi_user_cover_only_benchmark_reports_zero_file_activity(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 8,
            'max_books' => 8,
            'seed' => 20260314,
            'max_passes' => 4,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'state_weights' => ['same' => 1.0, 'upload_missing' => 0.0, 'download_missing' => 0.0],
            'sync_covers_enabled' => true,
            'sync_files_enabled' => false,
            'asset_profile' => 'mixed',
        ]);

        $this->assertTrue($stats['user_results'][0]['converged']);
        $downloadProfile = (array) ($stats['user_results'][0]['download_profile'] ?? []);
        $uploadProfile = (array) ($stats['user_results'][0]['upload_profile'] ?? []);
        $this->assertGreaterThan(0, (int) ($downloadProfile['cover_downloads'] ?? 0));
        $this->assertGreaterThan(0, (int) ($uploadProfile['cover_uploads'] ?? 0));
        $this->assertSame(0, (int) ($downloadProfile['file_downloads'] ?? 0));
        $this->assertSame(0, (int) ($uploadProfile['file_uploads'] ?? 0));
    }

    public function test_small_multi_user_file_only_benchmark_reports_zero_cover_activity(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 8,
            'max_books' => 8,
            'seed' => 20260315,
            'max_passes' => 4,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'state_weights' => ['same' => 1.0, 'upload_missing' => 0.0, 'download_missing' => 0.0],
            'sync_covers_enabled' => false,
            'sync_files_enabled' => true,
            'asset_profile' => 'mixed',
        ]);

        $this->assertTrue($stats['user_results'][0]['converged']);
        $downloadProfile = (array) ($stats['user_results'][0]['download_profile'] ?? []);
        $uploadProfile = (array) ($stats['user_results'][0]['upload_profile'] ?? []);
        $this->assertGreaterThan(0, (int) ($downloadProfile['file_downloads'] ?? 0));
        $this->assertGreaterThan(0, (int) ($uploadProfile['file_uploads'] ?? 0));
        $this->assertSame(0, (int) ($downloadProfile['cover_downloads'] ?? 0));
        $this->assertSame(0, (int) ($uploadProfile['cover_uploads'] ?? 0));
    }

    public function test_asset_toggles_without_asset_profile_keep_cover_and_file_profiles_zero(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 6,
            'max_books' => 6,
            'seed' => 20260316,
            'max_passes' => 3,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'sync_covers_enabled' => true,
            'sync_files_enabled' => true,
            'asset_profile' => 'none',
        ]);

        $this->assertTrue($stats['user_results'][0]['converged']);
        $downloadProfile = (array) ($stats['user_results'][0]['download_profile'] ?? []);
        $uploadProfile = (array) ($stats['user_results'][0]['upload_profile'] ?? []);
        $this->assertSame(0, (int) ($downloadProfile['cover_downloads'] ?? 0));
        $this->assertSame(0, (int) ($downloadProfile['file_downloads'] ?? 0));
        $this->assertSame(0, (int) ($uploadProfile['cover_uploads'] ?? 0));
        $this->assertSame(0, (int) ($uploadProfile['file_uploads'] ?? 0));
    }

    public function test_asset_profile_mixed_with_asset_toggles_disabled_keeps_asset_profiles_zero(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 8,
            'max_books' => 8,
            'seed' => 20260317,
            'max_passes' => 3,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'state_weights' => ['same' => 1.0, 'upload_missing' => 0.0, 'download_missing' => 0.0],
            'sync_covers_enabled' => false,
            'sync_files_enabled' => false,
            'asset_profile' => 'mixed',
        ]);

        $this->assertTrue($stats['user_results'][0]['converged']);
        $downloadProfile = (array) ($stats['user_results'][0]['download_profile'] ?? []);
        $uploadProfile = (array) ($stats['user_results'][0]['upload_profile'] ?? []);
        $this->assertSame(0, (int) ($downloadProfile['cover_downloads'] ?? 0));
        $this->assertSame(0, (int) ($downloadProfile['file_downloads'] ?? 0));
        $this->assertSame(0, (int) ($uploadProfile['cover_uploads'] ?? 0));
        $this->assertSame(0, (int) ($uploadProfile['file_uploads'] ?? 0));
    }

    public function test_asset_benchmark_user_profiles_have_numeric_non_negative_breakdown_fields(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 8,
            'max_books' => 8,
            'seed' => 20260318,
            'max_passes' => 4,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'sync_covers_enabled' => true,
            'sync_files_enabled' => true,
            'asset_profile' => 'mixed',
        ]);

        $downloadProfile = (array) ($stats['user_results'][0]['download_profile'] ?? []);
        $uploadProfile = (array) ($stats['user_results'][0]['upload_profile'] ?? []);

        foreach ([
            'metadata_downloads',
            'cover_downloads',
            'file_downloads',
            'metadata_apply_ms',
            'cover_apply_ms',
            'file_apply_ms',
        ] as $key) {
            $this->assertArrayHasKey($key, $downloadProfile);
            $this->assertIsNumeric($downloadProfile[$key]);
            $this->assertGreaterThanOrEqual(0, (float) $downloadProfile[$key]);
        }

        foreach ([
            'metadata_uploads',
            'cover_uploads',
            'file_uploads',
            'metadata_apply_ms',
            'cover_apply_ms',
            'file_apply_ms',
        ] as $key) {
            $this->assertArrayHasKey($key, $uploadProfile);
            $this->assertIsNumeric($uploadProfile[$key]);
            $this->assertGreaterThanOrEqual(0, (float) $uploadProfile[$key]);
        }
    }

    public function test_multi_user_asset_benchmark_totals_match_sum_of_user_results(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 2,
            'min_books' => 8,
            'max_books' => 8,
            'seed' => 20260320,
            'max_passes' => 4,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'sync_covers_enabled' => true,
            'sync_files_enabled' => true,
            'asset_profile' => 'mixed',
        ]);

        $sumDownloads = array_sum(array_map(
            static fn (array $result): int => (int) ($result['downloads_applied'] ?? 0),
            $stats['user_results']
        ));
        $sumUploads = array_sum(array_map(
            static fn (array $result): int => (int) ($result['uploads_applied'] ?? 0),
            $stats['user_results']
        ));

        $this->assertSame($sumDownloads, (int) ($stats['totals']['downloads_applied'] ?? -1));
        $this->assertSame($sumUploads, (int) ($stats['totals']['uploads_applied'] ?? -1));

        $coverDownloads = array_sum(array_map(
            static fn (array $result): int => (int) (($result['download_profile']['cover_downloads'] ?? 0)),
            $stats['user_results']
        ));
        $fileDownloads = array_sum(array_map(
            static fn (array $result): int => (int) (($result['download_profile']['file_downloads'] ?? 0)),
            $stats['user_results']
        ));
        $coverUploads = array_sum(array_map(
            static fn (array $result): int => (int) (($result['upload_profile']['cover_uploads'] ?? 0)),
            $stats['user_results']
        ));
        $fileUploads = array_sum(array_map(
            static fn (array $result): int => (int) (($result['upload_profile']['file_uploads'] ?? 0)),
            $stats['user_results']
        ));

        $this->assertGreaterThan(0, $coverDownloads);
        $this->assertGreaterThan(0, $fileDownloads);
        $this->assertGreaterThan(0, $coverUploads);
        $this->assertGreaterThan(0, $fileUploads);
    }

    public function test_file_only_benchmark_regression_keeps_file_uploads_after_download_phase(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 12,
            'max_books' => 12,
            'seed' => 20260319,
            'max_passes' => 4,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'state_weights' => ['same' => 1.0, 'upload_missing' => 0.0, 'download_missing' => 0.0],
            'sync_covers_enabled' => false,
            'sync_files_enabled' => true,
            'asset_profile' => 'mixed',
        ]);

        $this->assertTrue($stats['user_results'][0]['converged']);
        $this->assertGreaterThan(0, (int) ($stats['totals']['downloads_applied'] ?? 0));
        $this->assertGreaterThan(0, (int) ($stats['totals']['uploads_applied'] ?? 0));

        $downloadProfile = (array) ($stats['user_results'][0]['download_profile'] ?? []);
        $uploadProfile = (array) ($stats['user_results'][0]['upload_profile'] ?? []);
        $this->assertGreaterThan(0, (int) ($downloadProfile['file_downloads'] ?? 0));
        $this->assertGreaterThan(0, (int) ($uploadProfile['file_uploads'] ?? 0));
    }

    public function test_cover_only_benchmark_keeps_file_apply_times_at_zero(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 8,
            'max_books' => 8,
            'seed' => 20260321,
            'max_passes' => 4,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'state_weights' => ['same' => 1.0, 'upload_missing' => 0.0, 'download_missing' => 0.0],
            'sync_covers_enabled' => true,
            'sync_files_enabled' => false,
            'asset_profile' => 'mixed',
        ]);

        $downloadProfile = (array) ($stats['user_results'][0]['download_profile'] ?? []);
        $uploadProfile = (array) ($stats['user_results'][0]['upload_profile'] ?? []);

        $this->assertSame(0.0, (float) ($downloadProfile['file_apply_ms'] ?? -1));
        $this->assertSame(0.0, (float) ($uploadProfile['file_apply_ms'] ?? -1));
    }

    public function test_file_only_benchmark_keeps_cover_apply_times_at_zero(): void
    {
        $stats = app(MultiUserMetadataConvergenceBenchmarkService::class)->run([
            'users' => 1,
            'min_books' => 8,
            'max_books' => 8,
            'seed' => 20260322,
            'max_passes' => 4,
            'fixture_path' => base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            'allow_pre_1970' => DB::getDriverName() === 'pgsql',
            'state_weights' => ['same' => 1.0, 'upload_missing' => 0.0, 'download_missing' => 0.0],
            'sync_covers_enabled' => false,
            'sync_files_enabled' => true,
            'asset_profile' => 'mixed',
        ]);

        $downloadProfile = (array) ($stats['user_results'][0]['download_profile'] ?? []);
        $uploadProfile = (array) ($stats['user_results'][0]['upload_profile'] ?? []);

        $this->assertSame(0.0, (float) ($downloadProfile['cover_apply_ms'] ?? -1));
        $this->assertSame(0.0, (float) ($uploadProfile['cover_apply_ms'] ?? -1));
    }
}
