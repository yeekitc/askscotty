"""Campus index crawler.

Fetches public CMU pages, respects robots.txt and per-host rate limits,
extracts heading-structured text, and saves Document + Chunk rows.

The hard exclusion list below is the mechanical enforcement of PRD §3
("do not scrape behind logins") — no config option overrides it.
"""

import hashlib
import logging
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone

from apps.rag.chunker import chunk_sections
from apps.rag.models import Chunk, Document

logger = logging.getLogger(__name__)

# PRD §3: never crawl these, regardless of seeds or discovered links.
_BLOCKED_DOMAINS = frozenset({
    "sio.andrew.cmu.edu",
    "canvas.cmu.edu",
    "stellic.com",
    "autolab.andrew.cmu.edu",
    "25live.collegenet.com",
    "handshake.com",
    "accounts.google.com",
    "login.cmu.edu",
})

_RATE_LIMIT_DELAY = 1.0  # seconds between requests to the same host


def _host(url: str) -> str:
    return urlparse(url).netloc


def _is_blocked(url: str) -> bool:
    host = _host(url)
    return any(host == d or host.endswith("." + d) for d in _BLOCKED_DOMAINS)


def _get_robots(url: str, client: httpx.Client, cache: dict) -> RobotFileParser:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    if robots_url not in cache:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            resp = client.get(robots_url)
            rp.parse(resp.text.splitlines())
        except Exception:
            rp.parse([])  # network error reading robots.txt → assume allowed
        cache[robots_url] = rp
    return cache[robots_url]


def _robots_allowed(url: str, client: httpx.Client, cache: dict) -> bool:
    rp = _get_robots(url, client, cache)
    return rp.can_fetch(settings.CRAWLER_USER_AGENT, url)


def _extract_sections(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Extract heading-segmented text from cleaned HTML.

    Removes boilerplate (nav/footer/header/script/style/aside), then walks
    the remaining elements collecting paragraphs under each heading context.
    Returns list of (heading_path, text).
    """
    for tag in soup(["nav", "footer", "header", "script", "style", "aside", "noscript"]):
        tag.decompose()

    body = soup.find("body") or soup
    sections: list[tuple[str, str]] = []
    path: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        text = " ".join(buffer).strip()
        if text:
            sections.append((" > ".join(path), text))
        buffer.clear()

    for el in body.find_all(["h1", "h2", "h3", "p", "li", "blockquote", "td"]):
        if el.name in ("h1", "h2", "h3"):
            flush()
            level = int(el.name[1])
            path = path[: level - 1] + [el.get_text(" ", strip=True)]
        else:
            if el.find_parent(["h1", "h2", "h3"]):
                continue  # heading text already captured via heading path
            text = el.get_text(" ", strip=True)
            if text:
                buffer.append(text)

    flush()
    return sections


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Return same-host absolute links found in the page."""
    base_host = _host(base_url)
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0]
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        if _host(full) != base_host:
            continue
        links.append(full)
    return links


def crawl_seeds(seeds, *, limit: int = 500, depth: int = 2, stdout=None) -> int:
    """Crawl a list of CrawlSeed objects, saving Documents and Chunks.

    Returns the total number of pages fetched (including unchanged skips).
    """
    client = httpx.Client(
        headers={"User-Agent": settings.CRAWLER_USER_AGENT},
        follow_redirects=True,
        timeout=30.0,
    )
    robots_cache: dict = {}
    last_request: dict[str, float] = {}
    pages_fetched = 0

    try:
        for seed in seeds:
            if pages_fetched >= limit:
                break

            seed_url = seed.url
            if _is_blocked(seed_url):
                logger.warning("seed %s is in the blocked-domain list — skipping", seed_url)
                continue

            queue: list[tuple[str, int]] = [(seed_url, 0)]
            visited: set[str] = set()

            while queue and pages_fetched < limit:
                url, current_depth = queue.pop(0)
                if url in visited or _is_blocked(url):
                    continue
                visited.add(url)

                if not _robots_allowed(url, client, robots_cache):
                    logger.debug("robots.txt disallows %s", url)
                    continue

                # Per-host rate limit.
                host = _host(url)
                elapsed = time.monotonic() - last_request.get(host, 0.0)
                if elapsed < _RATE_LIMIT_DELAY:
                    time.sleep(_RATE_LIMIT_DELAY - elapsed)
                last_request[host] = time.monotonic()

                try:
                    response = client.get(url)
                    response.raise_for_status()
                except Exception as exc:
                    logger.warning("fetch_error url=%s error=%s", url, exc)
                    continue

                if "text/html" not in response.headers.get("content-type", ""):
                    continue

                pages_fetched += 1
                raw_html = response.text
                content_hash = hashlib.sha256(raw_html.encode()).hexdigest()

                # Skip re-chunking if content hasn't changed.
                try:
                    doc = Document.objects.get(url=url)
                    if doc.content_hash == content_hash:
                        if stdout:
                            stdout.write(f"  skip (unchanged): {url}")
                        if current_depth < depth:
                            soup = BeautifulSoup(raw_html, "html.parser")
                            for link in _extract_links(soup, url):
                                if link not in visited:
                                    queue.append((link, current_depth + 1))
                        continue
                    doc.content_hash = content_hash
                    is_new = False
                except Document.DoesNotExist:
                    doc = None
                    is_new = True

                soup = BeautifulSoup(raw_html, "html.parser")
                title = ""
                title_tag = soup.find("title")
                if title_tag:
                    title = title_tag.get_text(strip=True)[:500]

                sections = _extract_sections(soup)
                chunks_data = chunk_sections(sections)

                if is_new:
                    doc = Document.objects.create(
                        url=url,
                        title=title,
                        content_hash=content_hash,
                        robots_allowed=True,
                    )
                else:
                    doc.title = title
                    doc.save()
                    doc.chunks.all().delete()

                Chunk.objects.bulk_create([
                    Chunk(
                        document=doc,
                        text=chunk_text,
                        heading_path=heading_path,
                        token_count=token_count,
                    )
                    for chunk_text, heading_path, token_count in chunks_data
                ])

                if stdout:
                    stdout.write(f"  crawled: {url} ({len(chunks_data)} chunks)")

                if current_depth < depth:
                    for link in _extract_links(soup, url):
                        if link not in visited:
                            queue.append((link, current_depth + 1))

            seed.last_crawled_at = timezone.now()
            seed.save(update_fields=["last_crawled_at"])
    finally:
        client.close()

    return pages_fetched
