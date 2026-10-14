"""App reviews: Google Play + App Store -> one unified dataset + Markdown summary (PRIVATE build)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from apify import Actor

import sources as S
from charging import Charger
from summary import build_markdown

PRIMARY = "review"
SUMMARY_EVENT = "summary-report"


def _date(v: str | None, end: bool = False) -> datetime | None:
    if not v:
        return None
    v = v.strip()
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Bad date {v!r}; use YYYY-MM-DD") from None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    if end and len(v) == 10:
        d = d + timedelta(days=1) - timedelta(microseconds=1)
    return d


def row(platform: str, app_id: str, name: str | None, r: dict, country: str, lang: str | None) -> dict:
    return {"platform": platform, "appId": app_id, "appName": name, "reviewId": r["reviewId"], "rating": r["rating"],
            "date": r["date"].isoformat(), "version": r["version"], "title": r["title"], "text": r["text"],
            "userName": r["userName"], "developerReply": r["developerReply"],
            "developerReplyDate": r["developerReplyDate"], "country": country, "lang": lang}


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        country = (inp.get("country") or "us").strip().lower()
        lang = (inp.get("lang") or "en").strip().lower()
        platforms = inp.get("platforms") or ["googlePlay", "appStore"]
        max_reviews = int(inp.get("maxReviews") or 200)
        want_summary = inp.get("summary", True)
        name = (inp.get("appName") or "").strip()
        play_id = S.parse_play_id(inp.get("playApp"))
        apple_id = S.parse_apple_id(inp.get("appStoreApp"))
        try:
            d_from, d_to = _date(inp.get("dateFrom")), _date(inp.get("dateTo"), end=True)
        except ValueError as e:
            await Actor.fail(status_message=str(e))
            return
        if not (name or play_id or apple_id):
            await Actor.fail(status_message="Give appName, or playApp and/or appStoreApp (id or store URL).")
            return
        older = (lambda dt: d_from is not None and dt < d_from)
        newer = (lambda dt: d_to is not None and dt > d_to)
        ch = Charger(PRIMARY)
        status: dict = {}
        all_rows: list[dict] = []
        names: dict = {}
        ids: dict = {}

        if "appStore" in platforms:
            try:
                info = await asyncio.to_thread(S.apple_lookup, apple_id, country) if apple_id else \
                    await asyncio.to_thread(S.apple_search, name, country)
                if not info:
                    status["appStore"] = {"status": "not_found"}
                else:
                    aid = str(info["trackId"])
                    ids["appStore"], names["appStore"] = aid, info.get("trackName")
                    revs, st = await asyncio.to_thread(S.apple_reviews, aid, country, older, max_reviews, newer)
                    rows = [row("appStore", aid, info.get("trackName"), r, country, None) for r in revs]
                    stored = await ch.push_and_charge(rows)
                    all_rows += rows[:stored]
                    status["appStore"] = {"status": "ok", "reviews": stored, "appId": aid, **st}
                    Actor.log.info(f"App Store {aid}: {stored} reviews ({st})")
            except Exception as e:  # noqa: BLE001
                status["appStore"] = {"status": "error", "error": str(e)[:300]}
                Actor.log.warning(f"App Store failed: {e}")

        if "googlePlay" in platforms and not ch.limit_reached:
            try:
                pid = play_id or await asyncio.to_thread(S.play_search, name or names.get("appStore", ""), country, lang)
                info = await asyncio.to_thread(S.play_app, pid, country, lang) if pid else None
                if not info:
                    status["googlePlay"] = {"status": "not_found", "appId": pid}
                else:
                    ids["googlePlay"], names["googlePlay"] = pid, info.get("title")
                    revs, st = await asyncio.to_thread(S.play_reviews, pid, country, lang, older, max_reviews, newer)
                    rows = [row("googlePlay", pid, info.get("title"), r, country, lang) for r in revs]
                    stored = await ch.push_and_charge(rows)
                    all_rows += rows[:stored]
                    status["googlePlay"] = {"status": "ok", "reviews": stored, "appId": pid, **st}
                    Actor.log.info(f"Google Play {pid}: {stored} reviews")
            except Exception as e:  # noqa: BLE001
                status["googlePlay"] = {"status": "error", "error": str(e)[:300]}
                Actor.log.warning(f"Google Play failed: {e}")

        summary = {"input": {"appName": name, "country": country, "lang": lang, "dateFrom": inp.get("dateFrom"),
                             "dateTo": inp.get("dateTo"), "maxReviews": max_reviews},
                   "platforms": status, "reviews": len(all_rows), "charged": ch.counts}
        if want_summary and all_rows:
            meta = {"appName": name or names.get("appStore") or names.get("googlePlay"), "country": country, "lang": lang,
                    "window": f"{inp.get('dateFrom') or 'newest'} → {inp.get('dateTo') or 'now'}",
                    "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "appIds": ids}
            md, stats = build_markdown(meta, all_rows)
            await Actor.set_value("SUMMARY.md", md, content_type="text/markdown; charset=utf-8")
            summary["analysis"] = stats
            await ch.charge(SUMMARY_EVENT, 1)
        await Actor.set_value("SUMMARY", summary)
        ok = [p for p, s in status.items() if s.get("status") == "ok"]
        msg = f"{len(all_rows)} reviews · " + ", ".join(f"{p}: {s.get('status')} {s.get('reviews', '')}".strip() for p, s in status.items())
        if not ok:
            await Actor.fail(status_message="No platform returned reviews: " + msg)
            return
        await Actor.set_status_message(msg, is_terminal=True)
