<?php

namespace Tests\Feature;

use App\Models\BookDeviceProgress;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class BookProgressApiTest extends TestCase
{
    use RefreshDatabase;

    private User $user;
    private Library $library;
    private UserBook $book;

    protected function setUp(): void
    {
        parent::setUp();

        $this->user = User::factory()->create();
        $this->library = Library::factory()->create(['user_id' => $this->user->id]);
        $this->book = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
        ]);
    }

    public function test_can_update_reading_progress_for_epub(): void
    {
        $response = $this->actingAs($this->user)->postJson("/api/books/{$this->book->uuid}/reading-progress", [
            'library_id' => $this->library->id,
            'device_uuid' => 'test-device-epub',
            'format' => 'EPUB',
            'progress_bp' => 5000,
        ]);

        $response->assertStatus(200);
        $this->assertDatabaseHas('books_devices_progress', [
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress_bp' => 5000,
        ]);
    }

    public function test_progress_is_tracked_per_format(): void
    {
        $this->actingAs($this->user)->postJson("/api/books/{$this->book->uuid}/reading-progress", [
            'library_id' => $this->library->id,
            'device_uuid' => 'test-device-progress',
            'format' => 'EPUB',
            'progress_bp' => 3000,
        ])->assertStatus(200);

        $this->actingAs($this->user)->postJson("/api/books/{$this->book->uuid}/reading-progress", [
            'library_id' => $this->library->id,
            'device_uuid' => 'test-device-progress',
            'format' => 'PDF',
            'progress_bp' => 6000,
        ])->assertStatus(200);

        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress_bp' => 3000,
        ]);
        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'PDF',
            'progress_bp' => 6000,
        ]);
    }

    public function test_requires_authentication(): void
    {
        $this->postJson("/api/books/{$this->book->uuid}/reading-progress", [
            'library_id' => $this->library->id,
            'device_uuid' => 'test-device-unauth',
            'format' => 'EPUB',
            'progress_bp' => 5000,
        ])->assertStatus(401);
    }

    public function test_validates_required_fields(): void
    {
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/reading-progress", [])
            ->assertStatus(422);
    }

    public function test_creates_device_automatically_from_device_uuid(): void
    {
        $this->actingAs($this->user)->postJson("/api/books/{$this->book->uuid}/reading-progress", [
            'library_id' => $this->library->id,
            'device_uuid' => 'web-browser-test',
            'format' => 'EPUB',
            'progress_bp' => 2500,
        ])->assertStatus(200);

        $this->assertDatabaseHas('devices', [
            'user_id' => $this->user->id,
            'device_uuid' => 'web-browser-test',
        ]);
    }

    public function test_updates_progress_across_multiple_calls(): void
    {
        $this->actingAs($this->user)->postJson("/api/books/{$this->book->uuid}/reading-progress", [
            'library_id' => $this->library->id,
            'device_uuid' => 'test-device-repeat',
            'format' => 'EPUB',
            'progress_bp' => 2500,
        ])->assertStatus(200);

        $this->actingAs($this->user)->postJson("/api/books/{$this->book->uuid}/reading-progress", [
            'library_id' => $this->library->id,
            'device_uuid' => 'test-device-repeat',
            'format' => 'EPUB',
            'progress_bp' => 5000,
        ])->assertStatus(200);

        $progress = BookDeviceProgress::where('book_uuid', $this->book->uuid)
            ->where('format', 'EPUB')
            ->where('library_id', $this->library->id)
            ->first();

        $this->assertNotNull($progress);
        $this->assertEquals(5000, $progress->progress_bp);
    }
}

