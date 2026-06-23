"""
Discord web watcher — uses Playwright with your existing browser session.
Polls a Discord channel URL and passes new messages from watched users
through the LLM classifier → Supabase + Telegram.

Run once with --login to save your Discord session, then run normally.
"""

import os
import sys
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent / "bot"))
from classifier import classify_message
from database import insert_signal
from telegram import send_signal_alert

DISCORD_CHANNEL_URL = os.environ["DISCORD_CHANNEL_URL"]

# Comma-separated display names or usernames to watch (e.g. "tr16,tr16_alt")
WATCHED_NAMES = {
    n.strip().lower()
    for n in os.environ.get("WATCHED_NAMES", "").split(",")
    if n.strip()
}

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
SESSION_PATH = Path(__file__).parent / ".browser_session"


def get_visible_messages(page) -> list[dict]:
    """Scrape all visible message rows from the Discord channel."""
    messages = []
    items = page.query_selector_all('[class*="messageListItem"]')
    for item in items:
        # Author name — present on first message in a group, absent on continuations
        author_el = item.query_selector('[class*="username"]')
        author = author_el.inner_text().strip() if author_el else None

        # Message content
        content_el = item.query_selector('[class*="messageContent"]')
        content = content_el.inner_text().strip() if content_el else None

        # Message ID from the article or li data attribute
        msg_id = item.get_attribute("id") or ""

        if content:
            messages.append({
                "id": msg_id,
                "author": author,  # None for continuation messages
                "content": content,
            })

    # Fill in author for continuation messages (inherit from last known author)
    last_author = None
    resolved = []
    for m in messages:
        if m["author"]:
            last_author = m["author"]
        resolved.append({**m, "author": last_author or "unknown"})

    return resolved


def run_watcher(login_mode: bool = False):
    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_PATH),
            headless=not login_mode,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        if login_mode:
            print("Opening Discord — log in manually, then press Enter here to save session.")
            page.goto("https://discord.com/login")
            input("Press Enter after you've logged in fully: ")
            browser.close()
            print("Session saved. Run without --login to start watching.")
            return

        print(f"Navigating to channel…")
        page.goto(DISCORD_CHANNEL_URL, wait_until="networkidle", timeout=30_000)

        # Wait for messages to load
        try:
            page.wait_for_selector('[class*="messageListItem"]', timeout=15_000)
        except PWTimeout:
            print("ERROR: Could not find messages. Are you logged in? Run with --login first.")
            browser.close()
            return

        print(f"Watching channel. Poll interval: {POLL_INTERVAL}s")
        print(f"Filtering for: {WATCHED_NAMES or 'ALL users'}\n")

        seen_ids: set[str] = set()

        # Seed seen_ids with whatever's already on screen so we don't re-process history
        for msg in get_visible_messages(page):
            if msg["id"]:
                seen_ids.add(msg["id"])
        print(f"Seeded {len(seen_ids)} existing messages — watching for new ones…\n")

        while True:
            time.sleep(POLL_INTERVAL)

            try:
                messages = get_visible_messages(page)
            except Exception as e:
                print(f"[scrape error] {e}")
                continue

            for msg in messages:
                msg_id = msg["id"]

                if msg_id in seen_ids:
                    continue
                if msg_id:
                    seen_ids.add(msg_id)

                author = msg["author"]
                content = msg["content"]

                if WATCHED_NAMES and author.lower() not in WATCHED_NAMES:
                    continue

                timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
                print(f"[{timestamp}] {author}: {content}")

                result = classify_message(content)

                if result.get("is_signal"):
                    print(f"  → SIGNAL: {result.get('direction')} {result.get('pair')}")
                    print(f"    Entry: {result.get('entry')}")
                    print(f"    Target: {result.get('target')}")
                    print(f"    Invalidation: {result.get('invalidation')}")

                    insert_signal(
                        discord_message_id=msg_id or content[:40],
                        author=author,
                        raw_message=content,
                        signal=result,
                    )
                    print("  → Logged to Supabase")

                    send_signal_alert(result, author, timestamp)
                else:
                    print("  → Not a signal")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", action="store_true", help="Open browser to log into Discord")
    args = parser.parse_args()
    run_watcher(login_mode=args.login)
