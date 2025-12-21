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

        $ids = [1, 2, 3, 7, 9, 10];
        foreach ($ids as $id) {
            UserBook::create([
                'user_id' => $user->id,
                'library_id' => $library->id,
                'id' => $id,
                'title' => 'Book ' . $id,
                'last_modified' => now(),
            ]);
        }

        $service = app(SyncService::class);
        $method = new \ReflectionMethod($service, 'buildCalibreInventory');
        $method->setAccessible(true);
        $inventory = $method->invoke($service, $user, $library->id, null);

        $this->assertSame(1, $inventory['min']);
        $this->assertSame(10, $inventory['max']);
        $this->assertSame(['1-3', 7, '9-10'], $inventory['active']);
        $this->assertSame(['4-6', 8], $inventory['missing']);
    }

    public function test_expand_inventory_prefers_active(): void
    {
        $service = app(SyncService::class);
        $method = new \ReflectionMethod($service, 'expandInventoryIds');
        $method->setAccessible(true);

        $inventory = [
            'min' => 1,
            'max' => 5,
            'active' => ['1-3', 5],
            'missing' => [],
        ];

        $set = $method->invoke($service, $inventory);
        $this->assertArrayHasKey(1, $set);
        $this->assertArrayHasKey(2, $set);
        $this->assertArrayHasKey(3, $set);
        $this->assertArrayHasKey(5, $set);
        $this->assertArrayNotHasKey(4, $set);
    }

    public function test_expand_inventory_from_missing_ranges(): void
    {
        $service = app(SyncService::class);
        $method = new \ReflectionMethod($service, 'expandInventoryIds');
        $method->setAccessible(true);

        $inventory = [
            'min' => 1,
            'max' => 5,
            'active' => [],
            'missing' => [2, '4-5'],
        ];

        $set = $method->invoke($service, $inventory);
        $this->assertArrayHasKey(1, $set);
        $this->assertArrayHasKey(3, $set);
        $this->assertArrayNotHasKey(2, $set);
        $this->assertArrayNotHasKey(4, $set);
        $this->assertArrayNotHasKey(5, $set);
    }
}
