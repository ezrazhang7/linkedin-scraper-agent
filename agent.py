"""
LinkedIn Saved Posts Agent — v2
────────────────────────────────
Strategy:
  1. Open /my-items/saved-posts/
  2. Find every post link on the page via JS + Claude vision fallback
  3. Open each post URL in a new tab, extract content, close tab
  4. Scroll saved-posts list, repeat until posts > 30 days old
  5. Claude cleans + categorises everything at the end

SETUP:
  pip install playwright anthropic
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
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL             = "claude-opus-4-5"
LOOKBACK_DAYS     = 30
MAX_POSTS         = 100       # hard cap so you don't accidentally scrape forever
OUTPUT_FILE       = f"linkedin_saved_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
SESSION_FILE      = "linkedin_session.json"   # persisted login — delete to force re-login
PARALLEL_TABS     = 10                        # simultaneous post tabs

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Helpers ───────────────────────────────────────────────────────────────────
def b64(png: bytes) -> str:
    return base64.standard_b64encode(png).decode()

def claude_vision(img_b64: str, prompt: str) -> str:
    r = client.messages.create(
        model=MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
            {"type": "text", "text": prompt},
        ]}],
    )
    return r.content[0].text.strip()

async def safe_goto(page, url: str, timeout=20000):
    """Navigate without crashing on LinkedIn self-redirects."""
    try:
        await page.goto(url, wait_until="load", timeout=timeout)
    except PWTimeout:
        pass
    except Exception as e:
        if "interrupted by another navigation" in str(e):
            pass
        else:
            raise
    await asyncio.sleep(2)

# ── JS: collect all post links visible on saved-posts page ───────────────────
COLLECT_LINKS_JS = """
() => {
    const results = [];
    const seen = new Set();

    const candidates = [
        ...document.querySelectorAll('a[href*="/feed/update/"]'),
        ...document.querySelectorAll('a[href*="/posts/"]'),
    ];

    for (const a of candidates) {
        const href = a.href || '';
        if (!href || seen.has(href)) continue;

        // Skip nav/sidebar links
        if (href.includes('/mynetwork') || href.includes('/jobs') ||
            href.includes('/messaging') || href.includes('/notifications')) continue;

        seen.add(href);

        // Try to find a nearby timestamp
        const card = a.closest('[data-urn], [class*="occludable"], [class*="entity-result"], [class*="saved"]') || a.parentElement;
        const timeEl = card ? card.querySelector('time, [class*="timestamp"], [class*="time-ago"]') : null;
        const dateRaw = timeEl ? (timeEl.getAttribute('datetime') || timeEl.innerText.trim()) : '';

        const authorEl = card ? card.querySelector('[class*="actor__name"], [class*="author"], strong') : null;
        const author = authorEl ? authorEl.innerText.trim() : '';

        results.push({ url: href, dateRaw, author });
    }
    return results;
}
"""

# ── JS: extract content from an open post page ───────────────────────────────
EXTRACT_POST_JS = """
() => {
    const textEl = document.querySelector(
        '.feed-shared-text, .update-components-text, [class*="commentary"], ' +
        '.feed-shared-update-v2__description, [class*="attributed-text"]'
    );
    const text = textEl ? textEl.innerText.trim() : document.body.innerText.slice(0, 1500);

    const authorEl = document.querySelector(
        '.update-components-actor__name, .feed-shared-actor__name, ' +
        '[class*="actor__name"], h1[class*="author"]'
    );
    const author = authorEl ? authorEl.innerText.trim() : '';

    const timeEl = document.querySelector('time, [class*="timestamp"]');
    const dateRaw = timeEl ? (timeEl.getAttribute('datetime') || timeEl.innerText.trim()) : '';

    const articleTitle = (
        document.querySelector('.feed-shared-article__title, [class*="article-title"], [class*="article__title"]') || {}
    ).innerText?.trim() || '';

    const links = [...document.querySelectorAll('a[href]')]
        .map(a => ({ text: a.innerText.trim().slice(0, 120), url: a.href }))
        .filter(l =>
            l.url &&
            !l.url.startsWith('javascript') &&
            !l.url.includes('linkedin.com/in/') &&
            !l.url.includes('linkedin.com/company/') &&
            !l.url.includes('/mynetwork') &&
            !l.url.includes('/jobs') &&
            !l.url.includes('/messaging')
        )
        .filter((l, i, arr) => arr.findIndex(x => x.url === l.url) === i)
        .slice(0, 20);

    return { text, author, dateRaw, articleTitle, links };
}
"""

# ── Parse fuzzy LinkedIn dates ────────────────────────────────────────────────
def parse_date(raw: str):
    if not raw:
        return None
    raw = raw.strip().lower()
    try:
        return datetime.fromisoformat(raw.replace("z", "").split("+")[0])
    except Exception:
        pass
    now = datetime.now()
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s*ago", raw)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now - {"minute": timedelta(minutes=n), "hour": timedelta(hours=n),
                      "day": timedelta(days=n), "week": timedelta(weeks=n),
                      "month": timedelta(days=n*30), "year": timedelta(days=n*365)}[unit]
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d", "%B %d"):
        try:
            d = datetime.strptime(raw, fmt)
            return d.replace(year=now.year) if d.year == 1900 else d
        except Exception:
            pass
    return None

# ── Main ──────────────────────────────────────────────────────────────────────
async def run():
    print("\n🤖  LinkedIn Saved Posts Agent v2")
    print("=" * 44)
    if not ANTHROPIC_API_KEY:
        print("❌  Set ANTHROPIC_API_KEY env var first.")
        sys.exit(1)

    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    print(f"📅  Collecting posts since {cutoff.strftime('%b %d, %Y')}\n")

    async with async_playwright() as pw:
        # ── Session cache: reuse cookies so login only happens once ────────
        session_path = Path(SESSION_FILE)
        ctx_kwargs   = {"viewport": {"width": 1280, "height": 900}}
        if session_path.exists():
            ctx_kwargs["storage_state"] = SESSION_FILE
            print(f"🔑  Loaded saved session from {SESSION_FILE}")

        browser = await pw.chromium.launch(headless=False, slow_mo=30)
        ctx     = await browser.new_context(**ctx_kwargs)
        page    = await ctx.new_page()

        # ── Login (only if no cached session or session expired) ────────────
        print("🌐  Navigating to LinkedIn saved posts...")
        await safe_goto(page, "https://www.linkedin.com/my-items/saved-posts/")

        ss = await page.screenshot()
        status = claude_vision(b64(ss),
            "Is this a LinkedIn login page or are we already viewing saved posts? "
            "Reply exactly: LOGIN_NEEDED or LOGGED_IN")

        if "LOGIN_NEEDED" in status:
            print("🔐  Please log in inside the browser window.")
            print("    When you can see your saved posts, press ENTER here...")
            input()
            await safe_goto(page, "https://www.linkedin.com/my-items/saved-posts/")
            # Save session so next run skips login entirely
            await ctx.storage_state(path=SESSION_FILE)
            print(f"💾  Session saved → {SESSION_FILE} (won't ask again)")
        else:
            # Refresh the cache in case tokens rotated
            await ctx.storage_state(path=SESSION_FILE)
            print(f"✅  Session valid. Refreshed {SESSION_FILE}")

        print("✅  On saved posts page. Starting...\n")
        await asyncio.sleep(2)

        # ── Collect + open each post ───────────────────────────────────────
        all_posts   = []
        seen_urls   = set()
        stop        = False
        scroll_pass = 0
        empty_passes = 0

        while not stop and len(all_posts) < MAX_POSTS:
            scroll_pass += 1

            links = await page.evaluate(COLLECT_LINKS_JS)
            new_links = [l for l in links if l["url"] not in seen_urls]
            print(f"📋  Pass {scroll_pass}: {len(new_links)} new links visible ({len(all_posts)} extracted so far)")

            if not new_links:
                empty_passes += 1
                if empty_passes >= 4:
                    print("⚠️   No more new links after scrolling. Done.")
                    break
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(2.5)
                continue
            else:
                empty_passes = 0

            # ── Filter links: skip already-seen and past-cutoff cards ───────
            to_fetch = []
            for link_info in new_links:
                if len(all_posts) + len(to_fetch) >= MAX_POSTS:
                    stop = True
                    break
                url = link_info["url"]
                seen_urls.add(url)
                card_date = parse_date(link_info.get("dateRaw", ""))
                if card_date and card_date < cutoff:
                    print(f"  ⏭️   Card date '{link_info.get('dateRaw')}' past cutoff — stopping")
                    stop = True
                    break
                to_fetch.append(link_info)

            # ── Parallel fetch: PARALLEL_TABS tabs at a time ─────────────
            async def fetch_one(link_info, idx):
                url = link_info["url"]
                post_page = await ctx.new_page()
                try:
                    await safe_goto(post_page, url, timeout=15000)
                    data = await post_page.evaluate(EXTRACT_POST_JS)
                    if not data["author"] and link_info.get("author"):
                        data["author"] = link_info["author"]
                    if not data["dateRaw"] and link_info.get("dateRaw"):
                        data["dateRaw"] = link_info["dateRaw"]
                    parsed_date = parse_date(data["dateRaw"])
                    if parsed_date and parsed_date < cutoff:
                        return None   # signal: past cutoff
                    result = {
                        "index":        idx,
                        "postUrl":      url,
                        "author":       data["author"],
                        "dateRaw":      data["dateRaw"],
                        "parsedDate":   parsed_date.isoformat() if parsed_date else None,
                        "text":         data["text"][:1000],
                        "articleTitle": data["articleTitle"],
                        "links":        data["links"],
                        "scrapedAt":    datetime.now().isoformat(),
                    }
                    print(f"  ✅  [{idx}] {data['author'] or 'unknown'} · {data['dateRaw'] or 'no date'} · {len(data['links'])} links")
                    return result
                except Exception as e:
                    print(f"  ❌  [{idx}] {url[:55]}: {e}")
                    return None
                finally:
                    await post_page.close()

            for batch_start in range(0, len(to_fetch), PARALLEL_TABS):
                batch = to_fetch[batch_start : batch_start + PARALLEL_TABS]
                base_idx = len(all_posts) + 1
                print(f"  🚀  Launching {len(batch)} tabs in parallel...")
                results = await asyncio.gather(*[
                    fetch_one(link_info, base_idx + i)
                    for i, link_info in enumerate(batch)
                ])
                for r in results:
                    if r is None:
                        stop = True
                    else:
                        all_posts.append(r)
                if stop:
                    break
                await page.bring_to_front()
                await asyncio.sleep(0.5)

            # Scroll saved-posts list to load more cards
            if not stop:
                prev_h = await page.evaluate("document.body.scrollHeight")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2.5)
                new_h = await page.evaluate("document.body.scrollHeight")
                if new_h == prev_h:
                    print("📄  Reached end of saved posts list.")
                    break

        await browser.close()

    print(f"\n✅  Done. {len(all_posts)} posts collected.")

    # Cache raw posts immediately — so a cleaning crash never loses your scrape
    raw_cache = OUTPUT_FILE.replace(".json", "_raw.json")
    Path(raw_cache).write_text(
        json.dumps(all_posts, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"💾  Raw cache → {raw_cache}")

    if all_posts:
        print("🧹  Cleaning + categorising with Claude...")
        all_posts = await clean_posts(all_posts)

    Path(OUTPUT_FILE).write_text(
        json.dumps(all_posts, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"💾  Cleaned → {OUTPUT_FILE}")
    print(f"    Load into linkedin_viewer.jsx to browse.\n")
    return all_posts


# ── AI cleaner ────────────────────────────────────────────────────────────────
async def clean_posts(posts: list) -> list:
    BATCH = 10
    out   = []
    for i in range(0, len(posts), BATCH):
        batch = posts[i:i+BATCH]
        payload = json.dumps([{
            "index":        p["index"],
            "author":       p.get("author"),
            "dateRaw":      p.get("dateRaw"),
            "text":         p.get("text","")[:400],
            "articleTitle": p.get("articleTitle"),
            "links":        [l["url"] for l in p.get("links",[])[:6]],
            "postUrl":      p.get("postUrl"),
        } for p in batch], indent=2)

        r = client.messages.create(
            model=MODEL, max_tokens=3000,
            messages=[{"role": "user", "content": f"""Clean these LinkedIn posts. Return a JSON array — one object per post — with:
- index, author, postUrl  (unchanged from input)
- date: ISO date string (best guess from dateRaw, or null)
- summary: one punchy sentence about what this post is about
- category: job_opportunity | article | tool | event | person | other
- externalLinks: clean URLs that go outside LinkedIn (strip tracking params)

Return ONLY valid JSON, no markdown fences, no explanation.

{payload}"""}],
        )
        raw = r.content[0].text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("```").strip()
        try:
            cleaned = json.loads(raw)
            for item in cleaned:
                orig = next((p for p in batch if p["index"] == item.get("index")), {})
                item["allLinks"]  = orig.get("links", [])
                item["text"]      = orig.get("text", "")
                item["scrapedAt"] = orig.get("scrapedAt", "")
            out.extend(cleaned)
        except Exception as e:
            print(f"  ⚠️  Parse error batch {i//BATCH+1}: {e} — keeping raw")
            out.extend(batch)
        print(f"  Cleaned {min(i+BATCH, len(posts))}/{len(posts)} posts", end="\r")
    print()
    return out



# ── Re-clean from cache (skip scraping) ──────────────────────────────────────
async def clean_from_cache(cache_file: str):
    """
    Run just the cleaning step on an existing _raw.json file.
    Usage: edit the bottom of this file to call clean_from_cache("yourfile_raw.json")
    """
    print(f"📂  Loading cache: {cache_file}")
    posts = json.loads(Path(cache_file).read_text(encoding="utf-8"))
    print(f"   {len(posts)} posts loaded.")
    cleaned = await clean_posts(posts)
    out = cache_file.replace("_raw.json", "_cleaned.json")
    Path(out).write_text(json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"💾  Saved → {out}")
    return cleaned


if __name__ == "__main__":
    asyncio.run(run())