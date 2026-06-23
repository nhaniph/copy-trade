"""
Backfill diagnostic — scrolls through Discord channel history
and prints every message found from watched users. No classification,
no database writes. Use this to verify how far back the scraper can reach.
"""

import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import os

load_dotenv()

DISCORD_CHANNEL_URL = os.environ["DISCORD_CHANNEL_URL"]
WATCHED_NAMES = {
    n.strip().lower()
    for n in os.environ.get("WATCHED_NAMES", "").split(",")
    if n.strip()
}
SESSION_PATH = Path(__file__).parent / ".browser_session"
SCROLL_WAIT = 2.5
MAX_EMPTY_SCROLLS = 5


def run_backfill():
    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_PATH),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        print(f"Loading channel...")
        page.goto(DISCORD_CHANNEL_URL, wait_until="networkidle", timeout=30_000)

        try:
            page.wait_for_selector('[class*="messageListItem"]', timeout=15_000)
        except PWTimeout:
            print("ERROR: Could not find messages. Run watcher.py --login first.")
            browser.close()
            return

        print("Scrolling to top of channel history... (this may take a while)\n")

        all_messages: dict[str, dict] = {}
        empty_scroll_count = 0

        while True:
            items = page.query_selector_all('[class*="messageListItem"]')

            last_author = None
            batch = {}
            for item in items:
                author_el = item.query_selector('[class*="username"]')
                author = author_el.inner_text().strip() if author_el else None
                if author:
                    last_author = author

                content_el = item.query_selector('[class*="messageContent"]')
                content = content_el.inner_text().strip() if content_el else None

                msg_id = item.get_attribute("id") or ""
                timestamp_el = item.query_selector("time")
                timestamp = timestamp_el.get_attribute("datetime") if timestamp_el else None

                if content and msg_id:
                    batch[msg_id] = {
                        "id": msg_id,
                        "author": last_author or "unknown",
                        "content": content,
                        "timestamp": timestamp,
                    }

            new_count = sum(1 for mid in batch if mid not in all_messages)
            all_messages.update(batch)

            if new_count == 0:
                empty_scroll_count += 1
                print(f"  No new messages ({empty_scroll_count}/{MAX_EMPTY_SCROLLS})")
                if empty_scroll_count >= MAX_EMPTY_SCROLLS:
                    print("Reached top of channel history.\n")
                    break
            else:
                empty_scroll_count = 0
                print(f"  Found {new_count} new messages (total so far: {len(all_messages)})")

            page.evaluate("""
                const el = document.querySelector('[class*="scroller"]');
                if (el) el.scrollTop = 0;
            """)
            time.sleep(SCROLL_WAIT)

        browser.close()

    # Filter and sort
    tom_messages = [
        m for m in all_messages.values()
        if m["author"].lower() in WATCHED_NAMES
    ]
    tom_messages.sort(key=lambda m: m.get("timestamp") or "")

    print(f"Total messages scraped: {len(all_messages)}")
    print(f"Messages from {WATCHED_NAMES}: {len(tom_messages)}\n")
    print("=" * 60)

    for msg in tom_messages:
        ts = (msg.get("timestamp") or "")[:10]
        print(f"[{ts}] {msg['author']}: {msg['content']}")
        print()


if __name__ == "__main__":
    run_backfill()
