<?php

namespace Tests\Server;

use App\Services\StorageCoverService;
use Aws\S3\S3Client;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Tests\TestCase;

class StorageCoverServiceTest extends TestCase
{
    use RefreshDatabase;

    public function test_upload_cover_calls_s3_and_returns_public_url()
    {
        Config::set('filesystems.cover_storage.provider', 'r2');
        Config::set('filesystems.cover_storage.bucket', 'covers-bucket');
        Config::set('filesystems.cover_storage.endpoint', 'https://example.test/');
        Config::set('filesystems.cover_storage.key', 'key');
        Config::set('filesystems.cover_storage.secret', 'secret');
        Config::set('filesystems.cover_storage.region', 'auto');
        Config::set('filesystems.cover_storage.public_url', 'https://cdn.example.test');

        $service = new StorageCoverService();

        $tempPath = tempnam(sys_get_temp_dir(), 'cover');
        file_put_contents($tempPath, str_repeat('x', 2048));

        $mockClient = \Mockery::mock(S3Client::class);
        $mockClient->shouldReceive('putObject')
            ->once()
            ->with(\Mockery::on(function ($params) use ($tempPath) {
                return $params['Key'] === 'covers/test.jpg'
                    && $params['Bucket'] === 'covers-bucket'
                    && $params['ContentType'] === 'image/jpeg';
            }));

        $reflection = new \ReflectionProperty($service, 's3Client');
        $reflection->setAccessible(true);
        $reflection->setValue($service, $mockClient);

        $url = $service->uploadCover($tempPath, 'covers/test.jpg');

        $this->assertEquals('https://cdn.example.test/covers/test.jpg', $url);

        unlink($tempPath);
    }
}
