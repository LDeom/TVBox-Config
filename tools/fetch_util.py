#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared bounded HTTP fetcher with public-host validation and host circuit breaking."""
from __future__ import annotations

import ipaddress
import socket
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests

DEFAULT_HEADERS = {
    "User-Agent": "okhttp/3.12.13",
    "Accept": "application/json, application/xml, text/xml, */*",
}
REDIRECT_CODES = {301, 302, 303, 307, 308}
CIRCUIT_FAILURE_THRESHOLD = 4
CIRCUIT_COOLDOWN_SECONDS = 60
DEFAULT_TOTAL_TIMEOUT = 30.0


class FetchError(RuntimeError):
    """A safe HTTP fetch could not be completed."""


@dataclass
class FetchResult:
    url: str
    status_code: int
    body: bytes
    headers: dict
    elapsed: float


class HostCircuitBreaker:
    """Thread-safe per-host circuit breaker with one half-open probe."""

    def __init__(self, failure_threshold: int = CIRCUIT_FAILURE_THRESHOLD,
                 cooldown_seconds: float = CIRCUIT_COOLDOWN_SECONDS):
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(0.1, float(cooldown_seconds))
        self._lock = threading.Lock()
        self._states: dict[str, dict] = {}

    @staticmethod
    def _now(now=None) -> float:
        return time.monotonic() if now is None else float(now)

    def before_request(self, host: str, *, now=None) -> bool:
        """Raise while open; return True when this call owns the half-open probe."""
        current = self._now(now)
        with self._lock:
            state = self._states.get(host)
            if not state or state.get("opened_at") is None:
                return False
            if current - state["opened_at"] < self.cooldown_seconds:
                remaining = self.cooldown_seconds - (current - state["opened_at"])
                raise FetchError(
                    f"主机熔断中：{host}，冷却剩余约 {remaining:.1f}s"
                )
            if state.get("probe_in_flight"):
                raise FetchError(f"主机熔断半开探测已被占用：{host}")
            state["probe_in_flight"] = True
            return True

    def record_failure(self, host: str, *, now=None) -> None:
        current = self._now(now)
        with self._lock:
            state = self._states.setdefault(host, {
                "failures": 0, "opened_at": None, "probe_in_flight": False,
            })
            state["failures"] += 1
            state["probe_in_flight"] = False
            if state["failures"] >= self.failure_threshold:
                state["opened_at"] = current

    def record_success(self, host: str) -> None:
        with self._lock:
            self._states.pop(host, None)

    def abort_probe(self, host: str) -> None:
        """Release a half-open probe after a local validation/size error."""
        with self._lock:
            state = self._states.get(host)
            if state:
                state["probe_in_flight"] = False

    def record_response(self, host: str, status_code: int, *, now=None) -> None:
        if status_code in {408, 429} or status_code >= 500:
            self.record_failure(host, now=now)
        else:
            # A reachable host returning 4xx is not considered unavailable.
            self.record_success(host)

    def snapshot(self) -> dict:
        with self._lock:
            return {host: dict(state) for host, state in self._states.items()}


GLOBAL_CIRCUIT_BREAKER = HostCircuitBreaker()


def validate_public_url(url: str) -> None:
    """Reject non-HTTP URLs and hosts resolving to non-global IP addresses."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise FetchError("只允许完整的 HTTP(S) URL")
        if parsed.username or parsed.password:
            raise FetchError("不允许 URL 内嵌用户名或密码")
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise FetchError("拒绝本机或局域网域名")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            infos = socket.getaddrinfo(
                host, parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = list({ipaddress.ip_address(info[4][0]) for info in infos})
        if not addresses or any(not address.is_global for address in addresses):
            raise FetchError("域名解析包含非公网 IP，已阻止请求")
    except FetchError:
        raise
    except (OSError, ValueError) as exc:
        raise FetchError(f"域名解析或 URL 校验失败：{exc}") from exc


def _host_key(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return f"{host}:{parsed.port}" if parsed.port else host


class SafeFetcher:
    """Thread-safe bounded GET client with retries, deadline and circuit breaker."""

    def __init__(self, timeout=(5, 10), max_bytes=2 * 1024 * 1024,
                 retries=2, max_redirects=5, headers=None,
                 total_timeout: float | None = DEFAULT_TOTAL_TIMEOUT,
                 circuit_breaker: HostCircuitBreaker | None = None):
        self.timeout = timeout
        self.max_bytes = max(1, int(max_bytes))
        self.retries = max(0, min(int(retries), 3))
        self.max_redirects = max(0, min(int(max_redirects), 8))
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.total_timeout = (
            None if total_timeout is None else max(0.1, float(total_timeout))
        )
        self.circuit_breaker = circuit_breaker or GLOBAL_CIRCUIT_BREAKER
        self._local = threading.local()

    def _session(self):
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
            self._local.session.headers.update(self.headers)
            self._local.session.trust_env = True
        return self._local.session

    def _bounded_timeout(self, remaining: float | None):
        if remaining is None:
            return self.timeout
        if isinstance(self.timeout, tuple):
            connect, read = self.timeout
            return max(0.1, min(float(connect), remaining)), max(0.1, min(float(read), remaining))
        return max(0.1, min(float(self.timeout), remaining))

    def get(self, url: str) -> FetchResult:
        started = time.monotonic()
        deadline = started + self.total_timeout if self.total_timeout is not None else None
        current = url
        last_error = None

        for attempt in range(self.retries + 1):
            active_host = None
            owns_probe = False
            try:
                for redirect_count in range(self.max_redirects + 1):
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        raise FetchError(
                            f"单 URL 总请求预算耗尽（{self.total_timeout:.1f}s）"
                        )
                    validate_public_url(current)
                    active_host = _host_key(current)
                    owns_probe = self.circuit_breaker.before_request(active_host)
                    with self._session().get(
                        current,
                        timeout=self._bounded_timeout(remaining),
                        allow_redirects=False,
                        stream=True,
                    ) as response:
                        if response.status_code in REDIRECT_CODES:
                            self.circuit_breaker.record_success(active_host)
                            owns_probe = False
                            location = response.headers.get("Location")
                            if not location:
                                raise FetchError("重定向响应缺少 Location")
                            if redirect_count >= self.max_redirects:
                                raise FetchError("重定向次数超过限制")
                            current = urljoin(current, location)
                            continue

                        self.circuit_breaker.record_response(
                            active_host, response.status_code
                        )
                        owns_probe = False
                        body = bytearray()
                        for chunk in response.iter_content(32 * 1024):
                            if not chunk:
                                continue
                            remaining = None if deadline is None else deadline - time.monotonic()
                            if remaining is not None and remaining <= 0:
                                raise FetchError(
                                    f"单 URL 总请求预算耗尽（{self.total_timeout:.1f}s）"
                                )
                            if len(body) + len(chunk) > self.max_bytes:
                                raise FetchError(
                                    f"响应超过大小限制（{self.max_bytes} 字节）"
                                )
                            body.extend(chunk)
                        return FetchResult(
                            url=response.url,
                            status_code=response.status_code,
                            body=bytes(body),
                            headers=dict(response.headers),
                            elapsed=round(time.monotonic() - started, 3),
                        )
                raise FetchError("重定向处理失败")
            except FetchError:
                if owns_probe and active_host:
                    self.circuit_breaker.abort_probe(active_host)
                raise
            except requests.RequestException as exc:
                if active_host:
                    self.circuit_breaker.record_failure(active_host)
                owns_probe = False
                last_error = exc
                if attempt >= self.retries:
                    break
                delay = min(0.4 * (2 ** attempt), 1.6)
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    delay = min(delay, remaining)
                time.sleep(delay)

        if deadline is not None and time.monotonic() >= deadline:
            raise FetchError(
                f"单 URL 总请求预算耗尽（{self.total_timeout:.1f}s）"
            ) from last_error
        raise FetchError(
            f"HTTP 请求失败：{type(last_error).__name__}: {last_error}"
        ) from last_error


def fetch_bytes(url: str, *, timeout=(5, 10), max_bytes=2 * 1024 * 1024,
                retries=2, headers=None, total_timeout=DEFAULT_TOTAL_TIMEOUT) -> FetchResult:
    """Convenience wrapper used by repository scripts."""
    return SafeFetcher(
        timeout=timeout, max_bytes=max_bytes, retries=retries, headers=headers,
        total_timeout=total_timeout,
    ).get(url)
