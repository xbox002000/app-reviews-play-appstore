# App Reviews → Google Play + App Store (unified)

**One run, both stores, one dataset, plus a complaint report.** Give an app name (or a Play package / App Store id or URL). You get Google Play and App Store reviews in the same columns, and `SUMMARY.md` with the weekly rating trend and what ≤3★ reviewers complain about. About **$0.09 per 1,000 reviews**.

Real excerpt, Duolingo, US, run on 2026-10-14 (950 reviews):

```
| googlePlay | com.duolingo | 500 reviews | mean 4.42 | ≤3★ 15.6% |
| appStore   | 570060128    | 450 reviews | mean 3.81 | ≤3★ 30.2% |
≤3★ categories: Features & content 66 (30.8%) · Pricing & subscription 53 (24.8%)
                Update & UI changes 30 (14.0%) · Ads 28 (13.1%) · Crashes & bugs 16 (7.5%)
TF-IDF keywords: learning, lesson, ads, day, energy, learn, language, annoying, pay, free
```

**Limits, up front:** the App Store only serves the newest ~500 reviews per country; App Store rows have no developer reply and no language; complaint categories are keyword rules, mostly English.

## Output (dataset)
`platform` (googlePlay | appStore), `appId`, `appName`, `reviewId`, `rating`, `date` (ISO, UTC), `version`, `title` (App Store only), `text`, `userName`, `developerReply`, `developerReplyDate` (Google Play only), `country`, `lang` (Google Play only).

## SUMMARY.md (key-value store)
- Reviews, mean rating and ≤3★ share per platform
- Weekly average rating per platform (ISO weeks, UTC)
- For ≤3★ reviews: complaint categories from a keyword lexicon (crashes, performance, login, pricing, ads, updates/UI, sync/data, features, notifications, support) with example quotes, and top TF-IDF keywords (unigrams + bigrams). Rule-based, no LLM.

`SUMMARY` holds the same numbers as JSON.

## Example input
```json
{ "appName": "Duolingo", "country": "us", "lang": "en", "dateFrom": "2026-09-01", "maxReviews": 500 }
```
API: `curl -X POST "https://api.apify.com/v2/acts/ingenious_quip_bxq~app-reviews-play-appstore/runs?token=YOUR_APIFY_TOKEN" -H 'Content-Type: application/json' -d @input.json`

## Sources and limits
- App Store: public iTunes Search/Lookup API and the customer-reviews RSS feed, newest first. Apple serves at most 10 pages × 50 = **~500 newest reviews per country**. The feed has no developer replies. Some pages come back empty at random; the Actor retries each page, and pages that stay empty are reported in `SUMMARY.platforms.appStore.pagesEmpty`.
- Google Play: the open-source `google-play-scraper` package (public web endpoints), newest first, filtered by `lang` and `country`.
- No login, no cookies, no API key.

## Pricing (pay per event)
- Review saved: $0.00009 ($0.09 per 1,000)
- Summary report: $0.001 per run
- Actor start: $0.00005
Nothing is charged for a platform that fails or finds no app.

License: AGPL-3.0.

## Source code
https://github.com/xbox002000/app-reviews-play-appstore (AGPL-3.0)
