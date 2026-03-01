<?php

namespace Tests\Feature;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Tests\TestCase;

class ReaderSmokeTest extends TestCase
{
    use RefreshDatabase;

    public function test_reader_routes_require_authentication(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $this->get('/epub/' . $book->uuid)->assertStatus(302);
        $this->get('/pdf/' . $book->uuid)->assertStatus(302);
        $this->get('/comic/' . $book->uuid)->assertStatus(302);
    }

    public function test_user_can_open_epub_pdf_and_comic_readers_with_available_files(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Reader Smoke',
            'uuid' => (string) Str::uuid(),
        ]);

        foreach (['EPUB', 'PDF', 'CBZ'] as $format) {
            BookFile::factory()->create([
                'book' => $book->uuid,
                'user_id' => $user->id,
                'library_id' => $library->id,
                'format' => $format,
                'name' => strtolower($format) . '-smoke.' . strtolower($format),
                'storage_key' => 'ebooks/smoke/' . strtolower($format) . '.bin',
                'storage_provider' => 'r2',
                'file_hash' => hash('sha256', $format . '-smoke'),
                'is_uploaded' => true,
                'needs_file_upload' => false,
                'file_missing' => false,
                'uuid' => (string) Str::uuid(),
            ]);
        }

        $this->actingAs($user)->get('/epub/' . $book->uuid)->assertOk();
        $this->actingAs($user)->get('/pdf/' . $book->uuid)->assertOk();
        $this->actingAs($user)->get('/comic/' . $book->uuid)->assertOk();
    }
}

