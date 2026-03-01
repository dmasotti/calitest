<?php

namespace Tests\Server;

use App\Services\Sync\BookMetadataHandler;
use App\Services\Sync\CoreDelegate;
use App\Services\SyncService;
use Tests\TestCase;

class IdentifiersSyncNormalizationTest extends TestCase
{
    public function test_sync_hash_changes_when_identifiers_change(): void
    {
        $service = app(SyncService::class);

        $base = [
            'uuid' => '00000000-0000-0000-0000-000000000001',
            'title' => 'Identifiers Hash',
            'authors' => [['name' => 'Author', 'role' => 'author', 'position' => 0]],
            'identifiers' => ['isbn' => '1111111111', 'amazon' => 'A1'],
            'files' => [],
        ];

        $changed = $base;
        $changed['identifiers']['isbn'] = '2222222222';

        $this->assertNotSame(
            $service->computeSyncHashFromItem($base),
            $service->computeSyncHashFromItem($changed)
        );
    }

    public function test_book_metadata_handler_normalizes_identifiers_map_payload(): void
    {
        $core = \Mockery::mock(CoreDelegate::class);
        $handler = new class($core) extends BookMetadataHandler {
            public function normalizeIdentifiersPublic(array $data): array
            {
                return $this->normalizeIdentifiersPayload($data);
            }
        };

        $normalized = $handler->normalizeIdentifiersPublic([
            'isbn' => '978123',
            'amazon' => 'B00TEST',
        ]);

        $this->assertCount(2, $normalized);
        $this->assertSame('isbn', $normalized[0]['type']);
        $this->assertSame('978123', $normalized[0]['value']);
    }
}

