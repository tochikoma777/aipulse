"""统一 HTTP 客户端。

所有网络请求**必须**经过 :meth:`HttpClient.request`，这样：
1. 限速 / 重试 / 缓存 / UA / 代理只在一处实现，行为一致；
2. 测试里用 `respx` 拦截即可，无需打真实网络（CI 零密钥全绿的前提）。

特性：
- 每源独立令牌桶限速（`rate_limit` 形如 `3/s`、`10/1s`、`1/6h`）
- 连接/读取超时可配；tenacity 重试：仅 429 / 5xx / 超时，最多 3 次，指数退避 + 抖动
- SQLite 响应缓存（`data/cache/http.sqlite`，TTL 可配，`--no-cache` / `cache=False` 关闭）
- 统一 User-Agent 与 HTTP(S)_PROXY 支持
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from aipulse.core.logging import get_logger

log = get_logger(__name__)

RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
RETRY_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
    # 中间设备偶发返回损坏的 gzip，重新请求通常能拿到正确响应
    httpx.DecodingError,
)

_DURATION_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


class ConfigError(ValueError):
    """rate_limit 字符串无法解析。"""


@dataclass(frozen=True)
class RateLimit:
    """限速规格：`count/period`，如 `3/s`、`10/1s`、`1/6h`。"""

    count: int
    seconds: float

    @classmethod
    def parse(cls, spec: str) -> RateLimit:
        text = (spec or "").strip().lower()
        try:
            left, right = text.split("/")
        except ValueError as exc:
            raise ConfigError(
                f"限速格式应为 'N/period'，如 3/s、10/1s、1/6h，收到：{spec!r}"
            ) from exc
        count = int(left.strip())
        period = right.strip()
        unit = period[-1]
        if unit in _DURATION_UNITS and len(period) >= 1:
            number = period[:-1] or "1"
            seconds = float(number) * _DURATION_UNITS[unit]
        else:  # 纯秒数，如 "3/1"
            seconds = float(period)
        if count <= 0 or seconds <= 0:
            raise ConfigError(f"限速参数必须为正：{spec!r}")
        return cls(count=count, seconds=seconds)

    @property
    def per_second(self) -> float:
        return self.count / self.seconds


class TokenBucket:
    """令牌桶：容量 = count，补充速率 = count/period。

    用令牌桶而非固定 sleep，是因为"攒了一段时间的配额"可以被突发请求一次性用掉
    （例如一次探测连打 3 个 arXiv 请求），同时长期平均速率不会超限。
    """

    def __init__(self, limit: RateLimit, clock: Any = time.monotonic) -> None:
        self.limit = limit
        self.capacity = float(limit.count)
        self._tokens = float(limit.count)
        self._clock = clock
        self._updated = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.limit.per_second)
            self._updated = now

    def available(self) -> float:
        self._refill()
        return self._tokens

    def wait_time(self, tokens: float = 1.0) -> float:
        """取到 `tokens` 个令牌还需等待的秒数（0 表示立即可用）。"""
        self._refill()
        if self._tokens >= tokens:
            return 0.0
        return (tokens - self._tokens) / self.limit.per_second

    async def acquire(self, tokens: float = 1.0) -> None:
        """异步等待直到拿到令牌。"""
        while True:
            wait = self.wait_time(tokens)
            if wait <= 0:
                self._tokens -= tokens
                return
            await asyncio.sleep(min(wait, self.limit.seconds))


class HttpCache:
    """SQLite 响应缓存（同步 sqlite3，调用极快，不值得引入异步依赖）。"""

    def __init__(self, path: Path, ttl_s: int = 1800) -> None:
        self.path = Path(path)
        self.ttl_s = ttl_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS http_cache (
                    key         TEXT PRIMARY KEY,
                    url         TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    headers     TEXT NOT NULL,
                    content     BLOB NOT NULL,
                    created_at  REAL NOT NULL
                )
                """
            )

    @staticmethod
    def make_key(method: str, url: str, params: Mapping[str, Any] | None) -> str:
        import hashlib

        suffix = json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str)
        raw = f"{method.upper()}|{url}|{suffix}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str, ttl_s: int | None = None) -> httpx.Response | None:
        ttl = self.ttl_s if ttl_s is None else ttl_s
        with self._connect() as conn:
            row = conn.execute(
                "SELECT url, status_code, headers, content, created_at"
                " FROM http_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        url, status_code, headers_json, content, created_at = row
        # ttl <= 0 表示"立即过期"（等价于关闭缓存）
        if ttl <= 0 or (time.time() - created_at) > ttl:
            return None
        headers = json.loads(headers_json)
        response = httpx.Response(
            status_code=status_code,
            headers=httpx.Headers(headers),
            content=content,
            request=httpx.Request("GET", url),
        )
        # httpx 0.28 没有 .ext，用 extensions 字典标记缓存命中（供调用方判断是否走了网络）
        response.extensions["from_cache"] = True
        response.extensions["cached_at"] = created_at
        return response

    def put(
        self,
        key: str,
        url: str,
        response: httpx.Response,
        *,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        content = response.content
        if len(content) > max_bytes:
            return
        headers = dict(response.headers)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO http_cache"
                " (key, url, status_code, headers, content, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    url,
                    response.status_code,
                    json.dumps(headers, ensure_ascii=False),
                    content,
                    time.time(),
                ),
            )

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM http_cache")


DEFAULT_USER_AGENT = "aipulse/0.1 (+https://github.com/tochikoma777/aipulse)"


def resolve_proxy(env: Mapping[str, str] | None = None) -> str | None:
    """按优先级解析代理：HTTPS_PROXY > https_proxy > HTTP_PROXY > http_proxy。"""
    source = os.environ if env is None else env
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = source.get(key)
        if value:
            return value
    return None


def _is_retryable(response: httpx.Response) -> bool:
    return response.status_code in RETRY_STATUS


class _RetryableStatus(Exception):
    """可重试的 HTTP 状态码（429 / 5xx），用于把状态码接入 tenacity 的重试判定。"""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"HTTP {response.status_code}")


class HttpClient:
    """httpx.AsyncClient 的统一封装。所有采集请求都必须走 :meth:`request`。"""

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        connect_timeout_s: float = 5.0,
        read_timeout_s: float = 20.0,
        max_retries: int = 3,
        max_concurrency: int = 6,
        cache_enabled: bool = True,
        cache_path: Path | None = None,
        cache_ttl_s: int = 1800,
        proxy: str | None = None,
        default_headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.connect_timeout_s = connect_timeout_s
        self.read_timeout_s = read_timeout_s
        self.max_retries = max_retries
        # 供需要并发子请求的采集器（如 RSS 多 feed）自行限流，与全局并发保持一致
        self.max_concurrency = max_concurrency
        self.cache_enabled = cache_enabled
        self.cache_ttl_s = cache_ttl_s
        self.proxy = proxy if proxy is not None else resolve_proxy()
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0}

        headers = {"User-Agent": user_agent, "Accept": "*/*"}
        if default_headers:
            headers.update(dict(default_headers))

        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(None, connect=connect_timeout_s, read=read_timeout_s),
                follow_redirects=True,
                proxy=self.proxy,
            )
            self._owns_client = True

        self._cache: HttpCache | None = None
        if cache_enabled and cache_path is not None:
            self._cache = HttpCache(Path(cache_path), ttl_s=cache_ttl_s)
        self._buckets: dict[str, TokenBucket] = {}
        self._rate_limits: dict[str, RateLimit] = {}

    # ── 限速 ────────────────────────────────────────────────────────────
    def set_rate_limit(self, source: str, spec: str) -> None:
        """为某个源设置限速，如 `set_rate_limit("arxiv", "3/s")`。"""
        self._rate_limits[source] = RateLimit.parse(spec)
        self._buckets.pop(source, None)

    def bucket(self, source: str, spec: str | None = None) -> TokenBucket:
        """取（或按需创建）某源的令牌桶；未配置限速时用宽松默认值 10/1s。"""
        if spec is not None:
            limit = RateLimit.parse(spec)
            if self._rate_limits.get(source) != limit:
                self._rate_limits[source] = limit
                self._buckets.pop(source, None)
        if source not in self._buckets:
            self._buckets[source] = TokenBucket(
                self._rate_limits.get(source, RateLimit.parse("10/1s"))
            )
        return self._buckets[source]

    # ── 请求 ────────────────────────────────────────────────────────────
    async def request(
        self,
        method: str,
        url: str,
        *,
        source: str = "default",
        params: Mapping[str, str | int | float | bool | None] | None = None,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        content: bytes | str | None = None,
        rate_limit: str | None = None,
        cache: bool | None = None,
        cache_ttl_s: int | None = None,
        timeout: httpx.Timeout | None = None,
        max_retries: int | None = None,
    ) -> httpx.Response:
        """发一个请求。缓存命中直接返回，未命中才走限速 + 重试。"""
        use_cache = self.cache_enabled if cache is None else cache
        key = HttpCache.make_key(method, url, dict(params or {}) if params else None)

        if use_cache and self._cache is not None:
            cached = self._cache.get(key, cache_ttl_s)
            if cached is not None:
                self.stats["cache_hits"] += 1
                log.debug("http.cache.hit", url=url, source=source)
                return cached

        await self.bucket(source, rate_limit).acquire()

        attempts = max(1, self.max_retries if max_retries is None else max_retries)
        request_timeout = timeout or httpx.Timeout(
            None, connect=self.connect_timeout_s, read=self.read_timeout_s
        )

        async def send_once() -> httpx.Response:
            self.stats["requests"] += 1
            response = await self._client.request(
                method,
                url,
                params=params,
                headers=dict(headers) if headers else None,
                json=json_body,
                content=content,
                timeout=request_timeout,
            )
            log.debug(
                "http.response",
                url=url,
                source=source,
                status=response.status_code,
                bytes=len(response.content),
            )
            if _is_retryable(response):
                # 把"可重试状态码"转成异常交给 tenacity，避免依赖它的 result 判定语义
                raise _RetryableStatus(response)
            return response

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential_jitter(initial=0.5, max=8.0),
                retry=retry_if_exception_type((_RetryableStatus, *RETRY_EXCEPTIONS)),
                reraise=True,
            ):
                with attempt:
                    response = await send_once()
                    if use_cache and self._cache is not None and response.status_code < 400:
                        self._cache.put(key, url, response)
                    return response
        except _RetryableStatus as exc:
            # 重试耗尽：返回最后一次响应，是否算失败由调用方决定（单源失败不得中断全局）
            log.warning(
                "http.retry_exhausted", url=url, source=source, status=exc.response.status_code
            )
            return exc.response
        raise AssertionError("unreachable")  # pragma: no cover

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def fetch_text(self, url: str, **kwargs: Any) -> str:
        response = await self.request("GET", url, **kwargs)
        return response.text

    async def fetch_json(self, url: str, **kwargs: Any) -> Any:
        response = await self.request("GET", url, **kwargs)
        return response.json()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
