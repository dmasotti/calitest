<?php

namespace Tests\Feature;

use Tests\TestCase;
use App\Models\User;
use App\Models\UserBook;
use App\Models\Library;
use App\Models\Device;
use App\Models\BooksDevicesProgress;
use Illuminate\Foundation\Testing\RefreshDatabase;

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

    public function test_can_update_reading_progress_for_epub()
    {
        $response = $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'progress' => 50,
                'last_position' => json_encode(['cfi' => 'epubcfi(/6/4[chap01ref]!/4[body01]/10[para05]/1:0)']),
                'reading_time_seconds' => 120,
                'format' => 'EPUB',
            ]);

        $response->assertStatus(200);
        
        $this->assertDatabaseHas('books_devices_progress', [
            'user_id' => $this->user->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress' => 50,
        ]);
    }

    public function test_can_update_reading_progress_for_pdf()
    {
        $response = $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'progress' => 75,
                'last_position' => json_encode(['page' => 150]),
                'reading_time_seconds' => 300,
                'format' => 'PDF',
            ]);

        $response->assertStatus(200);
        
        $this->assertDatabaseHas('books_devices_progress', [
            'user_id' => $this->user->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'PDF',
            'progress' => 75,
        ]);
    }

    public function test_progress_is_tracked_per_format()
    {
        // Update EPUB progress
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'progress' => 30,
                'format' => 'EPUB',
            ]);

        // Update PDF progress  
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'progress' => 60,
                'format' => 'PDF',
            ]);

        // Both should exist separately
        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress' => 30,
        ]);

        $this->assertDatabaseHas('books_devices_progress', [
            'book_uuid' => $this->book->uuid,
            'format' => 'PDF',
            'progress' => 60,
        ]);
    }

    public function test_requires_authentication()
    {
        $response = $this->postJson("/api/books/{$this->book->uuid}/progress", [
            'progress' => 50,
            'format' => 'EPUB',
        ]);

        $response->assertStatus(401);
    }

    public function test_validates_required_fields()
    {
        $response = $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", []);

        $response->assertStatus(422);
    }

    public function test_creates_web_device_automatically()
    {
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'progress' => 25,
                'format' => 'EPUB',
            ]);

        $this->assertDatabaseHas('devices', [
            'user_id' => $this->user->id,
            'device_name' => 'Web Browser',
        ]);
    }

    public function test_accumulates_reading_time()
    {
        // First update
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'progress' => 25,
                'reading_time_seconds' => 100,
                'format' => 'EPUB',
            ]);

        // Second update
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'progress' => 50,
                'reading_time_seconds' => 150,
                'format' => 'EPUB',
            ]);

        $progress = BooksDevicesProgress::where('book_uuid', $this->book->uuid)
            ->where('format', 'EPUB')
            ->first();

        $this->assertEquals(250, $progress->reading_time_seconds);
    }
}
