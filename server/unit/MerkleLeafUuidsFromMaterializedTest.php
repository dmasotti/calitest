<?php
/**
 * RED tests: getLeafUuids must read from materialized uuids_json column,
 * NOT from source tables via heavy JOIN.
 *
 * Production bug (2026-03-23): Merkle leaf-uuids query for files dimension
 * timed out (>10s, nginx 504) because getLeafUuids() called
 * loadLeafUuidsFromSource() which does:
 *   SELECT b.uuid FROM books_files bf JOIN books b ...
 *   WHERE substr(lower(replace(b.uuid,'-','')),1,2) = ?
 *
 * The sync_merkle_leaves table already has a uuids_json column populated
 * with all UUIDs per leaf. The fix is to read from it.
 */

namespace Tests\Server\Unit;

use PHPUnit\Framework\TestCase;

class MerkleLeafUuidsFromMaterializedTest extends TestCase
{
    private function getServiceSource(): string
    {
        $path = __DIR__ . '/../../../html/app/Services/Sync/MaterializedMerkleService.php';
        $this->assertFileExists($path);
        return file_get_contents($path);
    }

    /**
     * RED: getLeafUuids must read from sync_merkle_leaves.uuids_json,
     * not call loadLeafUuidsFromSource.
     */
    public function test_getLeafUuids_reads_from_materialized_table(): void
    {
        $source = $this->getServiceSource();

        // Find getLeafUuids method body
        $methodStart = strpos($source, 'public function getLeafUuids(');
        $this->assertNotFalse($methodStart, 'getLeafUuids method not found');

        // Find next public/private/protected method
        $nextMethod = strpos($source, "\n    public function ", $methodStart + 10);
        if ($nextMethod === false) {
            $nextMethod = strpos($source, "\n    private function ", $methodStart + 10);
        }
        $methodBody = substr($source, $methodStart, ($nextMethod ?: strlen($source)) - $methodStart);

        // Must NOT call loadLeafUuidsFromSource (the heavy JOIN path)
        $this->assertStringNotContainsString(
            'loadLeafUuidsFromSource',
            $methodBody,
            "getLeafUuids must NOT call loadLeafUuidsFromSource — " .
            "it causes 504 timeout on files dimension (36000 row JOIN). " .
            "Must read from sync_merkle_leaves.uuids_json instead."
        );
    }

    /**
     * RED: getLeafUuids must reference uuids_json column.
     */
    public function test_getLeafUuids_uses_uuids_json_column(): void
    {
        $source = $this->getServiceSource();

        $methodStart = strpos($source, 'public function getLeafUuids(');
        $nextMethod = strpos($source, "\n    public function ", $methodStart + 10);
        if ($nextMethod === false) {
            $nextMethod = strpos($source, "\n    private function ", $methodStart + 10);
        }
        $methodBody = substr($source, $methodStart, ($nextMethod ?: strlen($source)) - $methodStart);

        $this->assertStringContainsString(
            'uuids_json',
            $methodBody,
            "getLeafUuids must read from the materialized uuids_json column " .
            "in sync_merkle_leaves (already populated for all 3 dimensions)."
        );
    }

    /**
     * RED: getLeafUuids must query sync_merkle_leaves table.
     */
    public function test_getLeafUuids_queries_materialized_leaves_table(): void
    {
        $source = $this->getServiceSource();

        $methodStart = strpos($source, 'public function getLeafUuids(');
        $nextMethod = strpos($source, "\n    public function ", $methodStart + 10);
        if ($nextMethod === false) {
            $nextMethod = strpos($source, "\n    private function ", $methodStart + 10);
        }
        $methodBody = substr($source, $methodStart, ($nextMethod ?: strlen($source)) - $methodStart);

        $this->assertStringContainsString(
            'sync_merkle_leaves',
            $methodBody,
            "getLeafUuids must query sync_merkle_leaves table directly."
        );
    }

    /**
     * GREEN: loadLeafUuidsFromSource still exists as fallback.
     */
    public function test_loadLeafUuidsFromSource_still_exists(): void
    {
        $source = $this->getServiceSource();

        $this->assertStringContainsString(
            'function loadLeafUuidsFromSource',
            $source,
            "loadLeafUuidsFromSource must still exist (fallback if uuids_json empty)."
        );
    }

    /**
     * GREEN: uuids_json column must be populated during leaf rebuild.
     */
    public function test_leaf_rebuild_populates_uuids_json(): void
    {
        $source = $this->getServiceSource();

        // The insert/rebuild code must include uuids_json
        $this->assertStringContainsString(
            'uuids_json',
            $source,
            "Leaf rebuild must populate uuids_json column."
        );
    }
}
