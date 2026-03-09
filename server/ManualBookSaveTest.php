<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\Library;
use App\Models\UserBook;
use App\Models\Tag;
use App\Models\Author;
use App\Models\Series;
use App\Services\ManualBookService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use PHPUnit\Framework\Attributes\Test;
use Illuminate\Support\Facades\DB;

class ManualBookSaveTest extends TestCase
{
    use RefreshDatabase;

    protected User $user;
    protected Library $library;
    protected ManualBookService $service;

    protected function setUp(): void
    {
        parent::setUp();
        
        $this->user = User::factory()->create();
        $this->library = Library::factory()->create(['user_id' => $this->user->id]);
        $this->service = app(ManualBookService::class);
    }

    #[Test]
    public function it_creates_book_with_all_metadata()
    {
        $data = [
            'title' => 'Test Book',
            'authors' => ['__new__:John Doe', '__new__:Jane Smith'],
            'tags' => ['__new__:Fiction', '__new__:Mystery'],
            'series' => '__new__:Test Series',
            'series_index' => '1.0',
            'publisher' => '__new__:Test Publisher',
            'language' => '__new__:eng',
            'isbn' => '9781234567890',
            'pubdate' => '2024-01-15',
            'description' => 'Test description',
        ];

        $book = $this->service->createManualBook($this->user, $this->library, $data);
        
        $this->assertNotNull($book);
        $this->assertEquals('Test Book', $book->title);
        
        // Verify authors
        $authors = DB::table('books_authors_link')
            ->join('books_authors', 'books_authors_link.author', '=', 'books_authors.id')
            ->where('books_authors_link.book', $book->uuid)
            ->where('books_authors_link.user_id', $this->user->id)
            ->where('books_authors_link.library_id', $this->library->id)
            ->pluck('books_authors.name');
        
        $this->assertCount(2, $authors);
        $this->assertTrue($authors->contains('John Doe'));
        $this->assertTrue($authors->contains('Jane Smith'));
        
        // Verify tags
        $tags = DB::table('books_tags_link')
            ->join('books_tags', 'books_tags_link.tag', '=', 'books_tags.id')
            ->where('books_tags_link.book', $book->uuid)
            ->where('books_tags_link.user_id', $this->user->id)
            ->where('books_tags_link.library_id', $this->library->id)
            ->pluck('books_tags.name');
        
        $this->assertCount(2, $tags);
        $this->assertTrue($tags->contains('Fiction'));
        $this->assertTrue($tags->contains('Mystery'));
        
        // Verify series
        $series = DB::table('books_series_link')
            ->join('books_series', 'books_series_link.series', '=', 'books_series.id')
            ->where('books_series_link.book', $book->uuid)
            ->where('books_series_link.user_id', $this->user->id)
            ->where('books_series_link.library_id', $this->library->id)
            ->first();
        
        $this->assertNotNull($series);
        $this->assertEquals('Test Series', $series->name);
        $this->assertEquals('1.00', $series->series_index); // Stored as decimal(5,2)
        
        // Verify publisher
        $publisher = DB::table('books_publishers_link')
            ->join('books_publishers', 'books_publishers_link.publisher', '=', 'books_publishers.id')
            ->where('books_publishers_link.book', $book->uuid)
            ->where('books_publishers_link.user_id', $this->user->id)
            ->where('books_publishers_link.library_id', $this->library->id)
            ->first();
        
        $this->assertNotNull($publisher);
        $this->assertEquals('Test Publisher', $publisher->name);
        
        // Verify language
        $language = DB::table('books_languages_link')
            ->join('books_languages', 'books_languages_link.lang_code', '=', 'books_languages.id')
            ->where('books_languages_link.book', $book->uuid)
            ->where('books_languages_link.user_id', $this->user->id)
            ->where('books_languages_link.library_id', $this->library->id)
            ->first();
        
        $this->assertNotNull($language, 'Language was not saved');
        $this->assertEquals('eng', $language->lang_code);
        
        // Verify book fields
        $this->assertEquals('9781234567890', $book->isbn);
        $this->assertStringStartsWith('2024-01-15', $book->pubdate);
        $this->assertEquals('Test description', $book->description);
    }

    #[Test]
    public function it_creates_book_with_cover()
    {
        $coverPath = __DIR__ . '/tmp/test_cover.jpg';
        
        // Create a simple test image
        if (!is_dir(__DIR__ . '/tmp')) {
            mkdir(__DIR__ . '/tmp', 0755, true);
        }
        
        $img = imagecreatetruecolor(600, 800);
        $bgColor = imagecolorallocate($img, 200, 200, 200);
        imagefill($img, 0, 0, $bgColor);
        imagejpeg($img, $coverPath);
        imagedestroy($img);
        
        $uploadedCover = new \Illuminate\Http\UploadedFile(
            $coverPath,
            'cover.jpg',
            'image/jpeg',
            null,
            true
        );

        $data = [
            'title' => 'Book with Cover',
        ];

        $book = $this->service->createManualBook($this->user, $this->library, $data, null, $uploadedCover);
        
        $this->assertNotNull($book);
        
        // Refresh to get latest data
        $book->refresh();
        
        $this->assertEquals(1, $book->has_cover, "Cover was not saved");
        $this->assertNotNull($book->cover_original_hash, "Original cover hash is null");
        $this->assertNotNull($book->cover_optimized_hash, "Optimized cover hash is null");
        
        // Cleanup
        if (file_exists($coverPath)) {
            unlink($coverPath);
        }
    }

    #[Test]
    public function it_creates_book_with_files()
    {
        $epubPath = __DIR__ . '/tmp/test.epub';
        $pdfPath = __DIR__ . '/tmp/test.pdf';
        
        if (!is_dir(__DIR__ . '/tmp')) {
            mkdir(__DIR__ . '/tmp', 0755, true);
        }
        
        // Create dummy files
        file_put_contents($epubPath, 'dummy epub content');
        file_put_contents($pdfPath, 'dummy pdf content');
        
        $files = [
            [
                'format' => 'EPUB',
                'file' => new \Illuminate\Http\UploadedFile($epubPath, 'book.epub', 'application/epub+zip', null, true),
            ],
            [
                'format' => 'PDF',
                'file' => new \Illuminate\Http\UploadedFile($pdfPath, 'book.pdf', 'application/pdf', null, true),
            ],
        ];

        $data = [
            'title' => 'Book with Files',
        ];

        $book = $this->service->createManualBook($this->user, $this->library, $data, $files);
        
        $this->assertNotNull($book);
        
        // Verify files in database
        $bookFiles = DB::table('books_files')
            ->where('book', $book->uuid)
            ->where('user_id', $this->user->id)
            ->where('library_id', $this->library->id)
            ->get();
        
        $this->assertCount(2, $bookFiles);
        
        $formats = $bookFiles->pluck('format')->toArray();
        $this->assertContains('EPUB', $formats);
        $this->assertContains('PDF', $formats);
        
        // Verify files are not marked as missing
        foreach ($bookFiles as $file) {
            $this->assertEquals(0, $file->file_missing);
            $this->assertNotNull($file->file_hash);
        }
        
        // Cleanup
        if (file_exists($epubPath)) unlink($epubPath);
        if (file_exists($pdfPath)) unlink($pdfPath);
    }

    #[Test]
    public function it_updates_book_cover()
    {
        $book = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'has_cover' => false,
        ]);

        $coverPath = __DIR__ . '/tmp/new_cover.jpg';
        
        if (!is_dir(__DIR__ . '/tmp')) {
            mkdir(__DIR__ . '/tmp', 0755, true);
        }
        
        $img = imagecreatetruecolor(600, 800);
        $bgColor = imagecolorallocate($img, 100, 150, 200);
        imagefill($img, 0, 0, $bgColor);
        imagejpeg($img, $coverPath);
        imagedestroy($img);
        
        $uploadedCover = new \Illuminate\Http\UploadedFile(
            $coverPath,
            'new_cover.jpg',
            'image/jpeg',
            null,
            true
        );

        $data = [
            'title' => $book->title,
        ];

        $updatedBook = $this->service->updateManualBook($this->user, $this->library, $book, $data, null, $uploadedCover);
        
        $updatedBook->refresh();
        
        $this->assertEquals(1, $updatedBook->has_cover);
        $this->assertNotNull($updatedBook->cover_original_hash);
        $this->assertNotNull($updatedBook->cover_optimized_hash);
        
        // Cleanup
        if (file_exists($coverPath)) {
            unlink($coverPath);
        }
    }

    #[Test]
    public function it_updates_book_metadata()
    {
        $book = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'title' => 'Original Title',
        ]);
        
        // Add initial author
        $initialAuthor = Author::create([
            'id' => -1,
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'name' => 'Initial Author',
            'uuid' => \Illuminate\Support\Str::uuid(),
        ]);
        
        DB::table('books_authors_link')->insert([
            'book' => $book->uuid,
            'author' => $initialAuthor->id,
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'id' => -1,
            'uuid' => \Illuminate\Support\Str::uuid(),
        ]);

        $data = [
            'title' => 'Updated Title',
            'authors' => ['__new__:New Author'],
            'tags' => ['__new__:Updated Tag'],
            'language' => '__new__:ita',
        ];

        $updatedBook = $this->service->updateManualBook($this->user, $this->library, $book, $data);
        
        $this->assertEquals('Updated Title', $updatedBook->title);
        
        // Verify old author removed and new one added
        $authors = DB::table('books_authors_link')
            ->join('books_authors', 'books_authors_link.author', '=', 'books_authors.id')
            ->where('books_authors_link.book', $book->uuid)
            ->where('books_authors_link.user_id', $this->user->id)
            ->where('books_authors_link.library_id', $this->library->id)
            ->pluck('books_authors.name');
        
        $this->assertCount(1, $authors);
        $this->assertEquals('New Author', $authors->first());
        $this->assertFalse($authors->contains('Initial Author'));
        
        // Verify tag added
        $tags = DB::table('books_tags_link')
            ->join('books_tags', 'books_tags_link.tag', '=', 'books_tags.id')
            ->where('books_tags_link.book', $book->uuid)
            ->where('books_tags_link.user_id', $this->user->id)
            ->where('books_tags_link.library_id', $this->library->id)
            ->pluck('books_tags.name');
        
        $this->assertCount(1, $tags);
        $this->assertEquals('Updated Tag', $tags->first());
        
        // Verify language added
        $language = DB::table('books_languages_link')
            ->join('books_languages', 'books_languages_link.lang_code', '=', 'books_languages.id')
            ->where('books_languages_link.book', $book->uuid)
            ->where('books_languages_link.user_id', $this->user->id)
            ->where('books_languages_link.library_id', $this->library->id)
            ->first();
        
        $this->assertNotNull($language, 'Language was not saved');
        $this->assertEquals('ita', $language->lang_code);
    }

    #[Test]
    public function it_handles_existing_entities_by_uuid()
    {
        // Create existing entities
        $existingAuthor = Author::create([
            'id' => -1,
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'name' => 'Existing Author',
            'uuid' => \Illuminate\Support\Str::uuid(),
        ]);
        
        $existingTag = Tag::create([
            'id' => -1,
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'name' => 'Existing Tag',
            'uuid' => \Illuminate\Support\Str::uuid(),
        ]);

        $data = [
            'title' => 'Book with Existing Entities',
            'authors' => [$existingAuthor->uuid],
            'tags' => [$existingTag->uuid],
        ];

        $book = $this->service->createManualBook($this->user, $this->library, $data);
        
        // Verify it used existing entities, not created new ones
        $authorId = DB::table('books_authors_link')
            ->where('book', $book->uuid)
            ->where('user_id', $this->user->id)
            ->where('library_id', $this->library->id)
            ->value('author');
        
        $this->assertEquals($existingAuthor->id, $authorId);
        
        $tagId = DB::table('books_tags_link')
            ->where('book', $book->uuid)
            ->where('user_id', $this->user->id)
            ->where('library_id', $this->library->id)
            ->value('tag');
        
        $this->assertEquals($existingTag->id, $tagId);
        
        // Verify no duplicate entities created
        $this->assertEquals(1, Author::where('name', 'Existing Author')->count());
        $this->assertEquals(1, Tag::where('name', 'Existing Tag')->count());
    }

    #[Test]
    public function it_removes_relations_when_empty()
    {
        $book = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
        ]);
        
        $author = Author::create([
            'id' => -1,
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'name' => 'Author to Remove',
            'uuid' => \Illuminate\Support\Str::uuid(),
        ]);
        
        DB::table('books_authors_link')->insert([
            'book' => $book->uuid,
            'author' => $author->id,
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'id' => -1,
            'uuid' => \Illuminate\Support\Str::uuid(),
        ]);
        
        $authorCount = DB::table('books_authors_link')
            ->where('book', $book->uuid)
            ->count();
        $this->assertEquals(1, $authorCount);

        // Update with empty authors
        $data = [
            'title' => $book->title,
            'authors' => [],
        ];

        $this->service->updateManualBook($this->user, $this->library, $book, $data);
        
        $authorCount = DB::table('books_authors_link')
            ->where('book', $book->uuid)
            ->count();
        $this->assertEquals(0, $authorCount);
    }
}
