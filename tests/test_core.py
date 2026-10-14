import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import sources as S, summary as M


def test_ids():
    assert S.parse_play_id("https://play.google.com/store/apps/details?id=com.duolingo&hl=en") == "com.duolingo"
    assert S.parse_play_id("notion.id") == "notion.id"
    assert S.parse_play_id("Duolingo") is None
    assert S.parse_apple_id("https://apps.apple.com/us/app/notion/id1232780281") == "1232780281"
    assert S.parse_apple_id(570060128) == "570060128"
    assert S.parse_apple_id("abc") is None


def test_categories_word_boundary():
    assert "Ads" not in M.categorize("bad and sad")
    c = M.categorize("Too many ads, it crashes after the update and the subscription is expensive")
    assert {"Ads", "Crashes & bugs", "Update & UI changes", "Pricing & subscription"} <= set(c)
    assert "Pricing & subscription" not in M.categorize("tell us more about the quests")


def test_summary_and_trend():
    rows = [{"platform": "appStore", "rating": r, "date": d, "title": "", "text": t} for r, d, t in [
        (1, "2026-10-05T10:00:00+00:00", "crashes on login every time"),
        (2, "2026-10-06T10:00:00+00:00", "crashes on login again"),
        (5, "2026-10-13T10:00:00+00:00", "great")]]
    md, st = M.build_markdown({"appName": "X", "country": "us", "lang": "en", "window": "w", "generatedAt": "g",
                               "appIds": {"appStore": "1"}}, rows)
    assert st["weeklyTrend"]["appStore"] == [{"weekStart": "2026-10-05", "reviews": 2, "avgRating": 1.5},
                                             {"weekStart": "2026-10-12", "reviews": 1, "avgRating": 5.0}]
    kws = [k["term"] for k in st["lowRated"]["All platforms"]["keywords"]]
    assert "crashes login" in kws
    assert "Weekly average rating" in md


def test_xml_entries():
    xml = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:im="http://itunes.apple.com/rss"><entry>'
           '<updated>2026-10-12T22:33:50-07:00</updated><id>14660505559</id><title>t</title>'
           '<content type="text">hello</content><im:version>9.1</im:version><im:rating>4</im:rating>'
           '<author><name>u</name></author></entry></feed>')
    e = S._xml_entries(xml)[0]
    assert e["id"]["label"] == "14660505559" and e["im:rating"]["label"] == "4" and e["content"]["label"] == "hello"
