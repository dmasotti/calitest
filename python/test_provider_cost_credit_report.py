import json
import tempfile
import unittest
from pathlib import Path

from scripts.provider_cost_credit_report import (
    _apply_r2_snapshot_to_providers,
    _load_accounts_config,
    _normalize_r2_usage_row,
    _run_credit_adapter,
)


class ProviderCostCreditReportTest(unittest.TestCase):
    def test_load_accounts_config_defaults_when_missing(self):
        conf = _load_accounts_config(None)
        self.assertEqual(conf, {})

    def test_load_accounts_config_parses_providers_accounts(self):
        payload = {
            "providers": {
                "openai": [
                    {"name": "work", "env": {"OPENAI_API_KEY": "k1"}, "budget_usd": 20},
                    {"name": "personal", "env": {"OPENAI_API_KEY": "k2"}, "budget_usd": 10},
                ],
                "deepseek": [
                    {"name": "main", "env": {"DEEPSEEK_API_KEY": "d1"}},
                ],
            }
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "accounts.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            conf = _load_accounts_config(p)

        self.assertIn("openai", conf)
        self.assertEqual(len(conf["openai"]), 2)
        self.assertEqual(conf["openai"][0]["name"], "work")
        self.assertEqual(conf["openai"][1]["name"], "personal")
        self.assertEqual(conf["deepseek"][0]["name"], "main")

    def test_run_credit_adapter_exposes_subscription_type(self):
        env_map = {
            "CREDIT_CHECK_OPENAI_CMD": "printf '{\"status\":\"ok\",\"credit_usd\":12.5,\"subscription_type\":\"pro\"}'"
        }
        result = _run_credit_adapter("openai", env_map, timeout=2)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.credit_usd, 12.5)
        self.assertEqual(result.payload.get("subscription_type"), "pro")

    def test_normalize_r2_usage_row_parses_metadata_json(self):
        row = {
            "logged_at": "2026-07-11 00:00:00",
            "cost_usd": "0.397807",
            "metric_type": "monthly_usage_snapshot",
            "metadata": json.dumps(
                {
                    "storage_gb": 25.5342,
                    "class_a_operations": 2030,
                    "class_b_operations": 15720,
                }
            ),
        }
        snapshot = _normalize_r2_usage_row(row)
        self.assertEqual(snapshot["total_cost_month_usd"], 0.397807)
        self.assertEqual(snapshot["storage_gb"], 25.5342)
        self.assertEqual(snapshot["class_a_operations"], 2030)
        self.assertEqual(snapshot["operations_total"], 17750)

    def test_apply_r2_snapshot_updates_cloudflare_provider(self):
        snapshot = {
            "source": "service_usage_logs",
            "logged_at": "2026-07-11 00:00:00",
            "metric_type": "monthly_usage_snapshot",
            "total_cost_month_usd": 0.4,
            "storage_gb": 25.5,
            "class_a_operations": 2000,
            "class_b_operations": 15000,
            "operations_total": 17000,
        }
        internal_costs = {"cloudflare": 0.0}
        providers = {
            "cloudflare": {
                "configured": True,
                "internal_cost_usd": 0.0,
                "budget_usd": 10.0,
                "residual_budget_usd": 10.0,
            }
        }
        _apply_r2_snapshot_to_providers(internal_costs, providers, snapshot)
        self.assertEqual(internal_costs["cloudflare"], 0.4)
        self.assertEqual(providers["cloudflare"]["internal_cost_usd"], 0.4)
        self.assertEqual(providers["cloudflare"]["residual_budget_usd"], 9.6)
        self.assertEqual(providers["cloudflare"]["r2_usage"]["storage_gb"], 25.5)


if __name__ == "__main__":
    unittest.main()
