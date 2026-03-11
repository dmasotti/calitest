<?php

namespace Tests\Server;

use App\Services\Sync\Benchmark\MultiUserMetadataScenarioBuilder;
use App\Services\Sync\Benchmark\RealMetadataPool;
use Tests\TestCase;

class MultiUserMetadataScenarioBuilderTest extends TestCase
{
    public function test_builder_is_deterministic_and_embeds_direction_markers_and_edge_variants(): void
    {
        $pool = app(RealMetadataPool::class)->load(
            base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            80
        );
        $builder = new MultiUserMetadataScenarioBuilder($pool);

        $config = [
            'users' => 3,
            'min_books' => 12,
            'max_books' => 12,
            'seed' => 20260310,
            'allow_pre_1970' => true,
        ];

        $first = $builder->build($config);
        $second = $builder->build($config);

        $this->assertSame($first, $second, 'Scenario builder must be deterministic for a fixed seed');

        $flat = [];
        foreach ($first as $plan) {
            foreach ($plan['books'] as $book) {
                $flat[] = $book;
            }
        }

        $states = array_count_values(array_map(fn (array $row) => $row['state'], $flat));
        $this->assertArrayHasKey('same', $states);
        $this->assertArrayHasKey('upload_missing', $states);
        $this->assertArrayHasKey('download_missing', $states);

        $titles = [];
        $pre1970Found = false;
        $unicodeFound = false;
        foreach ($flat as $row) {
            $item = $row['client_item'] ?? $row['server_item'];
            $this->assertNotNull($item);
            $title = (string) $item['title'];
            $titles[] = $title;
            $this->assertMatchesRegularExpression('/^\[[USD]\]\[u\d{3}\]\[b\d{6}\] /', $title);
            if (str_contains($title, 'Québec') || str_contains($item['description'] ?? '', 'Unicode')) {
                $unicodeFound = true;
            }
            if (($item['pubdate'] ?? 0) < 0) {
                $pre1970Found = true;
            }
        }

        $this->assertTrue($unicodeFound, 'Builder must include Unicode permutations from the edge matrix');
        $this->assertTrue($pre1970Found, 'Builder must include signed pre-1970 pubdate cases when enabled');
        $this->assertSame(count($titles), count(array_unique($titles)), 'Synthetic titles must remain unique across the benchmark plan');
    }

    public function test_builder_deduplicates_repeated_authors_tags_and_languages_per_item(): void
    {
        $pool = app(RealMetadataPool::class)->load(
            base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            2000
        );
        $builder = new MultiUserMetadataScenarioBuilder($pool);

        $plans = $builder->build([
            'users' => 10,
            'min_books' => 1000,
            'max_books' => 1000,
            'seed' => 20260310,
            'allow_pre_1970' => false,
        ]);

        foreach ($plans as $plan) {
            foreach ($plan['books'] as $book) {
                foreach (['client_item', 'server_item'] as $side) {
                    $item = $book[$side] ?? null;
                    if (!is_array($item)) {
                        continue;
                    }

                    foreach (['authors', 'tags', 'languages'] as $field) {
                        $values = array_map(
                            static fn ($value) => is_string($value) ? $value : json_encode($value),
                            $item[$field] ?? []
                        );

                        $this->assertSame(
                            count($values),
                            count(array_unique($values)),
                            sprintf(
                                'Benchmark builder must deduplicate %s for %s (%s)',
                                $field,
                                $book['uuid'],
                                $side
                            )
                        );
                    }
                }
            }
        }
    }

    public function test_build_for_user_matches_full_plan_slice_for_same_seed(): void
    {
        $pool = app(RealMetadataPool::class)->load(
            base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            120
        );
        $builder = new MultiUserMetadataScenarioBuilder($pool);

        $config = [
            'users' => 4,
            'min_books' => 12,
            'max_books' => 12,
            'seed' => 20260310,
            'allow_pre_1970' => true,
        ];

        $full = $builder->build($config);

        foreach ($full as $expectedPlan) {
            $userIndex = (int) $expectedPlan['user_index'];
            $this->assertSame(
                $expectedPlan,
                $builder->buildForUser($config, $userIndex),
                sprintf('buildForUser must match full-plan slice for user %d', $userIndex)
            );
        }
    }
}
