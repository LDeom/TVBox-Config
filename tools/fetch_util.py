#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared bounded HTTP fetcher for TVBox source maintenance tools."""
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


class FetchError(RuntimeError):
    """A safe HTTP fetch could not be completed."""


@dataclass
class FetchResult:
    url: str
    status_code: int
    body: bytes
    headers: dict
    elapsed: float


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


class SafeFetcher:
    """Thread-safe bounded GET client with retries and redirect revalidation."""

    def __init__(self, timeout=(5, 10), max_bytes=2 * 1024 * 1024,
                 retries=2, max_redirects=5, headers=None):
        self.timeout = timeout
        self.max_bytes = max(1, int(max_bytes))
        self.retries = max(0, min(int(retries), 3))
        self.max_redirects = max(0, min(int(max_redirects), 8))
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self._local = threading.local()

    def _session(self):
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
            self._local.session.headers.update(self.headers)
            self._local.session.trust_env = True
        return self._local.session

    def get(self, url: str) -> FetchResult:
        started = time.monotonic()
        current = url
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                for redirect_count in range(self.max_redirects + 1):
                    validate_public_url(current)
                    with self._session().get(
                        current, timeout=self.timeout, allow_redirects=False,
                        stream=True,
                    ) as response:
                        if response.status_code in REDIRECT_CODES:
                            location = response.headers.get("Location")
                            if not location:
                                raise FetchError("重定向响应缺少 Location")
                            if redirect_count >= self.max_redirects:
                                raise FetchError("重定向次数超过限制")
                            current = urljoin(current, location)
                            continue
                        body = bytearray()
                        for chunk in response.iter_content(32 * 1024):
                            if not chunk:
                                continue
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
                raise
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(min(0.4 * (2 ** attempt), 1.6))
        raise FetchError(
            f"HTTP 请求失败：{type(last_error).__name__}: {last_error}"
        ) from last_error


def fetch_bytes(url: str, *, timeout=(5, 10), max_bytes=2 * 1024 * 1024,
                retries=2, headers=None) -> FetchResult:
    """Convenience wrapper used by repository scripts."""
    return SafeFetcher(
        timeout=timeout, max_bytes=max_bytes, retries=retries, headers=headers
    ).get(url)
