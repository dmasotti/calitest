<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Tests\TestCase;

class SubscriptionConfigTest extends TestCase
{
    use RefreshDatabase;

    /**
     * Test subscription config is loaded correctly
     */
    public function test_subscription_config_is_loaded(): void
    {
        $tiers = config('subscription.tiers');
        
        $this->assertIsArray($tiers);
        $this->assertArrayHasKey('free', $tiers);
        $this->assertArrayHasKey('basic', $tiers);
        $this->assertArrayHasKey('pro', $tiers);
        $this->assertArrayHasKey('enterprise', $tiers);
    }

    /**
     * Test free tier has correct limits
     */
    public function test_free_tier_has_correct_limits(): void
    {
        $freeTier = config('subscription.tiers.free');
        
        $this->assertEquals(1, $freeTier['max_libraries']);
        $this->assertEquals(50, $freeTier['max_books']);
        $this->assertEquals(500, $freeTier['max_storage_mb']);
        $this->assertContains('sync', $freeTier['features']);
        $this->assertContains('covers', $freeTier['features']);
    }

    /**
     * Test basic tier has correct limits
     */
    public function test_basic_tier_has_correct_limits(): void
    {
        $basicTier = config('subscription.tiers.basic');
        
        $this->assertEquals(3, $basicTier['max_libraries']);
        $this->assertEquals(600, $basicTier['max_books']);
        $this->assertEquals(3072, $basicTier['max_storage_mb']);
        $this->assertContains('export', $basicTier['features']);
    }

    /**
     * Test pro tier has correct limits
     */
    public function test_pro_tier_has_correct_limits(): void
    {
        $proTier = config('subscription.tiers.pro');
        
        $this->assertEquals(10, $proTier['max_libraries']);
        $this->assertEquals(5000, $proTier['max_books']);
        $this->assertEquals(25600, $proTier['max_storage_mb']);
        $this->assertContains('api', $proTier['features']);
    }

    /**
     * Test enterprise tier has correct limits
     */
    public function test_enterprise_tier_has_correct_limits(): void
    {
        $enterpriseTier = config('subscription.tiers.enterprise');
        
        $this->assertEquals(50, $enterpriseTier['max_libraries']);
        $this->assertEquals(50000, $enterpriseTier['max_books']);
        $this->assertEquals(256000, $enterpriseTier['max_storage_mb']);
        $this->assertContains('white_label', $enterpriseTier['features']);
    }

    /**
     * Test pricing is configured correctly
     */
    public function test_pricing_is_configured_correctly(): void
    {
        $basicTier = config('subscription.tiers.basic');
        
        $this->assertEquals(499, $basicTier['pricing']['monthly']); // €4.99
        $this->assertEquals(4990, $basicTier['pricing']['yearly']); // €49.90
        
        $proTier = config('subscription.tiers.pro');
        $this->assertEquals(999, $proTier['pricing']['monthly']); // €9.99
        $this->assertEquals(9990, $proTier['pricing']['yearly']); // €99.90
    }

    /**
     * Test trial days config exists
     */
    public function test_trial_days_config_exists(): void
    {
        $trialDays = config('subscription.trial_days');
        
        $this->assertIsInt($trialDays);
        $this->assertGreaterThan(0, $trialDays);
    }

    /**
     * Test default tier config exists
     */
    public function test_default_tier_config_exists(): void
    {
        $defaultTier = config('subscription.default_tier');
        
        $this->assertEquals('free', $defaultTier);
    }
}
