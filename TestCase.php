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
        
        // Disable CSRF for all tests
        $this->withoutMiddleware(\App\Http\Middleware\VerifyCsrfToken::class);
        
        // Ensure the test suite does not depend on a database-backed cache table.
        // Some environments (.env) default to CACHE_STORE=database, but the Server suite
        // may run against existing schemas or schema dumps without the cache table.
        config(['cache.default' => 'array']);
        Cache::flush();
    }
}
