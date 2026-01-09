<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\UserBook;
use App\Models\BookFile;
use Illuminate\Foundation\Testing\RefreshDatabase;

class EpubReaderTest extends TestCase
{
    use RefreshDatabase;

    protected User $user;
    protected UserBook $book;

    protected function setUp(): void
    {
        parent::setUp();
        
        $this->user = User::factory()->create();
        $this->book = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'title' => 'Test EPUB Book',
        ]);

        BookFile::factory()->create([
            'book' => $this->book->uuid,
            'user_id' => $this->user->id,
            'library_id' => $this->book->library_id,
            'format' => 'EPUB',
        ]);
    }

    /** @test */
    public function it_can_load_epub_reader_page()
    {
        $response = $this->actingAs($this->user)
            ->get("/epub/{$this->book->uuid}");

        $response->assertStatus(200)
            ->assertViewIs('epub-reader')
            ->assertViewHas('book', function ($viewBook) {
                return $viewBook->uuid === $this->book->uuid;
            });
    }

    /** @test */
    public function it_requires_authentication_to_view_epub()
    {
        $response = $this->get("/epub/{$this->book->uuid}");

        $response->assertRedirect('/login');
    }

    /** @test */
    public function it_returns_404_for_nonexistent_book()
    {
        $response = $this->actingAs($this->user)
            ->get("/epub/nonexistent-uuid");

        $response->assertStatus(404);
    }

    /** @test */
    public function it_loads_max_progress_from_all_formats()
    {
        // Create progress for different formats
        $device = \App\Models\Device::factory()->create([
            'user_id' => $this->user->id,
        ]);

        // EPUB at 30%
        \App\Models\BookDeviceProgress::create([
            'user_id' => $this->user->id,
            'device_id' => $device->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress' => 30.0,
            'last_position' => json_encode(['cfi' => 'epub_position']),
        ]);

        // PDF at 70% (higher)
        \App\Models\BookDeviceProgress::create([
            'user_id' => $this->user->id,
            'device_id' => $device->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'PDF',
            'progress' => 70.0,
            'last_position' => json_encode(['page' => 42]),
        ]);

        $response = $this->actingAs($this->user)
            ->get("/epub/{$this->book->uuid}");

        $response->assertStatus(200)
            ->assertViewHas('maxProgress', function ($progress) {
                return $progress->progress == 70.0;
            });
    }
}
