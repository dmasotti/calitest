<?php

namespace Tests\Server;

use App\Models\BookFile;
use Illuminate\Database\QueryException;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class BookFileFactoryTest extends TestCase
{
    use RefreshDatabase;

    public function test_uuid_is_required_for_book_files(): void
    {
        $this->expectException(QueryException::class);

        BookFile::factory()->create([
            'uuid' => null,
        ]);
    }
}
