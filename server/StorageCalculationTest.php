<?php

namespace Tests\Server;

use App\Models\User;
use App\Models\Library;
use App\Models\UserBook;
use App\Models\BookFile;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Illuminate\Support\Facades\File;
use Tests\TestCase;

class StorageCalculationTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        
        Config::set('subscription.tiers', [
            'free' => [
                'max_storage_mb' => 500,
            ],
        ]);
    }

    /**
     * Test storage calculation includes ebook files
     */
    public function test_storage_includes_ebook_files(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        // Create book file with 10 MB
        BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 10 * 1024 * 1024, // 10 MB
            'is_uploaded' => true,
        ]);
        
        $storageMB = $user->getStorageUsedMB();
        
        $this->assertEquals(10.0, $storageMB);
    }

    /**
     * Test storage calculation includes multiple ebook files
     */
    public function test_storage_includes_multiple_ebook_files(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        $userBook1 = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        $userBook2 = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        // Create files: 5 MB + 3 MB = 8 MB total
        BookFile::factory()->create([
            'book_id' => $userBook1->id,
            'uncompressed_size' => 5 * 1024 * 1024,
            'is_uploaded' => true,
        ]);
        
        BookFile::factory()->create([
            'book_id' => $userBook2->id,
            'uncompressed_size' => 3 * 1024 * 1024,
            'is_uploaded' => true,
        ]);
        
        $storageMB = $user->getStorageUsedMB();
        
        $this->assertEquals(8.0, $storageMB);
    }

    /**
     * Test storage calculation includes local covers
     */
    public function test_storage_includes_local_covers(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Create user book with local cover path
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'cover_optimized_path' => 'images/covers/test.jpg',
            'cover_url' => null, // Local cover, not Cloudflare
        ]);
        
        // Create a temporary cover file for testing
        $coverPath = base_path('images/covers/test.jpg');
        $coverDir = dirname($coverPath);
        
        if (!File::exists($coverDir)) {
            File::makeDirectory($coverDir, 0755, true);
        }
        
        // Create a 500 KB cover file
        File::put($coverPath, str_repeat('x', 500 * 1024));
        
        $storageMB = $user->getStorageUsedMB();
        
        // Should be approximately 0.5 MB (500 KB)
        $this->assertGreaterThanOrEqual(0.48, $storageMB);
        $this->assertLessThanOrEqual(0.52, $storageMB);
        
        // Cleanup
        File::delete($coverPath);
    }

    /**
     * Test storage calculation excludes Cloudflare covers
     */
    public function test_storage_excludes_cloudflare_covers(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Create user book with Cloudflare cover URL
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'cover_url' => 'https://pub-xxx.r2.dev/covers/test.jpg',
            'cover_optimized_path' => null, // Not local
        ]);
        
        $storageMB = $user->getStorageUsedMB();
        
        // Should be 0 (no local storage)
        $this->assertEquals(0.0, $storageMB);
    }

    /**
     * Test storage calculation excludes non-uploaded files
     */
    public function test_storage_excludes_non_uploaded_files(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        // Create uploaded file (should count)
        BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 5 * 1024 * 1024,
            'is_uploaded' => true,
        ]);
        
        // Create non-uploaded file (should not count)
        BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 10 * 1024 * 1024,
            'is_uploaded' => false,
        ]);
        
        $storageMB = $user->getStorageUsedMB();
        
        // Should only count uploaded file (5 MB)
        $this->assertEquals(5.0, $storageMB);
    }

    /**
     * Test storage calculation handles missing cover files gracefully
     */
    public function test_storage_handles_missing_cover_files(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Create user book with cover path that doesn't exist
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'cover_optimized_path' => 'images/covers/nonexistent.jpg',
            'cover_url' => null,
        ]);
        
        // Should not throw error, should return 0
        $storageMB = $user->getStorageUsedMB();
        
        $this->assertEquals(0.0, $storageMB);
    }
}
