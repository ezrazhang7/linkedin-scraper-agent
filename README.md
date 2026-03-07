# LinkedIn Saved Posts Agent

An AI agent (Playwright + Claude vision) that opens your browser, scrolls your LinkedIn saved posts, extracts everything from the last 30 days, and cleans it into structured JSON.

## Setup (one-time)

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...
# (or paste it directly into agent.py line 18)
```

## Run

```bash
python agent.py
```

**What happens:**
1. A real Chrome window opens and navigates to your LinkedIn saved posts
2. If you're not logged in, it pauses and waits for you to log in, then press Enter
3. The agent scrolls automatically, extracting posts as it goes
4. Every 15 scroll steps, Claude looks at a screenshot to check everything's OK
5. Once it hits posts older than 30 days (or runs out), it stops
6. Claude cleans each post in batches: normalises dates, tags categories, strips tracking URLs
7. Saves a `linkedin_saved_YYYYMMDD_HHMMSS.json` file in the same folder

## Config (top of agent.py)

| Variable | Default | Description |
|---|---|---|
| `LOOKBACK_DAYS` | 30 | How far back to scrape |
| `MAX_SCROLL_STEPS` | 120 | Safety cap on scroll iterations |
| `MODEL` | claude-opus-4-5 | Claude model for vision + cleaning |

## Output format

Each post in the JSON looks like:

```json
{
  "index": 3,
  "author": "Jane Smith",
  "date": "2025-02-15T00:00:00",
  "summary": "Tool for auto-generating cold outreach emails using GPT-4",
  "category": "tool",
  "externalLinks": ["https://example.com/tool"],
  "allLinks": [{ "text": "Try it here", "url": "..." }],
  "postUrl": "https://linkedin.com/feed/update/..."
}
```

## View the results

Load the JSON into `linkedin_viewer.jsx` (open it as an artifact in Claude) for a searchable, filterable UI with proper new-tab links.

## Troubleshooting

- **No posts extracted**: LinkedIn may have updated their CSS class names. Open an issue — the selectors in `EXTRACT_JS` need updating.
- **CAPTCHA**: The agent will detect it via the Claude vision check every 15 steps and stop. Just re-run after a few minutes.
- **Slow**: Normal — `slow_mo=50` makes actions more human-like to avoid bot detection.
