import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "quota-resume/skills/quota-resume/scripts/quota_status.py"
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
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "weekly_threshold_reached")
        self.assertIsNone(result["retryAt"])

    def test_weekly_stop_takes_priority_over_five_hour_wait(self):
        result = quota.classify(payload(100, 70), now=1000)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "weekly_threshold_reached")
        self.assertIsNone(result["retryAt"])

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

    def test_legacy_missing_weekly_window_is_unknown(self):
        result = quota.classify({"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 0}, "secondary": None}})
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "weekly_window_unavailable")

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

    def test_default_threshold_boundaries(self):
        for used, expected in [(0, "ready"), (69.9, "ready"), (70, "blocked"), (70.1, "blocked")]:
            with self.subTest(used=used):
                result = quota.classify(payload(0, used))
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["weeklyStopPercent"], 70)
                self.assertEqual(result["weeklyUsedPercent"], used)

    def test_custom_threshold(self):
        self.assertEqual(quota.classify(payload(0, 79), weekly_stop_percent=80)["status"], "ready")
        self.assertEqual(quota.classify(payload(0, 80), weekly_stop_percent=80)["status"], "blocked")
        self.assertEqual(quota.classify(payload(0, 99), weekly_stop_percent=100)["status"], "ready")
        self.assertEqual(quota.classify(payload(0, 100), weekly_stop_percent=100)["status"], "blocked")

    def test_five_hour_percent_does_not_trigger_weekly_stop(self):
        self.assertEqual(quota.classify(payload(95, 10))["status"], "ready")

    def test_identifies_weekly_by_duration_after_slots_swap(self):
        data = payload(20, 70)
        limits = data["rateLimitsByLimitId"]["codex"]
        limits["primary"], limits["secondary"] = limits["secondary"], limits["primary"]
        result = quota.classify(data)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["weeklyUsedPercent"], 70)

    def test_unknown_duration_does_not_assume_secondary_is_weekly(self):
        data = payload(0, 10)
        del data["rateLimitsByLimitId"]["codex"]["secondary"]["windowDurationMins"]
        self.assertEqual(quota.classify(data)["reason"], "weekly_window_unavailable")

    def test_past_reset_does_not_bypass_weekly_stop(self):
        result = quota.classify(payload(0, 70), now=10000)
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["retryAt"])

    def test_invalid_thresholds(self):
        for value in [0, 101, -1, True, None, "70", float("nan"), float("inf")]:
            with self.subTest(value=value):
                self.assertEqual(quota.classify(payload(), weekly_stop_percent=value)["reason"], "invalid_weekly_threshold")

    def test_cli_threshold_parameter(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--weekly-stop-percent", "65"],
                                input=json.dumps(payload(0, 65)), text=True, capture_output=True, check=True)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["reason"], "weekly_threshold_reached")
        self.assertEqual(parsed["weeklyStopPercent"], 65)

    def test_cli_rejects_out_of_range_threshold(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--weekly-stop-percent", "101"],
                                input=json.dumps(payload()), text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("between 1 and 100", result.stderr)

    def test_legacy_payload_with_weekly_window(self):
        result = quota.classify({"rateLimits": payload(0, 70)["rateLimitsByLimitId"]["codex"]})
        self.assertEqual(result["reason"], "weekly_threshold_reached")


if __name__ == "__main__":
    unittest.main()
