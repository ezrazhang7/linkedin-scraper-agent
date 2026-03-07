"""
LinkedIn Saved Posts AI Agent
─────────────────────────────
Uses Playwright + Claude vision to scroll through your saved posts,
extract everything, and dump clean JSON — just like Manus AI.

SETUP:
  pip install playwright anthropic python-dotenv
  playwright install chromium

RUN:
  python agent.py
"""

import asyncio
import base64
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from anthropic import Anthropic
from playwright.async_api import async_playwright

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # or hardcode temporarily
MODEL = "claude-opus-4-5"
LOOKBACK_DAYS = 30          # stop scrolling past posts older than this
MAX_SCROLL_STEPS = 120      # safety cap
OUTPUT_FILE = f"linkedin_saved_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Screenshot helper ─────────────────────────────────────────────────────────
async def screenshot_b64(page) -> str:
    png = await page.screenshot(full_page=False)
    return base64.standard_b64encode(png).decode()

# ── Claude vision call ────────────────────────────────────────────────────────
def ask_claude_vision(screenshot_b64: str, prompt: str) -> str:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return resp.content[0].text.strip()

# ── Extract posts from current DOM via JS ─────────────────────────────────────
EXTRACT_JS = """
() => {
  const posts = [];
  const selectors = [
    '.scaffold-finite-scroll__content .occludable-update',
    '.feed-shared-update-v2',
    '[data-urn*="activity"]',
  ];

  let containers = [];
  for (const sel of selectors) {
    const els = [...document.querySelectorAll(sel)];
    if (els.length > 0) { containers = els; break; }
  }

  // dedupe
  containers = [...new Set(containers)];

  containers.forEach((el, i) => {
    try {
      const textEl = el.querySelector('.feed-shared-text, .update-components-text, [class*="commentary"]');
      const text = textEl ? textEl.innerText.trim() : '';

      const authorEl = el.querySelector('.update-components-actor__name, .feed-shared-actor__name, [class*="actor__name"]');
      const author = authorEl ? authorEl.innerText.trim() : '';

      const timeEl = el.querySelector('time, [class*="timestamp"], .feed-shared-actor__sub-description');
      const dateRaw = timeEl
        ? (timeEl.getAttribute('datetime') || timeEl.innerText.trim())
        : '';

      const linkEl = el.querySelector("a[href*='/posts/'], a[href*='/feed/update/']");
      const postUrl = linkEl ? linkEl.href : '';

      const links = [...el.querySelectorAll('a[href]')]
        .map(a => ({ text: a.innerText.trim().slice(0, 120), url: a.href }))
        .filter(l => l.url && !l.url.includes('javascript:') && !l.url.includes('linkedin.com/in/'))
        .filter((l, idx, arr) => arr.findIndex(x => x.url === l.url) === idx);

      const articleTitle = (el.querySelector('.feed-shared-article__title, [class*="article"] [class*="title"]') || {}).innerText?.trim() || '';

      // grab the position (top of element) to help detect how far we've scrolled
      const rect = el.getBoundingClientRect();
      const absTop = rect.top + window.scrollY;

      posts.push({ index: i, author, dateRaw, postUrl, text: text.slice(0, 1000), articleTitle, links, absTop });
    } catch(e) {}
  });

  return posts;
}
"""

# ── Parse fuzzy LinkedIn dates ────────────────────────────────────────────────
def parse_linkedin_date(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip().lower()

    # ISO datetime
    try:
        return datetime.fromisoformat(raw.replace("z", "+00:00").split("+")[0])
    except Exception:
        pass

    now = datetime.now()

    m = re.search(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s*ago", raw)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        deltas = {
            "minute": timedelta(minutes=n),
            "hour": timedelta(hours=n),
            "day": timedelta(days=n),
            "week": timedelta(weeks=n),
            "month": timedelta(days=n * 30),
            "year": timedelta(days=n * 365),
        }
        return now - deltas.get(unit, timedelta(0))

    # "Jan 5", "March 2023", etc.
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d", "%B %d", "%b %Y", "%B %Y"):
        try:
            d = datetime.strptime(raw, fmt)
            if d.year == 1900:
                d = d.replace(year=now.year)
            return d
        except Exception:
            pass

    return None

# ── Main agent loop ───────────────────────────────────────────────────────────
async def run():
    print("\n🤖  LinkedIn Saved Posts Agent")
    print("=" * 44)

    if not ANTHROPIC_API_KEY:
        print("❌  Set ANTHROPIC_API_KEY env var first.")
        sys.exit(1)

    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    print(f"📅  Collecting posts from the last {LOOKBACK_DAYS} days (since {cutoff.strftime('%b %d, %Y')})")

    async with async_playwright() as pw:
        # Launch visible browser so you can log in
        browser = await pw.chromium.launch(headless=False, slow_mo=50)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()

        # ── Step 1: navigate and wait for login ──────────────────────────────
        print("\n🌐  Opening LinkedIn saved posts...")
        await page.goto("https://www.linkedin.com/my-items/saved-posts/", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Check if we need to log in
        ss = await screenshot_b64(page)
        login_check = ask_claude_vision(
            ss,
            "Is this a LinkedIn login/auth page, or are we already viewing saved posts? "
            "Reply with exactly 'LOGIN_NEEDED' or 'LOGGED_IN'."
        )

        if "LOGIN_NEEDED" in login_check:
            print("\n🔐  Please log in to LinkedIn in the browser window.")
            print("    Press ENTER here when you're on the Saved Posts page...")
            input()
            await page.goto("https://www.linkedin.com/my-items/saved-posts/", wait_until="domcontentloaded")
            await asyncio.sleep(3)

        print("✅  Logged in. Starting extraction...\n")

        # ── Step 2: scroll + extract loop ────────────────────────────────────
        all_posts: dict[str, dict] = {}   # keyed by postUrl or index
        scroll_step = 0
        reached_cutoff = False
        last_post_count = 0
        stale_count = 0

        while scroll_step < MAX_SCROLL_STEPS and not reached_cutoff:
            scroll_step += 1

            # Extract current DOM
            posts = await page.evaluate(EXTRACT_JS)

            # Merge into all_posts (avoid duplicates)
            for p in posts:
                key = p.get("postUrl") or f"idx_{p['index']}"
                if key not in all_posts:
                    all_posts[key] = {**p, "scrapedAt": datetime.now().isoformat()}

            new_total = len(all_posts)
            print(f"  Step {scroll_step:03d} | {new_total} unique posts collected", end="\r")

            # Check if newest posts are older than cutoff
            dated = [p for p in all_posts.values() if p.get("dateRaw")]
            parsed_dates = [(p, parse_linkedin_date(p["dateRaw"])) for p in dated]
            valid = [(p, d) for p, d in parsed_dates if d]

            if valid:
                oldest_visible = min(d for _, d in valid)
                if oldest_visible < cutoff:
                    print(f"\n📅  Reached posts from {oldest_visible.strftime('%b %d, %Y')} — past our cutoff, stopping.")
                    reached_cutoff = True
                    break

            # Stale check (no new posts after scrolling)
            if new_total == last_post_count:
                stale_count += 1
                if stale_count >= 6:
                    print("\n⚠️   No new posts loading. Assuming we've hit the end.")
                    break
            else:
                stale_count = 0
            last_post_count = new_total

            # Scroll down
            await page.evaluate("window.scrollBy(0, window.innerHeight * 0.85)")
            await asyncio.sleep(1.5)

            # Every 15 steps, use Claude vision to confirm we're still on track
            if scroll_step % 15 == 0:
                ss = await screenshot_b64(page)
                assessment = ask_claude_vision(
                    ss,
                    "You are helping scrape LinkedIn saved posts. Look at this screenshot. "
                    "Are we still scrolling through the saved posts feed? Is there a 'no more posts' message? "
                    "Is anything broken (CAPTCHA, login redirect, error)? "
                    "Reply in one sentence starting with STATUS: OK | END_OF_FEED | ERROR."
                )
                print(f"\n  🧠 Claude says: {assessment}")
                if "END_OF_FEED" in assessment or "ERROR" in assessment:
                    break

        print(f"\n\n✅  Scroll complete. {len(all_posts)} raw posts collected.")

        await browser.close()

    # ── Step 3: filter to cutoff window ──────────────────────────────────────
    posts_list = list(all_posts.values())
    filtered = []
    undated = []
    for p in posts_list:
        d = parse_linkedin_date(p.get("dateRaw", ""))
        if d:
            p["parsedDate"] = d.isoformat()
            if d >= cutoff:
                filtered.append(p)
        else:
            undated.append(p)   # include undated ones since we can't exclude confidently

    # Include undated posts (can't tell if they're old)
    combined = filtered + undated
    print(f"📊  {len(filtered)} posts within {LOOKBACK_DAYS} days + {len(undated)} undated posts")

    # ── Step 4: AI clean + enrich ─────────────────────────────────────────────
    print("\n🧹  Cleaning + enriching with Claude...")
    cleaned = await clean_posts(combined)

    # ── Step 5: Save ──────────────────────────────────────────────────────────
    Path(OUTPUT_FILE).write_text(json.dumps(cleaned, indent=2, ensure_ascii=False))
    print(f"\n💾  Saved to {OUTPUT_FILE}")
    print(f"    {len(cleaned)} posts ready. Open linkedin_viewer.jsx to browse them!\n")

    return cleaned


# ── AI cleaner ────────────────────────────────────────────────────────────────
async def clean_posts(posts: list[dict]) -> list[dict]:
    """
    Sends posts in batches to Claude for cleaning:
    - Normalise dates
    - Extract/clean external URLs (strip LinkedIn tracking)
    - Tag post type (job opportunity, article, tool, event, other)
    - Pull out a one-line summary
    """
    BATCH = 15
    cleaned_all = []

    for i in range(0, len(posts), BATCH):
        batch = posts[i: i + BATCH]
        batch_json = json.dumps(
            [{
                "index": p.get("index"),
                "author": p.get("author"),
                "dateRaw": p.get("dateRaw"),
                "text": p.get("text", "")[:500],
                "articleTitle": p.get("articleTitle"),
                "links": [l["url"] for l in p.get("links", [])[:8]],
                "postUrl": p.get("postUrl"),
            } for p in batch],
            indent=2
        )

        prompt = f"""You are cleaning LinkedIn saved post data. For each post, return a JSON array with one object per post containing:
- index: same as input
- author: cleaned name
- date: best ISO date guess from dateRaw (or null)
- summary: one punchy sentence summarising what this post is about
- category: one of [job_opportunity, article, tool, event, person, other]
- externalLinks: array of URLs that go outside LinkedIn (strip tracking params, keep readable)
- postUrl: same as input

Return ONLY valid JSON array, no markdown, no explanation.

Input:
{batch_json}"""

        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()

        # Strip markdown fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("```").strip()

        try:
            batch_cleaned = json.loads(raw)
            # Merge back original links list
            for item in batch_cleaned:
                orig = next((p for p in batch if p.get("index") == item.get("index")), {})
                item["allLinks"] = orig.get("links", [])
                item["imageUrl"] = orig.get("imageUrl", "")
            cleaned_all.extend(batch_cleaned)
        except json.JSONDecodeError as e:
            print(f"  ⚠️  JSON parse error on batch {i//BATCH + 1}: {e} — keeping raw")
            cleaned_all.extend(batch)

        print(f"  Cleaned batch {i//BATCH + 1}/{(len(posts)-1)//BATCH + 1}", end="\r")

    print()
    return cleaned_all


if __name__ == "__main__":
    asyncio.run(run())
