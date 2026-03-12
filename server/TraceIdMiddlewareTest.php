<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use Tests\TestCase;

class TraceIdMiddlewareTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        Route::middleware('api')->get('/api/test/trace-id', function (Request $request) {
            return response()->json([
                'trace_id' => $request->attributes->get('trace_id'),
            ]);
        });
    }

    public function test_it_reuses_incoming_trace_id_header(): void
    {
        $response = $this->getJson('/api/test/trace-id', [
            'X-Trace-Id' => 'trace-client-123',
        ]);

        $response->assertStatus(200);
        $response->assertHeader('X-Trace-Id', 'trace-client-123');
        $response->assertJsonPath('trace_id', 'trace-client-123');
    }

    public function test_it_generates_trace_id_when_missing(): void
    {
        $response = $this->getJson('/api/test/trace-id');

        $response->assertStatus(200);
        $generated = (string) $response->headers->get('X-Trace-Id');
        $this->assertNotSame('', $generated);
        $response->assertJsonPath('trace_id', $generated);
    }
}
