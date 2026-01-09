<?php

namespace Tests\Server;

use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use App\Services\Sync\CoreDelegate;
use Illuminate\Support\Collection;
use Tests\TestCase;

class BookMetadataHandlerCoverHashesTest extends TestCase
{
    public function test_build_item_includes_both_cover_hashes()
    {
        $core = \Mockery::mock(CoreDelegate::class);
        $core->shouldReceive('ensureUserBookUuid')->andReturn('11111111-1111-1111-1111-111111111111');
        $core->shouldReceive('toUnixTimestamp')->andReturn(null);
        $core->shouldReceive('normalizePubdate')->andReturn(null);
        $core->shouldReceive('getItemVersion')->andReturn(1);

        // Stub handler to avoid DB-backed relationship loading/joins.
        $handler = new class($core) extends BookMetadataHandler {
            public function buildIdentifiersArray(UserBook $userBook): array { return []; }
            public function buildAuthorsArray(UserBook $userBook): array { return []; }
            public function buildSeriesObject(UserBook $userBook): ?array { return null; }
            public function buildTagsArray(UserBook $userBook): array { return []; }
            public function getLanguagesForUserBook(UserBook $userBook): array { return []; }
            public function getPublisherForUserBook(UserBook $userBook): ?string { return null; }
            public function getRatingForUserBook(UserBook $userBook): ?int { return null; }
            protected function buildFilesPayload(UserBook $userBook): array { return []; }
        };

        $book = new UserBook();
        $book->id = 10;
        $book->uuid = '11111111-1111-1111-1111-111111111111';
        $book->user_id = 1;
        $book->library_id = 2;
        $book->title = 'Test';
        $book->cover_original_hash = 'sha256:orig';
        $book->cover_optimized_hash = 'sha256:opt';
        $book->cover_optimized_path = 'covers/opt.jpg';

        // Preload relations to prevent lazy-loading attempts.
        $book->setRelation('files', new Collection());
        $book->setRelation('authors', new Collection());
        $book->setRelation('tags', new Collection());
        $book->setRelation('series', null);

        $item = $handler->buildItemFromUserBook($book);

        $this->assertSame('sha256:orig', $item['cover']['cover_hash']);
        $this->assertSame('sha256:opt', $item['cover']['cover_hash_optimized']);
    }
}


