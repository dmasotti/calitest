<?php

namespace Tests\Server;

use App\Models\Device;
use App\Models\Library;
use App\Models\ReadingEvent;
use App\Models\ReadingSession;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class ReadingStatsApiTest extends TestCase
{
    use RefreshDatabase;

    public function test_reading_events_store_updates_progress(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        $device = Device::factory()->create(['user_id' => $user->id]);

        Sanctum::actingAs($user);

        $payload = [
            'events' => [
                [
                    'book_uuid' => $book->uuid,
                    'library_id' => $library->id,
                    'event_type' => 'progress',
                    'progress_bp_before' => 1000,
                    'progress_bp_after' => 3567,
                    'delta_bp' => 2567,
                    'duration_seconds' => 900,
                    'chars_read' => 1500,
                    'client_ts' => now()->toIso8601String(),
                    'device_id' => $device->id,
                    'source' => 'calimob',
                ],
            ],
        ];

        $response = $this->postJson('/api/reading/events', $payload);
        $response->assertStatus(200);
        $response->assertJson([
            'status' => 'ok',
            'created' => 1,
        ]);

        $this->assertDatabaseHas('reading_events', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_uuid' => $book->uuid,
            'device_id' => $device->id,
            'source' => 'calimob',
            'event_type' => 'progress',
            'progress_bp_after' => 3567,
            'chars_read' => 1500,
        ]);

        $this->assertDatabaseHas('books_devices_progress', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_uuid' => $book->uuid,
            'device_id' => $device->id,
            'progress_bp' => 3567,
        ]);

        $this->assertDatabaseHas('reading_stats_daily', [
            'user_id' => $user->id,
        ]);
    }

    public function test_reading_sessions_store_creates_session(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        $device = Device::factory()->create(['user_id' => $user->id]);

        Sanctum::actingAs($user);

        $payload = [
            'sessions' => [
                [
                    'book_uuid' => $book->uuid,
                    'library_id' => $library->id,
                    'started_at' => now()->subMinutes(20)->toIso8601String(),
                    'ended_at' => now()->toIso8601String(),
                    'duration_seconds' => 1200,
                    'progress_bp_start' => 1000,
                    'progress_bp_end' => 2500,
                    'chars_read' => 2000,
                    'device_id' => $device->id,
                    'source' => 'calimob',
                ],
            ],
        ];

        $response = $this->postJson('/api/reading/sessions', $payload);
        $response->assertStatus(200);
        $response->assertJson([
            'status' => 'ok',
            'created' => 1,
        ]);

        $this->assertDatabaseHas('reading_sessions', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_uuid' => $book->uuid,
            'device_id' => $device->id,
            'source' => 'calimob',
            'progress_bp_end' => 2500,
            'chars_read' => 2000,
        ]);

        $this->assertDatabaseHas('books_devices_progress', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_uuid' => $book->uuid,
            'device_id' => $device->id,
            'progress_bp' => 2500,
        ]);
    }

    public function test_reading_stats_daily_endpoint_returns_summary(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        Sanctum::actingAs($user);

        $this->postJson('/api/reading/events', [
            'events' => [
                [
                    'book_uuid' => $book->uuid,
                    'library_id' => $library->id,
                    'event_type' => 'progress',
                    'progress_bp_before' => 0,
                    'progress_bp_after' => 1200,
                    'delta_bp' => 1200,
                    'duration_seconds' => 600,
                    'chars_read' => 800,
                    'client_ts' => now()->toIso8601String(),
                ],
            ],
        ])->assertStatus(200);

        $response = $this->getJson('/api/reading/stats/daily');
        $response->assertStatus(200);
        $response->assertJsonStructure([
            'from',
            'to',
            'summary' => ['books_finished', 'pages_read', 'reading_time_minutes', 'delta_bp_total', 'sessions_count', 'chars_read_total'],
            'days',
        ]);
    }
}
