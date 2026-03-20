<?php

namespace Tests;

use Illuminate\Foundation\Testing\TestCase as BaseTestCase;
use Illuminate\Support\Facades\Cache;

abstract class TestCase extends BaseTestCase
{
    use CreatesApplication;

    protected function setUp(): void
    {
        parent::setUp();
        
        // Disable CSRF for all tests (both app alias and framework middleware class).
        $this->withoutMiddleware(\App\Http\Middleware\VerifyCsrfToken::class);
        $this->withoutMiddleware(\Illuminate\Foundation\Http\Middleware\VerifyCsrfToken::class);
        
        // Ensure the test suite does not depend on a database-backed cache table.
        // Some environments (.env) default to CACHE_STORE=database, but the Server suite
        // may run against existing schemas or schema dumps without the cache table.
        config(['cache.default' => 'array']);
        Cache::flush();
    }

    /**
     * Asserts that the response is a successful page with no error content.
     * Use after GET/POST that should return a normal HTML page (no 500, no exception dump, no Vite/manifest errors).
     *
     * @param \Illuminate\Testing\TestResponse $response
     * @param string $context Optional message prefix for assertions
     */
    protected function assertPageHasNoErrors($response, string $context = 'Page'): void
    {
        $response->assertSessionHasNoErrors();
        $body = $response->getContent();
        $errorIndicators = [
            'Whoops' => 'Laravel exception page',
            'ErrorException' => 'ErrorException in output',
            'Vite manifest' => 'Vite manifest missing/error',
            'Unable to locate' => 'Asset/view not found',
            'stack trace' => 'Stack trace in output',
            '500 | Server Error' => 'Server error title',
            'Internal Server Error' => 'HTTP 500 message',
        ];
        foreach ($errorIndicators as $needle => $desc) {
            $this->assertStringNotContainsString($needle, $body, "{$context}: body must not contain error ({$desc})");
        }
    }
}
