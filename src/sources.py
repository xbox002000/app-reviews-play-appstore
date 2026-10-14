"""Public, login-free review sources.

App Store: iTunes Search/Lookup API + customer-reviews RSS JSON (max 10 pages x 50 = 500 newest per country).
Google Play: google-play-scraper (MIT, open source) - public web endpoints, NEWEST sort with continuation.
"""
from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
RSS_MAX_PAGES = 10
RSS_PAGE_ATTEMPTS = 8

PLAY_ID_RE = re.compile(r"[?&]id=([A-Za-z0-9_.]+)")
APPLE_ID_RE = re.compile(r"(?:/id|^)(\d{6,12})(?:\D|$)")


def parse_play_id(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    m = PLAY_ID_RE.search(v)
    if m:
        return m.group(1)
    return v if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+", v) else None


def parse_apple_id(v: str | int | None) -> str | None:
    if v is None or v == "":
        return None
    m = APPLE_ID_RE.search(str(v).strip())
    return m.group(1) if m else None


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30)


def _get_json(c: httpx.Client, url: str, params: dict | None = None, tries: int = 4) -> Any:
    last: Exception | None = None
    for a in range(tries):
        try:
            r = c.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (a + 1))
    raise RuntimeError(f"request failed: {last}")


# ---------------- App Store ----------------

def apple_lookup(app_id: str, country: str) -> dict | None:
    with _client() as c:
        j = _get_json(c, "https://itunes.apple.com/lookup", {"id": app_id, "country": country, "entity": "software"})
    res = [x for x in j.get("results", []) if x.get("trackId")]
    return res[0] if res else None


def apple_search(term: str, country: str) -> dict | None:
    with _client() as c:
        j = _get_json(c, "https://itunes.apple.com/search",
                      {"term": term, "country": country, "entity": "software", "limit": 5})
    res = [x for x in j.get("results", []) if x.get("trackId")]
    return res[0] if res else None


ATOM = "{http://www.w3.org/2005/Atom}"
IM = "{http://itunes.apple.com/rss}"


def _xml_entries(text: str) -> list[dict]:
    """Parse the XML variant of the feed into the same shape as the JSON entries."""
    import xml.etree.ElementTree as ET
    out = []
    for e in ET.fromstring(text).findall(f"{ATOM}entry"):
        rating = e.find(f"{IM}rating")
        if rating is None:
            continue
        content = next((c for c in e.findall(f"{ATOM}content") if c.get("type") == "text"), None)
        out.append({"id": {"label": e.findtext(f"{ATOM}id")}, "updated": {"label": e.findtext(f"{ATOM}updated")},
                    "im:rating": {"label": rating.text}, "im:version": {"label": e.findtext(f"{IM}version")},
                    "title": {"label": e.findtext(f"{ATOM}title")},
                    "content": {"label": content.text if content is not None else None},
                    "author": {"name": {"label": e.findtext(f"{ATOM}author/{ATOM}name")}}})
    return out


def _rss_page(c: httpx.Client, app_id: str, country: str, page: int, attempts: int = RSS_PAGE_ATTEMPTS) -> tuple[list[dict], int]:
    """Apple's feed often answers an empty page for a page that has data. Retry, alternating the JSON and XML
    variants with cache-busting query params."""
    for a in range(attempts):
        fmt = "json" if a % 2 == 0 else "xml"
        q = "" if a < 2 else random.choice(["?l=en", "?l=en-US", f"?cb={random.randint(1, 10**9)}"])
        url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortBy=mostRecent/{fmt}{q}"
        try:
            r = c.get(url)
            if r.status_code != 200:
                entries = []
            elif fmt == "json":
                entries = r.json().get("feed", {}).get("entry", [])
            else:
                entries = _xml_entries(r.text)
        except Exception:  # noqa: BLE001
            entries = []
        if isinstance(entries, dict):
            entries = [entries]
        entries = [e for e in entries if "im:rating" in e]
        if entries:
            return entries, a + 1
        time.sleep(0.5 + 0.25 * a)
    return [], attempts


def apple_reviews(app_id: str, country: str, stop: Callable[[datetime], bool], limit: int,
                  newer: Callable[[datetime], bool]) -> tuple[list[dict], dict]:
    pages: dict[int, list[dict]] = {}
    stats = {"pagesOk": 0, "pagesEmpty": 0, "attempts": 0}
    with _client() as c:
        for page in range(1, RSS_MAX_PAGES + 1):
            entries, att = _rss_page(c, app_id, country, page)
            stats["attempts"] += att
            pages[page] = entries
            if entries:
                last = datetime.fromisoformat(entries[-1]["updated"]["label"]).astimezone(timezone.utc)
                if stop(last) or sum(len(v) for v in pages.values()) >= limit * 1.2 + 50:
                    break
        filled = [p for p in pages if pages[p]]
        if filled:  # second pass, after a pause, for empty pages inside the range that has data
            time.sleep(3)
            for page in [p for p in pages if not pages[p] and p < max(filled)] + \
                        [p for p in pages if not pages[p] and p > max(filled)]:
                entries, att = _rss_page(c, app_id, country, page, attempts=6)
                stats["attempts"] += att
                pages[page] = entries
    stats["pagesOk"] = sum(1 for v in pages.values() if v)
    stats["pagesEmpty"] = sum(1 for v in pages.values() if not v)
    stats["emptyPages"] = [p for p, v in pages.items() if not v]
    out: list[dict] = []
    seen: set[str] = set()
    for page in sorted(pages):
        for e in pages[page]:
            rid = e["id"]["label"]
            if rid in seen:
                continue
            seen.add(rid)
            dt = datetime.fromisoformat(e["updated"]["label"]).astimezone(timezone.utc)
            if newer(dt) or stop(dt):
                continue
            out.append({"reviewId": rid, "rating": int(e["im:rating"]["label"]), "date": dt,
                        "version": (e.get("im:version") or {}).get("label"),
                        "title": (e.get("title") or {}).get("label"),
                        "text": (e.get("content") or {}).get("label"),
                        "userName": ((e.get("author") or {}).get("name") or {}).get("label"),
                        "developerReply": None, "developerReplyDate": None})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out[:limit], stats


# ---------------- Google Play ----------------

def play_search(term: str, country: str, lang: str) -> str | None:
    from google_play_scraper import search
    try:
        hits = search(term, lang=lang, country=country, n_hits=3)
        if hits and hits[0].get("appId"):
            return hits[0]["appId"]
    except Exception:  # noqa: BLE001
        pass
    # The package returns appId=None for the top (featured) hit; read the public search page instead.
    with _client() as c:
        r = c.get("https://play.google.com/store/search", params={"q": term, "c": "apps", "hl": lang, "gl": country})
    ids = re.findall(r"/store/apps/details\?id=([A-Za-z0-9_.]+)", r.text)
    return ids[0] if ids else None


def play_app(app_id: str, country: str, lang: str) -> dict | None:
    from google_play_scraper import app
    from google_play_scraper.exceptions import NotFoundError
    try:
        return app(app_id, lang=lang, country=country)
    except NotFoundError:
        return None


def play_reviews(app_id: str, country: str, lang: str, stop: Callable[[datetime], bool], limit: int,
                 newer: Callable[[datetime], bool]) -> tuple[list[dict], dict]:
    from google_play_scraper import Sort, reviews
    out: list[dict] = []
    token = None
    stats = {"batches": 0}
    while len(out) < limit:
        batch, token = None, token
        for a in range(4):
            try:
                batch, token = reviews(app_id, lang=lang, country=country, sort=Sort.NEWEST,
                                       count=min(200, max(limit - len(out), 1) + 20), continuation_token=token)
                break
            except Exception:  # noqa: BLE001
                time.sleep(2 * (a + 1))
        stats["batches"] += 1
        if not batch:
            break
        older = False
        for r in batch:
            dt = r["at"].astimezone(timezone.utc)  # package returns naive local time
            if newer(dt):
                continue
            if stop(dt):
                older = True
                break
            rep = r.get("repliedAt")
            out.append({"reviewId": r["reviewId"], "rating": int(r["score"]), "date": dt,
                        "version": r.get("reviewCreatedVersion") or r.get("appVersion"), "title": None,
                        "text": r.get("content"), "userName": r.get("userName"),
                        "developerReply": r.get("replyContent"),
                        "developerReplyDate": rep.astimezone(timezone.utc).isoformat() if rep else None})
            if len(out) >= limit:
                break
        if older or token is None or getattr(token, "token", "x") is None:
            break
    return out, stats
