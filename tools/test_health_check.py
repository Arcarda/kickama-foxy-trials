#!/usr/bin/env python3
"""Unit tests for health_check.py — rate limiter, timeout, circuit breaker integration."""

import json
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from health_check import TokenBucket, CircuitBreaker, CB_STATE_CLOSED, CB_STATE_HALF_OPEN, CB_STATE_OPEN


class TestTokenBucket(unittest.TestCase):
    def test_initial_tokens_equal_burst(self):
        tb = TokenBucket(rate=10, burst=5)
        self.assertEqual(tb.burst, 5)
        self.assertEqual(tb.tokens, 5)

    def test_acquire_consumes_tokens(self):
        tb = TokenBucket(rate=100, burst=10)
        self.assertTrue(tb.acquire())
        self.assertEqual(tb.tokens, 9)

    def test_acquire_returns_false_when_empty(self):
        tb = TokenBucket(rate=0, burst=1)
        self.assertTrue(tb.acquire())
        self.assertFalse(tb.acquire())

    def test_throttled_count_increments(self):
        tb = TokenBucket(rate=0, burst=1)
        tb.acquire()
        tb.acquire()
        tb.acquire()
        self.assertEqual(tb.throttled_count, 2)

    def test_rate_adjustment(self):
        tb = TokenBucket(rate=10, burst=10)
        tb.set_rate(5)
        self.assertEqual(tb.rate, 5)

    def test_stats_include_all_fields(self):
        tb = TokenBucket(rate=5, burst=3)
        tb.acquire()
        stats = tb.stats()
        self.assertIn("rate", stats)
        self.assertIn("burst", stats)
        self.assertIn("current_tokens", stats)
        self.assertIn("throttled", stats)
        self.assertIn("total_requests", stats)
        self.assertEqual(stats["rate"], 5)
        self.assertEqual(stats["burst"], 3)
        self.assertEqual(stats["total_requests"], 1)


class TestCircuitBreaker(unittest.TestCase):
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        self.assertEqual(cb.state, CB_STATE_CLOSED)

    def test_opens_after_failure_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        self.assertTrue(cb.allow_request())
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, CB_STATE_OPEN)
        self.assertFalse(cb.allow_request())

    def test_success_after_half_open_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, CB_STATE_OPEN)
        time.sleep(0.02)
        self.assertTrue(cb.allow_request())
        self.assertEqual(cb.state, CB_STATE_HALF_OPEN)
        cb.record_success()
        self.assertEqual(cb.state, CB_STATE_CLOSED)

    def test_half_open_reduces_probe_rate(self):
        from health_check import HealthCheckRunner
        runner = HealthCheckRunner(probe_rate=10.0)
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        runner.circuit_breakers["test"] = cb
        cb.record_failure()
        self.assertEqual(cb.state, CB_STATE_OPEN)
        time.sleep(0.02)
        cb.allow_request()
        self.assertEqual(cb.state, CB_STATE_HALF_OPEN)
        adjusted_rate = runner._rate_adjusted_probe_rate()
        self.assertEqual(adjusted_rate, 5.0)

    def test_maxtokens_parse_timeout_flag(self):
        from health_check import parse_args
        with patch("sys.argv", ["health_check.py", "--timeout", "15", "--probe-rate", "8"]):
            args = parse_args()
            self.assertEqual(args.timeout, 15)
            self.assertEqual(args.probe_rate, 8.0)

    def test_runner_respects_custom_timeout(self):
        from health_check import HealthCheckRunner
        runner = HealthCheckRunner(default_timeout=20)
        self.assertEqual(runner.default_timeout, 20)
        test_config = {"timeout": 5}
        resolved = runner._get_timeout(test_config)
        self.assertEqual(resolved, 20)

    def test_runner_uses_config_timeout_when_default_not_set(self):
        from health_check import HealthCheckRunner
        runner = HealthCheckRunner(default_timeout=0)
        test_config = {"timeout": 7}
        resolved = runner._get_timeout(test_config)
        self.assertEqual(resolved, 7)


if __name__ == "__main__":
    unittest.main()
