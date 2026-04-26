<?php

namespace Tests\Server;

use App\Models\Device;
use App\Models\DeviceAuthorization;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class ReadingProgressDeviceResolutionTest extends TestCase
{
    use RefreshDatabase;

    public function test_reading_progress_accepts_device_uuid_from_device_token(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $deviceToken = 'test-device-token';
        $deviceUuid = 'test-device-uuid';

        DeviceAuthorization::create([
            'device_token' => $deviceToken,
            'device_uuid' => $deviceUuid,
            'user_id' => $user->id,
            'device_name' => 'Test Device',
            'platform' => 'android',
            'authorized' => true,
            'authorized_at' => now(),
        ]);

        $response = $this->withHeaders([
            'Authorization' => 'Bearer ' . $deviceToken,
        ])->postJson("/api/books/{$book->uuid}/reading-progress", [
            'library_id' => $library->id,
            'format' => 'EPUB',
            'progress_bp' => 1234,
        ]);

        $response->assertStatus(200)
            ->assertJson([
                'book_uuid' => $book->uuid,
                'progress_bp' => 1234,
                'format' => 'EPUB',
            ]);

        $device = Device::where('user_id', $user->id)
            ->where('device_uuid', $deviceUuid)
            ->first();

        $this->assertNotNull($device);

        $record = DB::table('books_devices_progress')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('book_uuid', $book->uuid)
            ->where('device_id', $device->id)
            ->first();

        $this->assertNotNull($record);
        $this->assertEquals(1234, $record->progress_bp);
    }
}
