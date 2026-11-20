#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fetch_util import FetchError, HostCircuitBreaker, SafeFetcher


class FakeResponse:
    def __init__(self, status_code=200, body=b"", url="https://api.example.test/data"):
        self.status_code = status_code
        self.body = body
        self.url = url
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        if self.body:
            yield self.body


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


class HostCircuitBreakerTests(unittest.TestCase):
    def test_opens_after_threshold_and_allows_one_half_open_probe(self):
        breaker = HostCircuitBreaker(failure_threshold=2, cooldown_seconds=10)
        breaker.record_failure("api.example.test", now=1)
        breaker.record_failure("api.example.test", now=2)
        with self.assertRaises(FetchError):
            breaker.before_request("api.example.test", now=5)
        self.assertTrue(breaker.before_request("api.example.test", now=13))
        with self.assertRaises(FetchError):
            breaker.before_request("api.example.test", now=13.1)
        breaker.record_success("api.example.test")
        self.assertFalse(breaker.before_request("api.example.test", now=14))

    def test_hosts_are_isolated(self):
        breaker = HostCircuitBreaker(failure_threshold=1, cooldown_seconds=10)
        breaker.record_failure("bad.example.test", now=1)
        with self.assertRaises(FetchError):
            breaker.before_request("bad.example.test", now=2)
        self.assertFalse(breaker.before_request("good.example.test", now=2))

    def test_abort_probe_releases_half_open_lock_without_resetting_circuit(self):
        breaker = HostCircuitBreaker(failure_threshold=1, cooldown_seconds=5)
        breaker.record_failure("api.example.test", now=1)
        self.assertTrue(breaker.before_request("api.example.test", now=7))
        breaker.abort_probe("api.example.test")
        self.assertTrue(breaker.before_request("api.example.test", now=7.1))

    def test_http_429_and_5xx_count_as_failures_but_404_is_reachable(self):
        breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=10)
        breaker.record_response("api.example.test", 429, now=1)
        breaker.record_response("api.example.test", 503, now=2)
        self.assertEqual(breaker.snapshot()["api.example.test"]["failures"], 2)
        breaker.record_response("api.example.test", 404, now=3)
        self.assertEqual(breaker.snapshot(), {})

    def test_safe_fetcher_opens_circuit_after_server_errors(self):
        breaker = HostCircuitBreaker(failure_threshold=2, cooldown_seconds=30)
        fetcher = SafeFetcher(retries=0, total_timeout=2, circuit_breaker=breaker)
        fetcher._session = lambda: FakeSession(FakeResponse(status_code=503))
        with patch("fetch_util.validate_public_url"):
            self.assertEqual(fetcher.get("https://api.example.test/data").status_code, 503)
            self.assertEqual(fetcher.get("https://api.example.test/data").status_code, 503)
            with self.assertRaises(FetchError):
                fetcher.get("https://api.example.test/data")

    def test_total_request_deadline_is_enforced_while_reading_body(self):
        class SlowResponse(FakeResponse):
            def iter_content(self, chunk_size):
                time.sleep(0.03)
                yield b"x"

        breaker = HostCircuitBreaker()
        fetcher = SafeFetcher(retries=0, total_timeout=0.01, circuit_breaker=breaker)
        fetcher._session = lambda: FakeSession(SlowResponse())
        with patch("fetch_util.validate_public_url"):
            with self.assertRaisesRegex(FetchError, "总请求预算耗尽"):
                fetcher.get("https://api.example.test/data")


if __name__ == "__main__":
    unittest.main()
