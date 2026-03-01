<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\UserBook;
use App\Models\Library;
use App\Models\BookDeviceProgress;
use Illuminate\Foundation\Testing\RefreshDatabase;

class BookProgressTest extends TestCase
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

    /** @test */
    public function it_can_save_reading_progress()
    {
        $response = $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/reading-progress", [
                'library_id' => $this->library->id,
                'device_uuid' => 'test-device-progress-1',
                'format' => 'EPUB',
                'progress_bp' => 5000,
            ]);

        $response->assertStatus(200);

        $this->assertDatabaseHas('books_devices_progress', [
            'user_id' => $this->user->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress_bp' => 5000, // 50 * 100
        ]);
    }

    /** @test */
    public function it_requires_progress_bp_field()
    {
        $response = $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/reading-progress", [
                'library_id' => $this->library->id,
                'device_uuid' => 'test-device-progress-2',
                'format' => 'EPUB',
            ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['progress_bp']);
    }

    /** @test */
    public function it_tracks_progress_separately_per_format()
    {
        // Save EPUB progress
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/reading-progress", [
                'library_id' => $this->library->id,
                'device_uuid' => 'test-device-progress-3',
                'format' => 'EPUB',
                'progress_bp' => 3000,
            ]);

        // Save PDF progress
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/reading-progress", [
                'library_id' => $this->library->id,
                'device_uuid' => 'test-device-progress-3',
                'format' => 'PDF',
                'progress_bp' => 7000,
            ]);

        // Verify both are stored separately
        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress_bp' => 3000, // 30 * 100
        ]);

        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'PDF',
            'progress_bp' => 7000, // 70 * 100
        ]);
    }

    /** @test */
    public function it_updates_existing_progress_for_same_device_and_format()
    {
        // First save
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/reading-progress", [
                'library_id' => $this->library->id,
                'device_uuid' => 'test-device-progress-4',
                'format' => 'EPUB',
                'progress_bp' => 3000,
            ]);

        // Update
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/reading-progress", [
                'library_id' => $this->library->id,
                'device_uuid' => 'test-device-progress-4',
                'format' => 'EPUB',
                'progress_bp' => 6000,
            ]);

        // Should have only one record updated
        $this->assertEquals(1, BookDeviceProgress::where([
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
        ])->count());

        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress_bp' => 6000, // 60 * 100
        ]);
    }

    /** @test */
    public function it_requires_authentication()
    {
        $response = $this->postJson("/api/books/{$this->book->uuid}/reading-progress", [
            'library_id' => $this->library->id,
            'device_uuid' => 'test-device-progress-unauth',
            'format' => 'EPUB',
            'progress_bp' => 5000,
        ]);

        $response->assertStatus(401);
    }
}
