<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\SyncService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class SyncInventoryTest extends TestCase
{
    use RefreshDatabase;

    public function test_build_inventory_compresses_ranges(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        $uuids = [
            '11111111-1111-1111-1111-111111111111',
            '22222222-2222-2222-2222-222222222222',
            '33333333-3333-3333-3333-333333333333',
            '44444444-4444-4444-4444-444444444444',
        ];
        foreach ($uuids as $uuid) {
            UserBook::create([
                'user_id' => $user->id,
                'library_id' => $library->id,
                'title' => 'Book ' . $uuid,
                'last_modified' => now(),
                'uuid' => $uuid,
            ]);
        }

        $service = app(SyncService::class);
        $method = new \ReflectionMethod($service, 'buildCalibreInventory');
        $method->setAccessible(true);
        $inventory = $method->invoke($service, $user, $library->id, null);

        $this->assertSame($uuids, $inventory['uuids']);
    }

    public function test_expand_inventory_prefers_active(): void
    {
        $service = app(SyncService::class);
        $method = new \ReflectionMethod($service, 'expandInventoryUuids');
        $method->setAccessible(true);

        $inventory = [
            'uuids' => ['aaa', 'bbb', 'ccc'],
        ];

        $set = $method->invoke($service, $inventory);
        $this->assertArrayHasKey('aaa', $set);
        $this->assertArrayHasKey('bbb', $set);
        $this->assertArrayHasKey('ccc', $set);
        $this->assertArrayNotHasKey('ddd', $set);
    }

    public function test_expand_inventory_from_missing_ranges(): void
    {
        $service = app(SyncService::class);
        $method = new \ReflectionMethod($service, 'expandInventoryUuids');
        $method->setAccessible(true);

        $inventory = [
            'uuids' => ['x1', 'x2'],
        ];

        $set = $method->invoke($service, $inventory);
        $this->assertArrayHasKey('x1', $set);
        $this->assertArrayHasKey('x2', $set);
    }
}
