<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\UserBook;
use App\Models\Library;
use App\Models\Device;
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
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress' => 50,
                'last_position' => json_encode(['cfi' => 'epubcfi(/6/4[chap01]!/4/2/2/1:0)', 'percent' => 50]),
                'reading_time' => 300,
            ]);

        $response->assertStatus(200);

        $this->assertDatabaseHas('books_devices_progress', [
            'user_id' => $this->user->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress' => 50,
        ]);
    }

    /** @test */
    public function it_requires_format_field()
    {
        $response = $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'progress' => 50,
                'last_position' => json_encode(['percent' => 50]),
            ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['format']);
    }

    /** @test */
    public function it_tracks_progress_separately_per_format()
    {
        // Save EPUB progress
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress' => 30,
                'last_position' => json_encode(['cfi' => 'epubcfi(/6/4)', 'percent' => 30]),
                'reading_time' => 200,
            ]);

        // Save PDF progress
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'PDF',
                'progress' => 70,
                'last_position' => json_encode(['page' => 50, 'percent' => 70]),
                'reading_time' => 400,
            ]);

        // Verify both are stored separately
        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress' => 30,
        ]);

        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'PDF',
            'progress' => 70,
        ]);
    }

    /** @test */
    public function it_updates_existing_progress_for_same_device_and_format()
    {
        // First save
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress' => 30,
                'last_position' => json_encode(['percent' => 30]),
                'reading_time' => 200,
            ]);

        // Update
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress' => 60,
                'last_position' => json_encode(['percent' => 60]),
                'reading_time' => 150,
            ]);

        // Should have only one record updated
        $this->assertEquals(1, BooksDevicesProgress::where([
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
        ])->count());

        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress' => 60,
        ]);
    }

    /** @test */
    public function it_accumulates_reading_time()
    {
        // First session
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress' => 30,
                'last_position' => json_encode(['percent' => 30]),
                'reading_time' => 300,
            ]);

        // Second session
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress' => 60,
                'last_position' => json_encode(['percent' => 60]),
                'reading_time' => 200,
            ]);

        $progress = BooksDevicesProgress::where([
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
        ])->first();

        $this->assertEquals(500, $progress->reading_time);
    }

    /** @test */
    public function it_requires_authentication()
    {
        $response = $this->postJson("/api/books/{$this->book->uuid}/progress", [
            'format' => 'EPUB',
            'progress' => 50,
        ]);

        $response->assertStatus(401);
    }
}
