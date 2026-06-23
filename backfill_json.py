"""
Backfill from DiscordChatExporter JSON — processes all messages from Tom,
classifies them with Claude, and loads trade-relevant ones into Supabase.
Safe to re-run — duplicate message IDs are skipped.
"""

import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent / "bot"))
from classifier import classify_message
from database import insert_signal

JSON_FILE = Path(__file__).parent / "TR-VIP-JSON.json"
AUTHOR_NAME = "tr16"
AUTHOR_NICKNAME = "Tom"


def is_tom(author: dict) -> bool:
    return author.get("name") == AUTHOR_NAME or author.get("nickname") == AUTHOR_NICKNAME


def run_backfill():
    with open(JSON_FILE, encoding="utf-8") as f:
        data = json.load(f)

    all_messages = data["messages"]
    tom_messages = [m for m in all_messages if is_tom(m["author"])]

    print(f"Total messages in export: {len(all_messages)}")
    print(f"Messages from Tom: {len(tom_messages)}")
    print(f"Date range: {tom_messages[0]['timestamp'][:10]} to {tom_messages[-1]['timestamp'][:10]}")
    print(f"\nClassifying with Claude...\n")

    signals_found = 0
    skipped_dupe = 0
    not_signal = 0

    for i, msg in enumerate(tom_messages, 1):
        content = msg["content"].strip()
        msg_id = msg["id"]
        timestamp = msg["timestamp"]

        if not content:
            continue

        print(f"[{i}/{len(tom_messages)}] {timestamp[:10]} — {content[:100]}{'...' if len(content) > 100 else ''}")

        result = classify_message(content)

        if result.get("is_signal"):
            signals_found += 1
            status = result.get("status", "idea")
            pair = result.get("pair") or "?"
            direction = result.get("direction") or "?"
            print(f"  → {status.upper()} | {direction} {pair}")

            try:
                insert_signal(
                    discord_message_id=msg_id,
                    author=AUTHOR_NICKNAME,
                    raw_message=content,
                    signal=result,
                )
                print(f"  → Saved to Supabase")
            except Exception as e:
                if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                    print(f"  → Already in DB, skipping")
                    skipped_dupe += 1
                else:
                    print(f"  → DB error: {e}")
        else:
            not_signal += 1
            print(f"  → Not trade-related")

        # Small delay to avoid rate limiting Claude API
        time.sleep(0.3)

    print(f"\n{'='*50}")
    print(f"Done.")
    print(f"  Trade-related signals found: {signals_found}")
    print(f"  Not trade-related: {not_signal}")
    print(f"  Already in DB (skipped): {skipped_dupe}")


if __name__ == "__main__":
    run_backfill()
