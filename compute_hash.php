<?php
/**
 * Helper script to compute metadata hash from JSON file.
 * Usage: php compute_hash.php <json_file>
 */

require __DIR__ . '/../html/vendor/autoload.php';

if ($argc < 2) {
    echo "Error: Missing JSON file argument\n";
    exit(1);
}

$jsonFile = $argv[1];
if (!file_exists($jsonFile)) {
    echo "Error: File not found: $jsonFile\n";
    exit(1);
}

$data = json_decode(file_get_contents($jsonFile), true);
if ($data === null) {
    echo "Error: Invalid JSON\n";
    exit(1);
}

$hash = \App\Services\Sync\MetadataHasher::computeHash($data);
echo $hash;
