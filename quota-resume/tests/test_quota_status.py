import importlib.util
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/quota-resume/scripts/quota_status.py"
spec = importlib.util.spec_from_file_location("quota_status", SCRIPT)
quota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quota)


def payload(primary=20, secondary=30):
    return {"rateLimitsByLimitId": {"codex": {
        "primary": {"usedPercent": primary, "windowDurationMins": 300, "resetsAt": 2000},
        "secondary": {"usedPercent": secondary, "windowDurationMins": 10080, "resetsAt": 9000},
        "credits": {"hasCredits": False, "balance": "0"},
    }}}


class QuotaTests(unittest.TestCase):
    def test_available_without_purchased_credits(self):
        self.assertEqual(quota.classify(payload())["status"], "ready")

    def test_five_hour_waits_for_server_reset(self):
        result = quota.classify(payload(100), now=1000)
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(result["retryAt"], 2060)

    def test_weekly_limit_blocks_recovered_primary(self):
        result = quota.classify(payload(0, 100), now=1000)
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(result["retryAt"], 9060)

    def test_both_exhausted_wait_for_later_window(self):
        self.assertEqual(quota.classify(payload(100, 100), now=1000)["retryAt"], 9060)

    def test_elapsed_timestamp_does_not_imply_recovery(self):
        result = quota.classify(payload(100), now=3000)
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(result["retryAt"], 3300)

    def test_missing_usage_is_not_zero(self):
        self.assertEqual(quota.classify(payload(None))["status"], "unknown")

    def test_invalid_numbers_are_unknown(self):
        for value in [True, -1, float("nan"), "0"]:
            with self.subTest(value=value):
                self.assertEqual(quota.classify(payload(value))["status"], "unknown")

    def test_reset_missing_keeps_wait_without_invented_time(self):
        data = payload(100)
        data["rateLimitsByLimitId"]["codex"]["primary"]["resetsAt"] = None
        result = quota.classify(data)
        self.assertEqual(result["status"], "waiting")
        self.assertIsNone(result["retryAt"])

    def test_does_not_guess_multi_bucket(self):
        data = payload()
        data["rateLimitsByLimitId"]["other"] = payload(100)["rateLimitsByLimitId"]["codex"]
        self.assertEqual(quota.classify(data)["status"], "unknown")
        self.assertEqual(quota.classify(data, bucket="codex")["status"], "ready")
        self.assertEqual(quota.classify(data, bucket="other")["status"], "waiting")

    def test_unknown_bucket(self):
        self.assertEqual(quota.classify(payload(), bucket="missing")["status"], "unknown")

    def test_server_limit_blocks_ready_percentages(self):
        data = payload()
        data["rateLimitsByLimitId"]["codex"]["rateLimitReachedType"] = "newLimit"
        self.assertEqual(quota.classify(data)["status"], "unknown")

    def test_spend_control_blocks(self):
        data = payload()
        data["rateLimitsByLimitId"]["codex"]["spendControlReached"] = True
        self.assertEqual(quota.classify(data)["status"], "blocked")

    def test_legacy_single_window(self):
        self.assertEqual(quota.classify({"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 0}, "secondary": None}})["status"], "ready")

    def test_mcp_tool_envelope(self):
        value = {"content": [{"type": "text", "text": json.dumps(payload())}], "isError": False}
        self.assertEqual(quota.classify(value)["status"], "ready")
        value["isError"] = True
        self.assertEqual(quota.classify(value)["status"], "unknown")

    def test_no_fallback_when_modern_buckets_empty(self):
        data = {"rateLimitsByLimitId": {}, "rateLimits": {"primary": {"usedPercent": 0}}}
        self.assertEqual(quota.classify(data)["status"], "unknown")

    def test_unknown_individual_limit(self):
        data = payload()
        data["rateLimitsByLimitId"]["codex"]["individualLimit"] = {"newField": True}
        self.assertEqual(quota.classify(data)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
