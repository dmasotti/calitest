<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use Symfony\Component\HttpFoundation\StreamedResponse;
use Tests\TestCase;

class GzipApiResponseMiddlewareTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        Route::middleware('api')->post('/api/test/gzip-response-echo', function (Request $request) {
            return response()->json([
                'payload' => $request->all(),
                'blob' => str_repeat('x', 4096),
            ]);
        });

        Route::middleware('api')->get('/api/test/gzip-response-stream', function () {
            return new StreamedResponse(function () {
                echo json_encode(['stream' => true], JSON_THROW_ON_ERROR);
            }, 200, ['Content-Type' => 'application/json']);
        });

        Route::middleware('api')->get('/api/test/gzip-response-preencoded', function () {
            return response()->json(['pre' => true])->header('Content-Encoding', 'br');
        });
    }

    public function test_it_gzips_json_api_response_when_requested(): void
    {
        $response = $this->call(
            'POST',
            '/api/test/gzip-response-echo',
            [],
            [],
            [],
            [
                'CONTENT_TYPE' => 'application/json',
                'HTTP_ACCEPT' => 'application/json',
                'HTTP_ACCEPT_ENCODING' => 'gzip',
            ],
            json_encode(['k' => 'v'], JSON_THROW_ON_ERROR)
        );

        $response->assertStatus(200);
        $response->assertHeader('Content-Encoding', 'gzip');

        $decoded = gzdecode($response->getContent());
        $this->assertNotFalse($decoded, 'Response body should be valid gzip stream');

        $decodedJson = json_decode($decoded, true);
        $this->assertSame('v', $decodedJson['payload']['k'] ?? null);
    }

    public function test_it_keeps_json_response_plain_without_accept_encoding_gzip(): void
    {
        $response = $this->postJson('/api/test/gzip-response-echo', ['k' => 'v']);
        $response->assertStatus(200);
        $response->assertHeaderMissing('Content-Encoding');
        $response->assertJsonPath('payload.k', 'v');
    }

    public function test_it_gzips_when_accept_encoding_contains_multiple_values(): void
    {
        $response = $this->call(
            'POST',
            '/api/test/gzip-response-echo',
            [],
            [],
            [],
            [
                'CONTENT_TYPE' => 'application/json',
                'HTTP_ACCEPT' => 'application/json',
                'HTTP_ACCEPT_ENCODING' => 'gzip, br',
            ],
            json_encode(['k' => 'v'], JSON_THROW_ON_ERROR)
        );

        $response->assertStatus(200);
        $response->assertHeader('Content-Encoding', 'gzip');
    }

    public function test_it_keeps_small_json_plain_even_when_gzip_is_accepted(): void
    {
        putenv('API_GZIP_RESPONSE_MIN_BYTES=10000');
        try {
            $response = $this->call(
                'POST',
                '/api/test/gzip-response-echo',
                [],
                [],
                [],
                [
                    'CONTENT_TYPE' => 'application/json',
                    'HTTP_ACCEPT' => 'application/json',
                    'HTTP_ACCEPT_ENCODING' => 'gzip',
                ],
                json_encode(['k' => 'v'], JSON_THROW_ON_ERROR)
            );

            $response->assertStatus(200);
            $response->assertHeaderMissing('Content-Encoding');
            $response->assertJsonPath('payload.k', 'v');
        } finally {
            putenv('API_GZIP_RESPONSE_MIN_BYTES');
        }
    }

    public function test_it_does_not_gzip_streamed_json_response(): void
    {
        $response = $this->call(
            'GET',
            '/api/test/gzip-response-stream',
            [],
            [],
            [],
            [
                'HTTP_ACCEPT' => 'application/json',
                'HTTP_ACCEPT_ENCODING' => 'gzip',
            ]
        );

        $response->assertStatus(200);
        $response->assertHeaderMissing('Content-Encoding');
        $this->assertStringContainsString('stream', $response->streamedContent());
    }

    public function test_it_does_not_recompress_response_when_content_encoding_already_present(): void
    {
        $response = $this->call(
            'GET',
            '/api/test/gzip-response-preencoded',
            [],
            [],
            [],
            [
                'HTTP_ACCEPT' => 'application/json',
                'HTTP_ACCEPT_ENCODING' => 'gzip',
            ]
        );

        $response->assertStatus(200);
        $response->assertHeader('Content-Encoding', 'br');
    }
}
