"""Read-only quota classification. Never invokes a model or creates a schedule."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

DEFAULT_WEEKLY_STOP_PERCENT = 70
WEEK_MINUTES = 7 * 24 * 60


def weekly_percent(value):
    try:
        percent = float(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("weekly stop percent must be between 1 and 100")
    if not number(percent) or not 1 <= percent <= 100:
        raise argparse.ArgumentTypeError("weekly stop percent must be between 1 and 100")
    return percent


def unwrap(value):
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    if value.get("isError"):
        raise ValueError("Usage tool returned an error")
    if "rateLimits" in value or "rateLimitsByLimitId" in value:
        return value
    if isinstance(value.get("structuredContent"), dict):
        return unwrap(value["structuredContent"])
    if isinstance(value.get("result"), dict):
        return unwrap(value["result"])
    for item in value.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                return unwrap(json.loads(item["text"]))
            except (ValueError, KeyError, TypeError):
                continue
    raise ValueError("Usage data is unavailable")


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def classify(payload, *, bucket=None, now=None, weekly_stop_percent=DEFAULT_WEEKLY_STOP_PERCENT):
    now = time.time() if now is None else now
    result = {"status": "unknown", "bucket": bucket, "retryAt": None,
              "weeklyStopPercent": weekly_stop_percent, "weeklyUsedPercent": None}

    def answer(status, reason, retry_at=None):
        return dict(result, status=status, reason=reason, retryAt=retry_at)

    if not number(weekly_stop_percent) or not 1 <= weekly_stop_percent <= 100:
        return answer("unknown", "invalid_weekly_threshold")
    try:
        data = unwrap(payload)
    except (ValueError, TypeError):
        return answer("unknown", "usage_unavailable")
    buckets = data.get("rateLimitsByLimitId")
    if buckets is not None:
        if not isinstance(buckets, dict) or not buckets:
            return answer("unknown", "buckets_unavailable")
        if bucket is None:
            if len(buckets) != 1:
                return answer("unknown", "select_applicable_bucket")
            bucket = next(iter(buckets))
        limits = buckets.get(bucket)
    else:
        limits = data.get("rateLimits")
        if isinstance(limits, dict):
            actual = limits.get("limitId")
            if bucket is not None and actual != bucket:
                return answer("unknown", "bucket_not_found")
            bucket = actual
    result["bucket"] = bucket
    if not isinstance(limits, dict):
        return answer("unknown", "bucket_not_found")
    if limits.get("spendControlReached") is True:
        return answer("blocked", "spend_control")
    # A new, unrecognised individual-limit shape must not be treated as ready.
    if limits.get("individualLimit") is not None:
        return answer("unknown", "individual_limit_requires_review")
    windows = []
    missing = False
    for key in ("primary", "secondary"):
        window = limits.get(key)
        if window is None and key == "secondary":
            continue
        if not isinstance(window, dict):
            missing = True
            continue
        used = window.get("usedPercent")
        if not number(used) or used < 0:
            missing = True
            continue
        windows.append(window)
    # Identify the week by duration, not the primary/secondary position.
    weekly = [w for w in windows if w.get("windowDurationMins") == WEEK_MINUTES]
    if weekly:
        result["weeklyUsedPercent"] = max(w["usedPercent"] for w in weekly)
        if result["weeklyUsedPercent"] >= weekly_stop_percent:
            # This is a user stop boundary: pause the heartbeat, do not auto-retry.
            return answer("blocked", "weekly_threshold_reached")
    if not weekly:
        return answer("unknown", "weekly_window_unavailable")
    exhausted = [w for w in windows if w["usedPercent"] >= 100]
    if exhausted:
        resets = [w.get("resetsAt") for w in exhausted]
        retry = None
        if not missing and all(number(r) and r > 0 for r in resets):
            retry = int(max(max(resets) + 60, now + 300))
        return answer("waiting", "quota_exhausted", retry)
    if missing or not windows:
        return answer("unknown", "window_unavailable")
    if limits.get("rateLimitReachedType") is not None:
        return answer("unknown", "server_reports_limit")
    return answer("ready", "reported_windows_available")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, help="Usage JSON; omit to read stdin")
    parser.add_argument("--bucket", help="Verified applicable metered limit ID")
    parser.add_argument("--now", type=float, help="Unix seconds, for reproducible diagnostics")
    parser.add_argument("--weekly-stop-percent", type=weekly_percent,
                        default=DEFAULT_WEEKLY_STOP_PERCENT,
                        help="Pause at this WEEKLY used percent (1-100; default: 70)")
    args = parser.parse_args()
    try:
        raw = args.file.read_text(encoding="utf-8-sig") if args.file else sys.stdin.read()
        status = classify(json.loads(raw), bucket=args.bucket, now=args.now,
                          weekly_stop_percent=args.weekly_stop_percent)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "unknown", "reason": type(exc).__name__}))
        return 2
    print(json.dumps(status, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
