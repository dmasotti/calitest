<?php

namespace Tests\Feature;

use Illuminate\Support\Facades\Artisan;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class SyncV5MerklePayloadGateCommandTest extends TestCase
{
    use RefreshDatabase;

    public function test_merkle_payload_gate_command_runs_and_writes_report(): void
    {
        $reportDir = storage_path('app/perf');
        $before = glob($reportDir . '/sync_v5_merkle_payload_gate_cmd_*.json') ?: [];

        $exitCode = Artisan::call('sync:benchmark-merkle-payload-gate', [
            '--books' => 200,
            '--iterations' => 1,
            '--branch-id' => 0,
        ]);

        $this->assertSame(0, $exitCode, Artisan::output());

        $after = glob($reportDir . '/sync_v5_merkle_payload_gate_cmd_*.json') ?: [];
        $this->assertGreaterThan(count($before), count($after), 'Expected a new benchmark report json file.');
    }
}
