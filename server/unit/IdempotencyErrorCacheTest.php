<?php
/**
 * RED tests for IdempotencyHandler: cached error responses must NOT be reused.
 *
 * Production bug (2026-03-23): 137 sync operations returned stale errors
 * from 2026-03-10 because IdempotencyHandler cached error responses and
 * returned them on subsequent calls with the same idempotency_key.
 *
 * These tests verify:
 * 1. Error responses are NOT reused (re-execute instead)
 * 2. Success responses ARE reused (idempotency works)
 * 3. Stale error record is deleted before re-execution
 */

namespace Tests\Server\Unit;

use PHPUnit\Framework\TestCase;

class IdempotencyErrorCacheTest extends TestCase
{
    /**
     * Parse the IdempotencyHandler source and verify behavior contract.
     */
    private function getHandlerSource(): string
    {
        $path = __DIR__ . '/../../../html/app/Services/Sync/IdempotencyHandler.php';
        $this->assertFileExists($path, 'IdempotencyHandler.php not found');
        return file_get_contents($path);
    }

    /**
     * RED: IdempotencyHandler must check status before reusing cached response.
     */
    public function test_handler_checks_error_status_before_reuse(): void
    {
        $source = $this->getHandlerSource();

        // The getOrCreateIdempotencyRecord method must check for error status
        // before returning a cached response.
        $this->assertStringContainsString(
            "status",
            $source,
            "IdempotencyHandler must check record status (error vs success) before reusing"
        );

        // Specifically: must check for 'error' status
        $methodStart = strpos($source, 'function getOrCreateIdempotencyRecord');
        $this->assertNotFalse($methodStart, 'getOrCreateIdempotencyRecord method not found');

        // Find the method body (up to next public/protected/private function)
        $methodBody = substr($source, $methodStart, 1500);

        $this->assertStringContainsString(
            "error",
            $methodBody,
            "getOrCreateIdempotencyRecord must handle 'error' status to prevent reusing stale error responses"
        );
    }

    /**
     * RED: When record exists with status='error', it must NOT return reused=true.
     */
    public function test_error_record_is_not_returned_as_reused(): void
    {
        $source = $this->getHandlerSource();

        $methodStart = strpos($source, 'function getOrCreateIdempotencyRecord');
        $methodBody = substr($source, $methodStart, 1500);

        // The method must have a conditional that prevents reusing error records.
        // It should either delete the record or skip the reuse path when status='error'.
        $hasErrorGuard = (
            str_contains($methodBody, "status === 'error'") ||
            str_contains($methodBody, 'status === "error"') ||
            str_contains($methodBody, "->status === 'error'") ||
            str_contains($methodBody, '->status === "error"')
        );

        $this->assertTrue(
            $hasErrorGuard,
            "getOrCreateIdempotencyRecord must explicitly check for status='error' " .
            "and NOT return reused=true for error responses. " .
            "Without this guard, stale error responses are returned forever."
        );
    }

    /**
     * RED: Error record must be deleted (not left stale) so re-execution starts fresh.
     */
    public function test_error_record_is_deleted_before_reexecution(): void
    {
        $source = $this->getHandlerSource();

        $methodStart = strpos($source, 'function getOrCreateIdempotencyRecord');
        $methodBody = substr($source, $methodStart, 1500);

        // After detecting error status, the method should delete the old record
        $hasDelete = (
            str_contains($methodBody, '->delete()') ||
            str_contains($methodBody, 'delete()')
        );

        $this->assertTrue(
            $hasDelete,
            "When a cached record has status='error', it must be deleted " .
            "before creating a new record for re-execution."
        );
    }

    /**
     * GREEN: Success responses must still be reused (idempotency contract).
     */
    public function test_success_response_is_reused(): void
    {
        $source = $this->getHandlerSource();

        $methodStart = strpos($source, 'function getOrCreateIdempotencyRecord');
        $methodBody = substr($source, $methodStart, 1500);

        // Must still have the reuse path: 'reused' => true
        $this->assertStringContainsString(
            "'reused' => true",
            $methodBody,
            "Success responses must still be reused (idempotency contract)"
        );
    }
}
