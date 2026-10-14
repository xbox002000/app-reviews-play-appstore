"""Markdown summary: weekly rating trend per platform + rule-based complaint analysis (no LLM).

- Trend: ISO-week (Monday, UTC) mean rating and count per platform.
- Keywords: TF-IDF over reviews rated <= 3 (unigrams + bigrams), document frequency >= 2.
- Categories: heuristic keyword lexicon (English + a few es/de/fr/pt stems); one review can hit several.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

LOW = 3

STOP = set("""a about above after again against all also am an and any are aren't as at be because been before being below
between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each even ever every
few for from further get gets got had hadn't has hasn't have haven't having he her here hers him his how i i'm i've if in into
is isn't it it's its itself just let like me more most much my myself no nor not now of off on once one only or other our
ours out over own please really same she should shouldn't so some such than that that's the their theirs them then there
these they they're this those through to too under until up us very was wasn't we we're were weren't what when where which
while who whom why will with won't would wouldn't you you're your yours app apps use using used im dont cant ive thats
still way thing things time make makes made want need lot also us its make go going well good great love even get got
el la los las de y que en un una es por con para lo se no me mi al del le les des et est pas pour une der die das und ist
nicht ich zu den mit ein eine o os um uma não com""".split())

CATEGORIES: dict[str, list[str]] = {
    "Crashes & bugs": ["crash", "crashes", "crashing", "bug", "bugs", "buggy", "glitch", "freez", "froze", "error",
                       "broken", "not working", "doesn't work", "stopped working", "won't open", "black screen", "fehler", "falla"],
    "Performance & battery": ["slow", "lag", "laggy", "loading", "load", "battery", "drain", "storage", "heavy", "takes forever"],
    "Login & account": ["login", "log in", "sign in", "signin", "logged out", "password", "account", "verification", "verify", "2fa", "otp"],
    "Pricing & subscription": ["subscription", "subscribe", "premium", "price", "pricing", "expensive", "paywall", "pay", "paid",
                               "charge", "charged", "refund", "trial", "billing", "money", "cancel", "suscrip", "abonnement"],
    "Ads": ["ads\\b", "ad\\b", "advert", "commercials?\\b", "anuncio", "werbung", "pubs?\\b"],
    "Update & UI changes": ["update", "updated", "new version", "redesign", "interface", "ui", "layout", "design", "used to", "bring back", "old version"],
    "Sync, data & offline": ["sync", "offline", "lost", "deleted", "data", "backup", "download", "saved", "disappear"],
    "Features & content": ["feature", "missing", "add\\b", "option", "playlist", "shuffle", "lesson", "streak", "hearts", "energy",
                           "template", "content", "limit", "limited"],
    "Notifications": ["notification", "notifications", "spam", "reminder", "push notification"],
    "Customer support": ["support", "customer service", "no response", "contact", "help center", "reply"],
}

WORD = re.compile(r"[a-zà-ÿ][a-zà-ÿ'’]+")


def tokens(text: str) -> list[str]:
    return [w.replace("’", "'") for w in WORD.findall((text or "").lower())]


def grams(text: str) -> set[str]:
    ws = [w for w in tokens(text) if w not in STOP and len(w) > 2]
    return set(ws) | {f"{a} {b}" for a, b in zip(ws, ws[1:])}


def week_start(d: datetime) -> str:
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def weekly_trend(rows: list[dict]) -> dict[str, list[tuple[str, int, float]]]:
    acc: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        acc[r["platform"]][week_start(datetime.fromisoformat(r["date"]))].append(r["rating"])
    return {p: [(w, len(v), round(sum(v) / len(v), 2)) for w, v in sorted(ws.items())] for p, ws in acc.items()}


def tfidf_keywords(low: list[dict], all_rows: list[dict], top: int = 20, exclude: set[str] | None = None) -> list[tuple[str, int, float]]:
    """Rank terms that are frequent in low-rated reviews and comparatively rare across all reviews."""
    if not low:
        return []
    n_all = len(all_rows)
    df_all: Counter = Counter()
    for r in all_rows:
        df_all.update(grams(f"{r.get('title') or ''} {r.get('text') or ''}"))
    df_low: Counter = Counter()
    for r in low:
        df_low.update(grams(f"{r.get('title') or ''} {r.get('text') or ''}"))
    scored = []
    for t, c in df_low.items():
        if c < 2 or (exclude and any(w in exclude for w in t.split())):
            continue
        idf = math.log((1 + n_all) / (1 + df_all[t])) + 1
        scored.append((t, c, round((c / len(low)) * idf * (1.15 if " " in t else 1.0), 4)))
    scored.sort(key=lambda x: (-x[2], -x[1], x[0]))
    out, seen = [], set()
    for t, c, s in scored:  # drop unigrams already covered by a stronger bigram with the same count
        if " " not in t and any(t in b.split() and bc == c for b, bc, _ in out):
            continue
        out.append((t, c, s))
        seen.add(t)
        if len(out) >= top:
            break
    return out


# Each entry is matched at a word start (prefix match unless it ends with \b), so "ad\b" never hits "bad".
CAT_RE = {cat: re.compile(r"\b(?:" + "|".join(k if "\\" in k else re.escape(k) for k in kws) + ")") for cat, kws in CATEGORIES.items()}


def categorize(text: str) -> list[str]:
    t = (text or "").lower().replace("’", "'")
    return [cat for cat, rx in CAT_RE.items() if rx.search(t)]


def complaint_categories(low: list[dict]) -> list[tuple[str, int, float, str]]:
    cnt: Counter = Counter()
    example: dict[str, str] = {}
    for r in low:
        txt = f"{r.get('title') or ''} {r.get('text') or ''}"
        for c in categorize(txt):
            cnt[c] += 1
            if c not in example and 30 <= len(r.get("text") or "") <= 220:
                example[c] = (r.get("text") or "").replace("\n", " ").strip()
    n = len(low) or 1
    return [(c, k, round(100 * k / n, 1), example.get(c, "")) for c, k in cnt.most_common()]


def build_markdown(meta: dict, rows: list[dict]) -> tuple[str, dict]:
    trend = weekly_trend(rows)
    lines = [f"# App reviews summary — {meta.get('appName') or ''}".rstrip(), ""]
    lines.append(f"Country `{meta['country']}` · lang `{meta['lang']}` · window {meta['window']} · generated {meta['generatedAt']}")
    lines.append("")
    lines.append("| Platform | App id | Reviews | Mean rating | ≤3★ share |")
    lines.append("|---|---|---|---|---|")
    stats: dict = {"platforms": {}}
    for p in ("googlePlay", "appStore"):
        pr = [r for r in rows if r["platform"] == p]
        if not pr and p not in meta.get("appIds", {}):
            continue
        mean = round(sum(r["rating"] for r in pr) / len(pr), 2) if pr else None
        lowp = round(100 * sum(1 for r in pr if r["rating"] <= LOW) / len(pr), 1) if pr else None
        stats["platforms"][p] = {"reviews": len(pr), "meanRating": mean, "lowSharePct": lowp}
        lines.append(f"| {p} | `{meta.get('appIds', {}).get(p, '—')}` | {len(pr)} | {mean if mean is not None else '—'} | "
                     f"{f'{lowp}%' if lowp is not None else '—'} |")
    lines += ["", "## Weekly average rating (ISO weeks, UTC, Monday start)", ""]
    for p, ws in trend.items():
        lines += [f"### {p}", "", "| Week of | Reviews | Avg ★ |", "|---|---|---|"]
        lines += [f"| {w} | {n} | {a} |" for w, n, a in ws]
        lines.append("")
    stats["weeklyTrend"] = {p: [{"weekStart": w, "reviews": n, "avgRating": a} for w, n, a in ws] for p, ws in trend.items()}
    low = [r for r in rows if r["rating"] <= LOW]
    lines += [f"## Reviews rated ≤{LOW}★: {len(low)} of {len(rows)}", ""]
    for scope, subset in [("All platforms", low)] + [(p, [r for r in low if r["platform"] == p]) for p in trend]:
        if not subset:
            continue
        cats = complaint_categories(subset)
        kws = tfidf_keywords(subset, rows, exclude=set(tokens(meta.get("appName") or "")))
        lines += [f"### {scope} — complaint categories (keyword lexicon)", "",
                  "| Category | Reviews | Share of ≤3★ | Example |", "|---|---|---|---|"]
        lines += [f"| {c} | {k} | {s}% | {ex[:160].replace('|', '/')} |" for c, k, s, ex in cats] or ["| — | 0 | — | |"]
        lines += ["", f"### {scope} — top keywords (TF-IDF, uni+bigrams, ≥2 reviews)", "",
                  ", ".join(f"`{t}` ({c})" for t, c, _ in kws) or "—", ""]
        stats.setdefault("lowRated", {})[scope] = {"count": len(subset),
                                                   "categories": [{"category": c, "reviews": k, "sharePct": s} for c, k, s, _ in cats],
                                                   "keywords": [{"term": t, "reviews": c, "score": sc} for t, c, sc in kws]}
    lines += ["## Method & limits", "",
              "- App Store: public iTunes Lookup/Search + customer-reviews RSS (newest first; Apple caps it at 10 pages × 50 = 500 reviews per country; no developer replies in the feed).",
              "- Google Play: open-source `google-play-scraper`, newest first.",
              "- Categories are keyword rules, keywords are TF-IDF; no LLM. A review can fall into several categories.", ""]
    return "\n".join(lines), stats
