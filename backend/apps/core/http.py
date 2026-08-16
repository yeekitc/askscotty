"""One outbound HTTP path for everything we fetch ourselves.

The live-tool clients (tasklist B2) and the crawler (B1) all want the same four
things: a timeout, a couple of retries, an identifying User-Agent, and enough
politeness not to hammer a public CMU API during a demo. Written once here
rather than twice in two lanes. It lives in `apps.core` because that app sits
below `apps.tools`, `apps.rag` and `apps.personal` in INSTALLED_APPS, so all
three can import it without a cycle.

GET only — every caller we know of is a read.

Out of scope: robots.txt, which is the crawler's own layer on top of this; and
Claude's server-side web_search / web_fetch, whose traffic never reaches this
process at all (docs/b3-web-verify.md).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 6.0

# Three attempts, and no new attempt once the budget is gone. A planner turn is
# blocked on this call, so the ceiling for an upstream that accepts the
# connection and then hangs has to be about two timeouts, not three.
_MAX_ATTEMPTS = 3
_RETRY_BUDGET = 10.0
_RETRY_BACKOFF = 0.25

# Only what a second attempt could plausibly fix. A 404 is still a 404 next time.
_RETRY_STATUSES = frozenset({429, 502, 503, 504})

# Minimum gap between two requests to one host. Deliberately not a token bucket:
# the real load is a handful of tool calls per conversation turn.
_MIN_HOST_INTERVAL = 0.25

_gates_lock = threading.Lock()
_host_gates: dict[str, threading.Lock] = {}
_host_last_request: dict[str, float] = {}

_client_lock = threading.Lock()
_client_instance: httpx.Client | None = None

_MISS = object()


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    ttl: float = 0.0,
) -> Any:
    """GET `url` and decode the JSON body.

    `ttl` is seconds to cache the decoded response for, keyed on url and params.
    Zero — the default — reads nothing and writes nothing. It is per call rather
    than one global constant because the honest answer differs per source: a
    course catalog barely moves during a demo, dining hours do.

    Never pass `ttl > 0` for a request carrying someone's identity. The cache is
    process-wide and keyed only on url and params, so two students hitting the
    same authenticated endpoint with different tokens would collide and one
    could be served the other's data. A personal connector (PRD §9) that wants
    caching has to fold the user into the key, which this helper does not do.

    Raises whatever httpx raises once the retries are spent — an unreachable
    host, a timeout, or a non-2xx status. A tool calling this is expected to
    catch and re-raise as ToolError (apps/tools/registry.py) so a dead upstream
    degrades the answer instead of failing the request.
    """
    key = _cache_key(url, params) if ttl > 0 else None

    if key is not None:
        cached = cache.get(key, _MISS)
        # Its own line rather than a field on registry.py's `tool_call` line:
        # tool dispatch runs in a thread pool, and contextvars do not cross a
        # ThreadPoolExecutor boundary. Adjacent timestamps read well enough.
        logger.info("http_cache hit=%s host=%s", cached is not _MISS, httpx.URL(url).host)
        if cached is not _MISS:
            return cached

    data = _fetch(url, params=params, timeout=timeout)

    if key is not None:
        cache.set(key, data, timeout=ttl)
    return data


def _fetch(url: str, *, params: dict[str, Any] | None, timeout: float) -> Any:
    host = httpx.URL(url).host
    headers = {"User-Agent": settings.CRAWLER_USER_AGENT}
    deadline = time.monotonic() + _RETRY_BUDGET

    for attempt in range(_MAX_ATTEMPTS):
        _throttle(host)
        try:
            response = _client().get(url, params=params, timeout=timeout, headers=headers)
        except httpx.RequestError:
            if _out_of_retries(attempt, deadline):
                raise
        else:
            if response.status_code not in _RETRY_STATUSES or _out_of_retries(attempt, deadline):
                response.raise_for_status()
                return response.json()
        time.sleep(_RETRY_BACKOFF * (attempt + 1))


def _out_of_retries(attempt: int, deadline: float) -> bool:
    return attempt >= _MAX_ATTEMPTS - 1 or time.monotonic() >= deadline


def _throttle(host: str) -> None:
    """Block until this host's minimum interval has elapsed.

    One lock per host, held only across the wait: tool dispatch is parallel
    (planner/loop.py), and a slow gate on one host must not queue up a call to
    a different one.
    """
    with _gates_lock:
        gate = _host_gates.setdefault(host, threading.Lock())

    with gate:
        wait = _host_last_request.get(host, 0.0) + _MIN_HOST_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _host_last_request[host] = time.monotonic()


def _cache_key(url: str, params: dict[str, Any] | None) -> str:
    payload = json.dumps(["GET", url, sorted((params or {}).items())], default=str)
    return "core.http:" + hashlib.sha256(payload.encode()).hexdigest()


def _client() -> httpx.Client:
    """The process-wide connection pool.

    The User-Agent is set per request instead of on the client so that changing
    the setting is honoured without rebuilding the pool.
    """
    global _client_instance
    if _client_instance is None:
        with _client_lock:
            if _client_instance is None:
                _client_instance = httpx.Client(follow_redirects=True)
    return _client_instance
