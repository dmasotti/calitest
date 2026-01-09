<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\UserBook;
use App\Models\Library;
use App\Models\Device;
use App\Models\BookDeviceProgress;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Foundation\Testing\WithoutMiddleware;

class BookProgressTest extends TestCase
{
    use RefreshDatabase, WithoutMiddleware;

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
        $response = $this->actingAs($this->user, 'sanctum')
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress_percent' => 50,
                'last_position' => [
                    'cfi' => 'epubcfi(/6/4[chap01]!/4/2/2/1:0)',
                    'percent' => 50
                ],
                'reading_time' => 5, // minutes
            ]);

        if ($response->status() !== 200) {
            dump($response->json());
        }
        
        $response->assertStatus(200);

        $this->assertDatabaseHas('books_devices_progress', [
            'user_id' => $this->user->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress_bp' => 5000, // 50 * 100
        ]);
    }

    /** @test */
    public function it_requires_format_field()
    {
        $response = $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'progress_percent' => 50,
                'last_position' => ['percent' => 50],
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
                'progress_percent' => 30,
                'last_position' => ['cfi' => 'epubcfi(/6/4)', 'percent' => 30],
                'reading_time' => 3, // minutes
            ]);

        // Save PDF progress
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'PDF',
                'progress_percent' => 70,
                'last_position' => ['page' => 50, 'percent' => 70],
                'reading_time' => 7, // minutes
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
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress_percent' => 30,
                'last_position' => ['percent' => 30],
                'reading_time' => 3,
            ]);

        // Update
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress_percent' => 60,
                'last_position' => ['percent' => 60],
                'reading_time' => 3,
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
    public function it_accumulates_reading_time()
    {
        // First session
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress_percent' => 30,
                'last_position' => ['percent' => 30],
                'reading_time' => 5, // minutes
            ]);

        // Second session
        $this->actingAs($this->user)
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress_percent' => 60,
                'last_position' => ['percent' => 60],
                'reading_time' => 3, // minutes
            ]);

        $stats = \App\Models\ReadingStatDaily::where([
            'user_id' => $this->user->id,
            'date' => now()->toDateString(),
        ])->first();

        $this->assertNotNull($stats);
        $this->assertEquals(8, $stats->minutes_read); // 5 + 3
    }

    /** @test */
    public function it_requires_authentication()
    {
        $response = $this
            ->postJson("/api/books/{$this->book->uuid}/progress", [
                'format' => 'EPUB',
                'progress_percent' => 50,
            ]);

        $response->assertStatus(401);
    }
}
