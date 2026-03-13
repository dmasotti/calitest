<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Models\UserBookVersion;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Tests\TestCase;

class UserBookVersioningEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    public function test_no_version_is_created_for_noop_save(): void
    {
        [$user, $library, $book] = $this->makeBook();

        $book->title = $book->title;
        $book->save();

        $this->assertSame(0, $this->versionCountFor($book), 'No-op save must not create a version.');
    }

    public function test_no_version_is_created_when_only_sync_timestamp_changes(): void
    {
        [$user, $library, $book] = $this->makeBook();

        $book->last_modified = now()->addMinute();
        $book->save();

        $this->assertSame(
            0,
            $this->versionCountFor($book),
            'Sync timestamp-only churn must not create a new version snapshot.'
        );
    }

    public function test_version_is_created_when_title_changes(): void
    {
        [$user, $library, $book] = $this->makeBook();

        $book->title = 'Changed Title';
        $book->save();

        $this->assertSame(1, $this->versionCountFor($book));
        $snapshot = $this->latestSnapshotFor($book);
        $this->assertSame('Original Title', $snapshot['title'] ?? null);
    }

    public function test_version_is_created_when_status_changes(): void
    {
        [$user, $library, $book] = $this->makeBook(['status' => 'reading']);

        $book->status = 'finished';
        $book->save();

        $this->assertSame(1, $this->versionCountFor($book));
        $snapshot = $this->latestSnapshotFor($book);
        $this->assertSame('reading', $snapshot['status'] ?? null);
    }

    public function test_version_is_created_when_cover_hash_changes(): void
    {
        [$user, $library, $book] = $this->makeBook([
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'has_cover' => true,
        ]);

        $book->cover_original_hash = 'sha256:' . str_repeat('b', 64);
        $book->save();

        $this->assertSame(1, $this->versionCountFor($book));
        $snapshot = $this->latestSnapshotFor($book);
        $this->assertSame('sha256:' . str_repeat('a', 64), $snapshot['cover_hash'] ?? null);
    }

    public function test_version_is_not_duplicated_when_same_cover_hash_is_saved_again(): void
    {
        [$user, $library, $book] = $this->makeBook([
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'has_cover' => true,
        ]);

        $book->cover_original_hash = 'sha256:' . str_repeat('b', 64);
        $book->save();
        $book->refresh();

        $book->cover_original_hash = 'sha256:' . str_repeat('b', 64);
        $book->save();

        $this->assertSame(
            1,
            $this->versionCountFor($book),
            'Saving the same effective cover state twice must not create duplicate versions.'
        );
    }

    public function test_no_version_is_created_when_same_status_is_saved_again(): void
    {
        [$user, $library, $book] = $this->makeBook(['status' => 'reading']);

        $book->status = 'reading';
        $book->save();

        $this->assertSame(0, $this->versionCountFor($book));
    }

    public function test_version_is_created_when_favorite_changes(): void
    {
        [$user, $library, $book] = $this->makeBook(['favorite' => false]);

        $book->favorite = true;
        $book->save();

        $this->assertSame(1, $this->versionCountFor($book));
        $snapshot = $this->latestSnapshotFor($book);
        $this->assertFalse((bool) ($snapshot['favorite'] ?? true));
    }

    public function test_version_is_created_when_series_index_changes(): void
    {
        [$user, $library, $book] = $this->makeBook(['series_index' => 1.0]);

        $book->series_index = 2.5;
        $book->save();

        $this->assertSame(1, $this->versionCountFor($book));
        $snapshot = $this->latestSnapshotFor($book);
        $this->assertSame(1.0, (float) ($snapshot['series_index'] ?? -1));
    }

    public function test_version_is_created_when_custom_metadata_changes(): void
    {
        [$user, $library, $book] = $this->makeBook([
            'custom_metadata' => ['reading_mode' => 'paged'],
        ]);

        $book->custom_metadata = ['reading_mode' => 'scroll'];
        $book->save();

        $this->assertSame(1, $this->versionCountFor($book));
        $snapshot = $this->latestSnapshotFor($book);
        $this->assertSame('paged', $snapshot['custom_metadata']['reading_mode'] ?? null);
    }

    public function test_version_is_created_when_custom_metadata_is_removed(): void
    {
        [$user, $library, $book] = $this->makeBook([
            'custom_metadata' => ['reading_mode' => 'paged', 'density' => 'comfortable'],
        ]);

        $book->custom_metadata = [];
        $book->save();

        $this->assertSame(1, $this->versionCountFor($book));
        $snapshot = $this->latestSnapshotFor($book);
        $this->assertSame('paged', $snapshot['custom_metadata']['reading_mode'] ?? null);
        $this->assertSame('comfortable', $snapshot['custom_metadata']['density'] ?? null);
    }

    public function test_version_is_created_when_has_cover_toggles(): void
    {
        [$user, $library, $book] = $this->makeBook(['has_cover' => false]);

        $book->has_cover = true;
        $book->save();

        $this->assertSame(1, $this->versionCountFor($book));
        $snapshot = $this->latestSnapshotFor($book);
        $this->assertFalse((bool) ($snapshot['has_cover'] ?? true));
    }

    public function test_version_is_created_when_publisher_changes(): void
    {
        [$user, $library, $book] = $this->makeBook(['publisher' => 'Old Publisher']);

        $book->publisher = 'New Publisher';
        $book->save();

        $this->assertSame(1, $this->versionCountFor($book));
        $snapshot = $this->latestSnapshotFor($book);
        $this->assertSame('Old Publisher', $snapshot['publisher'] ?? null);
    }

    public function test_no_version_is_created_when_custom_metadata_is_saved_with_same_effective_payload(): void
    {
        [$user, $library, $book] = $this->makeBook([
            'custom_metadata' => ['reading_mode' => 'paged', 'density' => 'comfortable'],
        ]);

        $book->custom_metadata = ['reading_mode' => 'paged', 'density' => 'comfortable'];
        $book->save();

        $this->assertSame(0, $this->versionCountFor($book));
    }

    public function test_no_version_is_created_when_has_cover_is_saved_with_same_value(): void
    {
        [$user, $library, $book] = $this->makeBook(['has_cover' => true]);

        $book->has_cover = true;
        $book->save();

        $this->assertSame(0, $this->versionCountFor($book));
    }

    public function test_no_version_is_created_when_favorite_is_saved_with_same_value(): void
    {
        [$user, $library, $book] = $this->makeBook(['favorite' => true]);

        $book->favorite = true;
        $book->save();

        $this->assertSame(0, $this->versionCountFor($book));
    }

    private function makeBook(array $overrides = []): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::create(array_merge([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'id' => 100,
            'title' => 'Original Title',
            'path' => 'original-title',
            'last_modified' => now(),
        ], $overrides));

        return [$user, $library, $book];
    }

    private function versionCountFor(UserBook $book): int
    {
        return UserBookVersion::where('book_id', $book->uuid)->count();
    }

    private function latestSnapshotFor(UserBook $book): array
    {
        return UserBookVersion::where('book_id', $book->uuid)->latest('id')->value('snapshot') ?? [];
    }
}
