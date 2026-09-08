"""
India Trending News Report
---------------------------
Pulls trending-signal data for the Indian context from multiple sources and
produces a report as Markdown, JSON, and a self-contained HTML dashboard:

  1. Google Trends India      - always on, no API key needed (public RSS)
  2. Major Indian news RSS    - always on, no API key needed
  3. NewsAPI top headlines    - optional, needs NEWSAPI_KEY
  4. GNews top headlines      - optional, needs GNEWS_KEY
  5. X (Twitter) trends       - optional, needs TWITTER_BEARER_TOKEN
                                 (requires a paid API tier with access to
                                 GET /1.1/trends/place)

Usage:
    python trending_india.py                 # run once, print + save report
    python trending_india.py --open           # also open the dashboard in your browser
    python trending_india.py --loop           # run every 20 min forever
    python trending_india.py --loop --interval 15 --open
    python trending_india.py --top 15         # headlines per source

Config:
    Copy .env.example to .env and fill in any API keys you have. Sources
    without a key are simply skipped (noted in the report).
"""

import argparse
import html
import json
import os
import re
import sys
import time
import webbrowser
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

# Windows consoles default to cp1252, which can't print rupee signs, Hindi
# names, em-dashes, etc. that show up in real headlines.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REQUEST_TIMEOUT = 10
REPORTS_DIR = Path(__file__).parent / "reports"

NEWS_RSS_FEEDS = {
    "Times of India": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "NDTV": "https://feeds.feedburner.com/ndtvnews-top-stories",
    "Hindustan Times": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
    "Indian Express": "https://indianexpress.com/section/india/feed/",
    "The Hindu": "https://www.thehindu.com/news/national/feeder/default.rss",
    "Livemint": "https://www.livemint.com/rss/news",
    "Moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "News18": "https://www.news18.com/rss/india.xml",
}

GOOGLE_TRENDS_RSS_URLS = [
    "https://trends.google.com/trending/rss?geo=IN",
    "https://trends.google.com/trends/trendingsearches/daily/rss?geo=IN",
]

TWITTER_INDIA_WOEID = 23424848  # Yahoo WOEID for India

STOPWORDS = set(
    """a an the and or but if while is are was were be been being to of in on
    at for with by from as it its this that these those he she they we you i
    his her their our your not no yes will would can could should may might
    has have had do does did says said new after before over under out up
    down into onto than then so too very just also amid amidst about""".split()
)


def fetch_google_trends():
    for url in GOOGLE_TRENDS_RSS_URLS:
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = []
            for item in root.iter("item"):
                title_el = item.find("title")
                if title_el is None or not title_el.text:
                    continue
                traffic_el = item.find(
                    "{https://trends.google.com/trends/trendingsearches/daily}approx_traffic"
                )
                traffic = traffic_el.text if traffic_el is not None else None
                link_el = item.find("link")
                link = link_el.text.strip() if link_el is not None and link_el.text else None
                items.append({"title": title_el.text.strip(), "traffic": traffic, "link": link})
            if items:
                return items
        except Exception:
            continue
    return []


def fetch_news_rss(url, top_n):
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        headlines = []
        for entry in feed.entries[:top_n]:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip() or None
            if title:
                headlines.append({"title": html.unescape(title), "link": link})
        return headlines
    except Exception:
        return []


def fetch_newsapi(top_n):
    key = os.getenv("NEWSAPI_KEY")
    if not key:
        return None
    try:
        resp = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"country": "in", "pageSize": top_n, "apiKey": key},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": a["title"], "link": a.get("url")}
            for a in data.get("articles", [])
            if a.get("title")
        ]
    except Exception as e:
        return [{"title": f"(NewsAPI error: {e})", "link": None}]


def fetch_gnews(top_n):
    key = os.getenv("GNEWS_KEY")
    if not key:
        return None
    try:
        resp = requests.get(
            "https://gnews.io/api/v4/top-headlines",
            params={"country": "in", "max": top_n, "apikey": key},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": a["title"], "link": a.get("url")}
            for a in data.get("articles", [])
            if a.get("title")
        ]
    except Exception as e:
        return [{"title": f"(GNews error: {e})", "link": None}]


def fetch_twitter_trends():
    token = os.getenv("TWITTER_BEARER_TOKEN")
    if not token:
        return None
    try:
        resp = requests.get(
            "https://api.twitter.com/1.1/trends/place.json",
            params={"id": TWITTER_INDIA_WOEID},
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        trends = data[0].get("trends", []) if data else []
        return [
            {"title": t["name"], "link": t.get("url")} for t in trends if t.get("name")
        ]
    except Exception as e:
        return [{"title": f"(X/Twitter trends error: {e})", "link": None}]


def extract_cross_source_keywords(all_headlines, top_n=15):
    counter = Counter()
    for headline in all_headlines:
        words = re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", headline)
        phrases = re.findall(r"(?:[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){0,2})", headline)
        for p in phrases:
            if p.lower() not in STOPWORDS and len(p) > 3:
                counter[p] += 1
        for w in words:
            lw = w.lower()
            if lw not in STOPWORDS and len(w) > 3:
                counter[w] += 0.3  # lower weight for single common words
    return [{"term": term, "score": round(score, 1)} for term, score in counter.most_common(top_n)]


def collect_data(top_n):
    """Fetch every source once and return a plain-dict snapshot used to
    render the Markdown report, the HTML dashboard, and the JSON file."""
    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "google_trends": fetch_google_trends()[:top_n],
    }

    outlets = {}
    all_titles = []
    for name, url in NEWS_RSS_FEEDS.items():
        headlines = fetch_news_rss(url, top_n)
        outlets[name] = headlines  # empty list means unavailable
        all_titles.extend(h["title"] for h in headlines)
    data["outlets"] = outlets

    data["keywords"] = extract_cross_source_keywords(all_titles)
    data["newsapi"] = fetch_newsapi(top_n)
    data["gnews"] = fetch_gnews(top_n)
    data["twitter"] = fetch_twitter_trends()
    return data


def _md_link(title, link):
    return f"[{title}]({link})" if link else title


def render_markdown(data):
    lines = [f"# India Trending Report — {data['generated_at']}", ""]

    lines.append("## Google Trends (India) — top trending searches")
    if data["google_trends"]:
        for i, item in enumerate(data["google_trends"], 1):
            suffix = f"  (~{item['traffic']})" if item.get("traffic") else ""
            lines.append(f"{i}. {_md_link(item['title'], item.get('link'))}{suffix}")
    else:
        lines.append("_Unavailable right now (feed unreachable or format changed)._")
    lines.append("")

    lines.append("## Latest headlines by outlet")
    for name, headlines in data["outlets"].items():
        if headlines:
            lines.append(f"**{name}**")
            lines.extend(f"- {_md_link(h['title'], h.get('link'))}" for h in headlines)
            lines.append("")
        else:
            lines.append(f"**{name}** — _unavailable_")
            lines.append("")

    lines.append("## Cross-source trending keywords (derived from headlines above)")
    if data["keywords"]:
        lines.extend(f"- {kw['term']} ({kw['score']:.1f})" for kw in data["keywords"])
    else:
        lines.append("_Not enough headline data collected._")
    lines.append("")

    lines.append("## NewsAPI top headlines (India)")
    if data["newsapi"] is None:
        lines.append("_Skipped — set NEWSAPI_KEY in .env to enable (https://newsapi.org)._")
    else:
        lines.extend(f"- {_md_link(h['title'], h.get('link'))}" for h in data["newsapi"])
    lines.append("")

    lines.append("## GNews top headlines (India)")
    if data["gnews"] is None:
        lines.append("_Skipped — set GNEWS_KEY in .env to enable (https://gnews.io)._")
    else:
        lines.extend(f"- {_md_link(h['title'], h.get('link'))}" for h in data["gnews"])
    lines.append("")

    lines.append("## X (Twitter) trending topics — India")
    if data["twitter"] is None:
        lines.append(
            "_Skipped — set TWITTER_BEARER_TOKEN in .env to enable. "
            "Note: GET /1.1/trends/place requires a paid X API tier (Basic or higher)._"
        )
    else:
        lines.extend(f"- {_md_link(t['title'], t.get('link'))}" for t in data["twitter"])
    lines.append("")

    return "\n".join(lines)


def _esc(text):
    return html.escape(str(text), quote=True)


def _link_html(title, link):
    escaped_title = _esc(title)
    if not link:
        return escaped_title
    return f'<a href="{_esc(link)}" target="_blank" rel="noopener noreferrer">{escaped_title}</a>'


def render_html(data, refresh_seconds):
    def trend_row(i, item):
        chip = f'<span class="chip">~{_esc(item["traffic"])}</span>' if item.get("traffic") else ""
        return (
            f'<li><span class="rank">{i}</span>'
            f'<span class="term">{_link_html(item["title"], item.get("link"))}</span>{chip}</li>'
        )

    trends_html = "".join(
        trend_row(i, item) for i, item in enumerate(data["google_trends"], 1)
    ) or '<li class="empty">Unavailable right now.</li>'

    max_score = max((kw["score"] for kw in data["keywords"]), default=1) or 1
    keywords_html = "".join(
        f'<span class="tag" style="font-size:{0.85 + 0.9 * (kw["score"] / max_score):.2f}rem">{_esc(kw["term"])}</span>'
        for kw in data["keywords"]
    ) or '<p class="empty">Not enough headline data collected.</p>'

    outlet_cards = ""
    for name, headlines in data["outlets"].items():
        if headlines:
            items = "".join(
                f'<li>{_link_html(h["title"], h.get("link"))}</li>' for h in headlines
            )
            outlet_cards += f'<div class="card"><h3>{_esc(name)}</h3><ul>{items}</ul></div>'
        else:
            outlet_cards += (
                f'<div class="card unavailable"><h3>{_esc(name)}</h3>'
                f'<p class="empty">Unavailable</p></div>'
            )

    def optional_list_html(items, skip_message):
        if items is None:
            return f'<p class="empty">{skip_message}</p>'
        if not items:
            return '<p class="empty">No headlines returned.</p>'
        return (
            "<ul>"
            + "".join(f'<li>{_link_html(h["title"], h.get("link"))}</li>' for h in items)
            + "</ul>"
        )

    newsapi_html = optional_list_html(
        data["newsapi"], "Skipped — set NEWSAPI_KEY in .env to enable."
    )
    gnews_html = optional_list_html(data["gnews"], "Skipped — set GNEWS_KEY in .env to enable.")
    twitter_html = optional_list_html(
        data["twitter"],
        "Skipped — set TWITTER_BEARER_TOKEN in .env to enable "
        "(requires a paid X API tier).",
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh_seconds}">
<title>India Trending Dashboard</title>
<style>
  :root {{
    --bg: #f5f6f8; --card: #ffffff; --text: #1a1d23; --muted: #6b7280;
    --accent: #ff6a00; --border: #e5e7eb; --tag-bg: #fff1e6; --tag-text: #b34700;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #14161a; --card: #1e2127; --text: #e8eaed; --muted: #9aa0a8;
      --accent: #ff8a3d; --border: #2c3038; --tag-bg: #3a2617; --tag-text: #ffb27a;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, Segoe UI, Roboto, sans-serif;
    padding: 24px 16px 60px;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }}
  h1 {{ font-size: 1.5rem; margin: 0; }}
  h1 span {{ color: var(--accent); }}
  .timestamp {{ color: var(--muted); font-size: 0.85rem; }}
  h2 {{ font-size: 1.05rem; margin: 28px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px; margin-bottom: 12px;
  }}
  .card h3 {{ margin: 0 0 8px; font-size: 0.95rem; }}
  .card ul {{ margin: 0; padding-left: 18px; font-size: 0.88rem; line-height: 1.5; }}
  .card.unavailable {{ opacity: 0.55; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }}
  ol.trends {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }}
  ol.trends li {{
    display: flex; align-items: center; gap: 10px; background: var(--card);
    border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; font-size: 0.9rem;
  }}
  .rank {{ color: var(--accent); font-weight: 700; width: 1.4em; }}
  .term {{ flex: 1; }}
  .chip {{ font-size: 0.72rem; color: var(--muted); }}
  .tagcloud {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .tag {{
    background: var(--tag-bg); color: var(--tag-text); border-radius: 999px;
    padding: 4px 12px; font-weight: 600;
  }}
  .empty {{ color: var(--muted); font-size: 0.85rem; font-style: italic; margin: 0; }}
  a {{ color: inherit; text-decoration: none; }}
  a:hover {{ color: var(--accent); text-decoration: underline; }}
  section.optional ul {{ margin: 0; padding-left: 18px; font-size: 0.88rem; line-height: 1.5; }}
  footer {{ margin-top: 40px; color: var(--muted); font-size: 0.78rem; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>India <span>Trending</span> Dashboard</h1>
    <div class="timestamp">Generated {_esc(data['generated_at'])} · auto-refreshes every {refresh_seconds // 60} min</div>
  </header>

  <h2>Google Trends (India)</h2>
  <ol class="trends">{trends_html}</ol>

  <h2>Cross-source trending keywords</h2>
  <div class="tagcloud">{keywords_html}</div>

  <h2>Latest headlines by outlet</h2>
  <div class="grid">{outlet_cards}</div>

  <h2>NewsAPI top headlines (India)</h2>
  <section class="optional">{newsapi_html}</section>

  <h2>GNews top headlines (India)</h2>
  <section class="optional">{gnews_html}</section>

  <h2>X (Twitter) trending topics — India</h2>
  <section class="optional">{twitter_html}</section>

  <footer>Sources: Google Trends RSS, 8 Indian news outlet RSS feeds, optionally NewsAPI / GNews / X.
  This page rewrites itself on each script run and reloads automatically — leave the tab open.</footer>
</div>
</body>
</html>
"""


def run_once(top_n, save, refresh_seconds, open_browser, output_dir=None, history=True):
    data = collect_data(top_n)
    report = render_markdown(data)
    print(report)

    if save:
        out_dir = output_dir or REPORTS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        if history:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            (out_dir / f"report_{ts}.md").write_text(report, encoding="utf-8")

        (out_dir / "latest.md").write_text(report, encoding="utf-8")
        (out_dir / "latest.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

        html_content = render_html(data, refresh_seconds)
        (out_dir / "latest.html").write_text(html_content, encoding="utf-8")
        # index.html too, so this folder can be served directly (e.g. GitHub Pages).
        index_path = out_dir / "index.html"
        index_path.write_text(html_content, encoding="utf-8")
        print(f"\n[saved report + dashboard to {out_dir}]")

        if open_browser:
            webbrowser.open(index_path.resolve().as_uri())

    return data


def main():
    parser = argparse.ArgumentParser(description="India trending news report")
    parser.add_argument("--loop", action="store_true", help="run continuously")
    parser.add_argument("--interval", type=int, default=20, help="minutes between runs when looping")
    parser.add_argument("--top", type=int, default=10, help="items per source")
    parser.add_argument("--no-save", action="store_true", help="don't write report files, just print")
    parser.add_argument("--open", action="store_true", help="open the HTML dashboard in your browser")
    parser.add_argument(
        "--output-dir", type=str, default=None, help="write report/dashboard files here instead of ./reports"
    )
    parser.add_argument(
        "--no-history", action="store_true", help="skip writing a timestamped report_<ts>.md snapshot"
    )
    args = parser.parse_args()

    save = not args.no_save
    refresh_seconds = max(args.interval, 1) * 60
    output_dir = Path(args.output_dir) if args.output_dir else None
    history = not args.no_history

    if args.loop:
        print(f"Looping every {args.interval} minute(s). Press Ctrl+C to stop.")
        try:
            first = True
            while True:
                run_once(
                    args.top, save, refresh_seconds,
                    open_browser=args.open and first,
                    output_dir=output_dir, history=history,
                )
                first = False
                time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print("\nStopped.")
            sys.exit(0)
    else:
        run_once(
            args.top, save, refresh_seconds,
            open_browser=args.open,
            output_dir=output_dir, history=history,
        )


if __name__ == "__main__":
    main()
