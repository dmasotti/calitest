<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\UserBook;
use App\Models\BookFile;
use Illuminate\Foundation\Testing\RefreshDatabase;
use PHPUnit\Framework\Attributes\Test;

class EpubReaderTest extends TestCase
{
    use RefreshDatabase;

    protected User $user;
    protected UserBook $book;
    protected \App\Models\Library $library;

    protected function setUp(): void
    {
        parent::setUp();
        
        $this->user = User::factory()->create();
        $this->library = \App\Models\Library::factory()->create([
            'user_id' => $this->user->id,
        ]);
        $this->book = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'title' => 'Test EPUB Book',
        ]);

        BookFile::factory()->create([
            'book' => $this->book->uuid,
            'user_id' => $this->user->id,
            'library_id' => $this->book->library_id,
            'format' => 'EPUB',
        ]);
    }

    #[Test]
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

    #[Test]
    public function it_requires_authentication_to_view_epub()
    {
        $response = $this->get("/epub/{$this->book->uuid}");

        $response->assertRedirect('/login');
    }

    #[Test]
    public function it_returns_404_for_nonexistent_book()
    {
        $response = $this->actingAs($this->user)
            ->get("/epub/nonexistent-uuid");

        $response->assertStatus(404);
    }

    #[Test]
    public function it_loads_max_progress_from_all_formats()
    {
        // Create progress for different formats
        $device = \App\Models\Device::factory()->create([
            'user_id' => $this->user->id,
        ]);

        // EPUB at 30%
        \App\Models\BookDeviceProgress::create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'device_id' => $device->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress_bp' => 3000,
            'client_ts' => now(),
        ]);

        // PDF at 70% (higher)
        \App\Models\BookDeviceProgress::create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'device_id' => $device->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'PDF',
            'progress_bp' => 7000,
            'client_ts' => now(),
        ]);

        $response = $this->actingAs($this->user)
            ->get("/epub/{$this->book->uuid}");

        $response->assertStatus(200)
            ->assertViewHas('initialProgress', function ($progress) {
                return $progress == 70.0;
            });
    }
}
