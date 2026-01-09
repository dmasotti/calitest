<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\UserBook;
use App\Services\EbookStorageService;
use App\Services\StorageFileService;
use Illuminate\Support\Facades\Config;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Mockery;
use Tests\TestCase;

class StorageFileServiceTest extends TestCase
{
    protected function tearDown(): void
    {
        Mockery::close();
        parent::tearDown();
    }

    public function test_ensure_stored_file_exists_throws_if_remote_missing()
    {
        $ebookStorage = Mockery::mock(EbookStorageService::class);
        $ebookStorage->shouldReceive('ebookExists')
            ->once()
            ->with('ebooks/missing.epub')
            ->andReturnFalse();

        $service = new StorageFileService($ebookStorage);

        $this->expectException(\RuntimeException::class);
        $this->expectExceptionMessage('StorageFileService: remote upload failed');

        $this->invokeEnsure($service, 'ebooks/missing.epub', true, 'r2');
    }

    public function test_ensure_stored_file_exists_throws_if_local_missing()
    {
        $ebookStorage = Mockery::mock(EbookStorageService::class);
        $service = new StorageFileService($ebookStorage);

        $disk = Mockery::mock();
        Storage::shouldReceive('disk')->with('local')->once()->andReturn($disk);
        $disk->shouldReceive('exists')->with('ebooks/missing.epub')->once()->andReturnFalse();

        $this->expectException(\RuntimeException::class);
        $this->expectExceptionMessage('StorageFileService: local copy missing');

        $this->invokeEnsure($service, 'ebooks/missing.epub', false, 'local');
    }

    public function test_ensure_stored_file_exists_passes_when_remote_present()
    {
        $ebookStorage = Mockery::mock(EbookStorageService::class);
        $ebookStorage->shouldReceive('ebookExists')
            ->once()
            ->with('ebooks/present.epub')
            ->andReturnTrue();

        $service = new StorageFileService($ebookStorage);

        $this->invokeEnsure($service, 'ebooks/present.epub', true, 'r2');
        $this->addToAssertionCount(1);
    }

    public function test_ensure_stored_file_exists_passes_when_local_present()
    {
        $ebookStorage = Mockery::mock(EbookStorageService::class);
        $service = new StorageFileService($ebookStorage);

        $disk = Mockery::mock();
        Storage::shouldReceive('disk')->with('local')->once()->andReturn($disk);
        $disk->shouldReceive('exists')->with('ebooks/present.epub')->once()->andReturnTrue();

        $this->invokeEnsure($service, 'ebooks/present.epub', false, 'local');
        $this->addToAssertionCount(1);
    }

    public function test_store_file_returns_prefixed_hash_for_local_upload()
    {
        Config::set('filesystems.ebook_storage.enabled', false);
        Storage::fake('local');

        $ebookStorage = Mockery::mock(EbookStorageService::class);
        $service = new StorageFileService($ebookStorage);

        $userBook = new UserBook([
            'user_id' => 1,
            'library_id' => 2,
            'uuid' => Str::uuid()->toString(),
        ]);
        $bookFile = new BookFile([
            'format' => 'CBR',
            'name' => 'test.cbr',
        ]);

        $meta = $service->storeFile($userBook, $bookFile, 'content-bytes', 'test.cbr');

        $this->assertStringStartsWith('sha256:', $meta['file_hash']);
        $this->assertTrue(Str::startsWith($meta['file_hash'], 'sha256:'));
    }

    public function test_store_file_returns_prefixed_hash_for_remote_upload()
    {
        Config::set('filesystems.ebook_storage.enabled', true);
        Config::set('filesystems.ebook_storage.provider', 'r2');

        $ebookStorage = Mockery::mock(EbookStorageService::class);
        $ebookStorage->shouldReceive('uploadEbook')
            ->once()
            ->andReturn([
                'storage_key' => 'ebooks/1/2/uuid/hash.cbr',
                'file_hash' => 'sha256:remotehash',
            ]);
        $ebookStorage->shouldReceive('getProvider')->andReturn('r2');
        $ebookStorage->shouldReceive('ebookExists')
            ->once()
            ->andReturnTrue();

        $service = new StorageFileService($ebookStorage);

        $userBook = new UserBook([
            'user_id' => 1,
            'library_id' => 2,
            'uuid' => Str::uuid()->toString(),
        ]);
        $bookFile = new BookFile([
            'format' => 'CBR',
            'name' => 'test.cbr',
        ]);

        $meta = $service->storeFile($userBook, $bookFile, 'content', 'test.cbr');

        $this->assertSame('sha256:remotehash', $meta['file_hash']);
    }

    private function invokeEnsure(StorageFileService $service, string $key, bool $remote, string $provider): void
    {
        $method = new \ReflectionMethod(StorageFileService::class, 'ensureStoredFileExists');
        $method->setAccessible(true);
        $method->invoke($service, $key, $remote, $provider);
    }
}
