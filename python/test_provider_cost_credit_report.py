import json
import tempfile
import unittest
from pathlib import Path

from scripts.provider_cost_credit_report import (
    _load_accounts_config,
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


if __name__ == "__main__":
    unittest.main()
