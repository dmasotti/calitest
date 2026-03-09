<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\UserBook;
use App\Models\BookFile;
use Illuminate\Foundation\Testing\RefreshDatabase;
use PHPUnit\Framework\Attributes\Test;

class PdfReaderTest extends TestCase
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
            'title' => 'Test PDF Book',
        ]);

        BookFile::factory()->create([
            'book' => $this->book->uuid,
            'user_id' => $this->user->id,
            'library_id' => $this->book->library_id,
            'format' => 'PDF',
        ]);
    }

    #[Test]
    public function it_can_load_pdf_reader_page()
    {
        $response = $this->actingAs($this->user)
            ->get("/pdf/{$this->book->uuid}");

        $response->assertStatus(200)
            ->assertViewIs('pdf-reader')
            ->assertViewHas('book', function ($viewBook) {
                return $viewBook->uuid === $this->book->uuid;
            });
    }

    #[Test]
    public function it_requires_authentication_to_view_pdf()
    {
        $response = $this->get("/pdf/{$this->book->uuid}");

        $response->assertRedirect('/login');
    }

    #[Test]
    public function it_returns_404_for_nonexistent_book()
    {
        $response = $this->actingAs($this->user)
            ->get("/pdf/nonexistent-uuid");

        $response->assertStatus(404);
    }

    #[Test]
    public function it_loads_max_progress_from_all_formats()
    {
        $device = \App\Models\Device::factory()->create([
            'user_id' => $this->user->id,
        ]);

        // PDF at 40%
        \App\Models\BookDeviceProgress::create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'device_id' => $device->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'PDF',
            'progress_bp' => 4000,
            'client_ts' => now(),
        ]);

        // EPUB at 80% (higher)
        \App\Models\BookDeviceProgress::create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'device_id' => $device->id,
            'book_uuid' => $this->book->uuid,
            'format' => 'EPUB',
            'progress_bp' => 8000,
            'client_ts' => now(),
        ]);

        $response = $this->actingAs($this->user)
            ->get("/pdf/{$this->book->uuid}");

        $response->assertStatus(200)
            ->assertViewHas('initialProgress', function ($progress) {
                return $progress == 80.0;
            });
    }
}
