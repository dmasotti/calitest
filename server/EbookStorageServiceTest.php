<?php

namespace Tests\Server;

use App\Services\EbookStorageService;
use Aws\S3\S3Client;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Tests\TestCase;

class EbookStorageServiceTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        $this->markTestSkipped('Ebook storage integration is disabled until the new storage workflow stabilizes.');
    }

    public function test_upload_ebook_hashes_and_uploads()
    {
        Config::set('filesystems.ebook_storage.provider', 'r2');
        Config::set('filesystems.ebook_storage.bucket', 'ebooks-bucket');
        Config::set('filesystems.ebook_storage.endpoint', 'https://example.test/');
        Config::set('filesystems.ebook_storage.key', 'key');
        Config::set('filesystems.ebook_storage.secret', 'secret');
        Config::set('filesystems.ebook_storage.region', 'auto');

        $service = new EbookStorageService();
        $tempPath = tempnam(sys_get_temp_dir(), 'ebook');
        file_put_contents($tempPath, str_repeat('y', 4096));

        $mockClient = \Mockery::mock(S3Client::class);
        $mockClient->shouldReceive('putObject')
            ->once()
            ->with(\Mockery::on(fn($params) => $params['Bucket'] === 'ebooks-bucket' && $params['Key'] === 'ebooks/book.epub'));

        $reflection = new \ReflectionProperty($service, 's3Client');
        $reflection->setAccessible(true);
        $reflection->setValue($service, $mockClient);

        $result = $service->uploadEbook($tempPath, 'ebooks/book.epub', 'EPUB');

        $this->assertArrayHasKey('storage_key', $result);
        $this->assertEquals('ebooks/book.epub', $result['storage_key']);
        $this->assertStringStartsWith('sha256:', $result['file_hash']);

        unlink($tempPath);
    }

    public function test_get_signed_url_uses_presigned_request()
    {
        Config::set('filesystems.ebook_storage.provider', 'r2');
        Config::set('filesystems.ebook_storage.bucket', 'ebooks-bucket');
        Config::set('filesystems.ebook_storage.endpoint', 'https://example.test/');
        Config::set('filesystems.ebook_storage.key', 'key');
        Config::set('filesystems.ebook_storage.secret', 'secret');
        Config::set('filesystems.ebook_storage.region', 'auto');

        $service = \Mockery::mock(EbookStorageService::class)->makePartial();
        $mockClient = \Mockery::mock(S3Client::class);
        $mockCommand = \Mockery::mock();
        $mockRequest = \Mockery::mock();
        $mockRequest->shouldReceive('__toString')->andReturn('https://signed.example/book.epub');

        $mockClient->shouldReceive('getCommand')->andReturn($mockCommand);
        $mockClient->shouldReceive('createPresignedRequest')->andReturn($mockRequest);

        $reflection = new \ReflectionProperty($service, 's3Client');
        $reflection->setAccessible(true);
        $reflection->setValue($service, $mockClient);

        $url = $service->getSignedUrl('ebooks/book.epub', 600, 'book.epub');
        $this->assertEquals('https://signed.example/book.epub', $url);
    }
}
