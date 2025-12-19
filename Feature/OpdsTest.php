<?php

namespace Tests\Feature;

use Tests\TestCase;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Illuminate\Database\Schema\Blueprint;

class OpdsTest extends TestCase
{
    use DatabaseTransactions;

    protected function setUp(): void
    {
        parent::setUp();

        if (! Schema::hasTable('users')) {
            Schema::create('users', function (Blueprint $table) {
                $table->id();
                $table->string('name')->nullable();
                $table->string('email')->unique();
                $table->string('username')->nullable()->unique();
                $table->string('password')->nullable();
                $table->string('subscription_tier')->default('free');
                $table->string('subscription_status')->default('active');
                $table->timestamps();
            });
        }

        if (! Schema::hasTable('opds_books')) {
            Schema::create('opds_books', function (Blueprint $table) {
                $table->id();
                $table->string('title')->nullable();
                $table->string('file_path')->nullable();
                $table->string('mime_type')->nullable();
                $table->unsignedBigInteger('user_id')->nullable();
                $table->unsignedBigInteger('library_id')->nullable();
                $table->timestamps();
            });
        }

        if (! Schema::hasTable('user_app_passwords')) {
            Schema::create('user_app_passwords', function (Blueprint $table) {
                $table->id();
                $table->unsignedBigInteger('user_id');
                $table->string('name');
                $table->string('password_hash');
                $table->timestamp('last_used_at')->nullable();
                $table->timestamp('expires_at')->nullable();
                $table->timestamps();
            });
        }

        if (! Schema::hasTable('user_subscription_overrides')) {
            Schema::create('user_subscription_overrides', function (Blueprint $table) {
                $table->id();
                $table->unsignedBigInteger('user_id')->index();
                $table->string('override_tier', 20)->nullable();
                $table->unsignedInteger('override_max_libraries')->nullable();
                $table->unsignedInteger('override_max_books')->nullable();
                $table->unsignedInteger('override_max_storage_mb')->nullable();
                $table->unsignedBigInteger('created_by')->nullable()->index();
                $table->timestamp('effective_from')->nullable();
                $table->timestamp('effective_until')->nullable();
                $table->text('notes')->nullable();
                $table->timestamps();
            });
        }

        if (! Schema::hasTable('static_pages')) {
            Schema::create('static_pages', function (Blueprint $table) {
                $table->id();
                $table->string('slug')->unique();
                $table->text('content')->nullable();
                $table->timestamps();
            });
        }
    }

    public function test_opds_root_requires_auth()
    {
        $resp = $this->get('/opds');
        $resp->assertStatus(401);
        $this->assertTrue($resp->headers->has('WWW-Authenticate'));
    }

    public function test_opds_root_with_app_password_returns_feed()
    {
        // create user
        $userId = DB::table('users')->insertGetId([
            'name' => 'OPDS Tester',
            'email' => 'opds@test.local',
            'password' => Hash::make('webpass'),
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        // create book owned by user (use opds_books to avoid schema conflicts)
        $bookId = DB::table('opds_books')->insertGetId([
            'title' => 'OPDS Example Book',
            'file_path' => 'books/opds-example.epub',
            'mime_type' => 'application/epub+zip',
            'user_id' => $userId,
            'library_id' => 1,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        // create app-password (plain shown only once)
        $plain = 'apppass-test-'.bin2hex(random_bytes(6));
        $hash = Hash::make($plain);
        DB::table('user_app_passwords')->insert([
            'user_id' => $userId,
            'name' => 'Test Reader',
            'password_hash' => $hash,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        // fetch root OPDS
        $auth = base64_encode("opds@test.local:{$plain}");
        $resp = $this->withHeaders([
            'Authorization' => "Basic {$auth}",
            'Accept' => 'application/atom+xml;profile=opds-catalog;kind=navigation'
        ])->get('/opds');

        $resp->assertStatus(200);
        $resp->assertHeader('Content-Type');
        $this->assertStringContainsString('application/atom+xml', $resp->headers->get('Content-Type'));
        $this->assertStringContainsString('rel="http://opds-spec.org/search"', $resp->getContent());
        $this->assertStringContainsString('/opds/all', $resp->getContent());

        // acquisition feed (all)
        $resp2 = $this->withHeaders(['Authorization' => "Basic {$auth}"])->get('/opds/all');
        $resp2->assertStatus(200);
        $this->assertStringContainsString('<entry', $resp2->getContent());
    }

    public function test_book_download_returns_x_accel_headers()
    {
        // create user and book
        $userId = DB::table('users')->insertGetId([
            'name' => 'Download Tester',
            'email' => 'download@test.local',
            'password' => Hash::make('webpass'),
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $bookId = DB::table('opds_books')->insertGetId([
            'title' => 'Downloadable Book',
            'file_path' => 'books/downloadable.epub',
            'mime_type' => 'application/epub+zip',
            'user_id' => $userId,
            'library_id' => 2,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        // create app-password
        $plain = 'apppass-dl-'.bin2hex(random_bytes(6));
        $hash = Hash::make($plain);
        DB::table('user_app_passwords')->insert([
            'user_id' => $userId,
            'name' => 'DL Reader',
            'password_hash' => $hash,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $auth = base64_encode("download@test.local:{$plain}");
        $resp = $this->withHeaders(['Authorization' => "Basic {$auth}"])->get('/books/'.$bookId.'/download');
        $resp->assertStatus(200);
        $resp->assertHeader('X-Accel-Redirect');
        $resp->assertHeader('Content-Disposition');
        $this->assertStringContainsString('attachment', $resp->headers->get('Content-Disposition'));
    }
}
