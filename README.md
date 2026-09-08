# Trending News — India

A dashboard of trending news/search signals for the Indian context, built
from Google Trends, 8 major Indian news outlets' RSS feeds, and (optionally)
NewsAPI / GNews / X. Published automatically to **GitHub Pages** via a
scheduled GitHub Actions workflow — no server to maintain.

Live dashboard (after Pages is enabled — see below):
`https://sudheendraprasad-hue.github.io/Trending-News/`

## How it works

1. [`.github/workflows/update-dashboard.yml`](.github/workflows/update-dashboard.yml)
   runs on a schedule (every ~30 min) via GitHub Actions.
2. It runs [`trending_india.py`](trending_india.py), which fetches all
   sources and writes `docs/index.html` (the dashboard), `docs/latest.md`,
   and `docs/latest.json`.
3. The workflow commits and pushes `docs/` back to the repo.
4. GitHub Pages serves whatever is in `docs/` on the `main` branch.
5. The dashboard page itself has a `<meta http-equiv="refresh">` tag, so an
   open browser tab reloads on the same cadence and always shows the latest
   published version.

## One-time setup

### 1. Enable GitHub Pages
In the repo on GitHub: **Settings → Pages → Build and deployment → Source:
"Deploy from a branch" → Branch: `main`, folder: `/docs` → Save.**
(Needs at least one commit with a `docs/` folder to exist first — see below.)

### 2. (Optional) Add API keys as repository secrets
Only needed if you want the NewsAPI / GNews / X sections populated.
**Settings → Secrets and variables → Actions → New repository secret:**
- `NEWSAPI_KEY` — from [newsapi.org](https://newsapi.org)
- `GNEWS_KEY` — from [gnews.io](https://gnews.io)
- `TWITTER_BEARER_TOKEN` — needs a paid X API tier (Basic+); skip otherwise

Without these, those three sections just show "skipped" — everything else
still works.

### 3. Trigger the first run
Either wait for the next scheduled run, or trigger it manually:
**Actions tab → "Update trending dashboard" → Run workflow.**

## Running locally

```bash
python -m pip install -r requirements.txt
python trending_india.py --open              # generates ./reports and opens it
```

Useful flags:
```bash
python trending_india.py --top 15                       # more headlines per source
python trending_india.py --loop --interval 20            # keep re-running locally
python trending_india.py --output-dir docs --no-history  # what the GitHub Action runs
```

Copy `.env.example` to `.env` to add API keys for local runs (not needed —
and not committed — for the GitHub Pages deployment, which uses repo
secrets instead).

## Adjusting the refresh cadence

Edit the `cron` line in
[`.github/workflows/update-dashboard.yml`](.github/workflows/update-dashboard.yml).
GitHub's scheduler has a practical floor around 5 minutes and can run a few
minutes late under load — treat any interval as "roughly," not exact.
News/search trends genuinely don't move at 1-minute resolution, so 15-30
minutes is already close to real-time here. NewsAPI/GNews free tiers also
cap at 100 requests/day, which limits how short the interval can usefully go
if those are enabled.

## Known limitations

- "Trending" = Google's public daily-trends RSS + what's currently on each
  outlet's top-news RSS feed — not a live, second-by-second signal.
- The cross-source keyword list is a simple frequency count, not NLP entity
  extraction.
- X/Twitter trends require a paid API tier; without `TWITTER_BEARER_TOKEN`
  that section is skipped.
