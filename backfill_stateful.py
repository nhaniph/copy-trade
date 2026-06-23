"""
Stateful backfill — processes Tom's messages in batches of 30 with NO overlap.
Instead of overlap, currently open trades are injected as context into each batch.
This prevents phantom closes and wrong-instrument exit attribution.

Usage:
  python backfill_stateful.py --run v3-stateful
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent / "bot"))
from stateful_classifier import classify_stateful
from database import get_client, find_active_trade, create_trade, update_trade_status

BATCH_SIZE = 30
JSON_FILE = Path(__file__).parent / "TR-VIP-JSON.json"
AUTHOR_NAME = "tr16"
AUTHOR_NICKNAME = "Tom"


def is_tom(author: dict) -> bool:
    return author.get("name") == AUTHOR_NAME or author.get("nickname") == AUTHOR_NICKNAME


def find_active_trade_for_run(pair: str, backtest_run: str) -> dict | None:
    if not pair:
        return None
    result = get_client().table("trades") \
        .select("*") \
        .ilike("pair", pair) \
        .in_("status", ["idea", "open"]) \
        .eq("backtest_run", backtest_run) \
        .order("opened_at", desc=True) \
        .limit(1) \
        .execute()
    return result.data[0] if result.data else None


def insert_batch_signal(discord_message_id: str, raw_message: str, timestamp: str,
                        idea: dict, msg_status: str, trade_id: str,
                        backtest_run: str) -> None:
    db = get_client()
    row = {
        "discord_message_id": discord_message_id,
        "author": AUTHOR_NICKNAME,
        "raw_message": raw_message,
        "pair": idea.get("pair"),
        "direction": idea.get("direction"),
        "entry": idea.get("entry"),
        "target": idea.get("target"),
        "invalidation": idea.get("invalidation"),
        "notes": idea.get("summary"),
        "status": msg_status,
        "trade_id": trade_id,
        "source": "backfill",
        "backtest_run": backtest_run,
        "created_at": timestamp,
    }
    try:
        db.table("signals").insert(row).execute()
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            pass
        else:
            print(f"    [DB error] {e}")


def run_backfill(backtest_run: str):
    with open(JSON_FILE, encoding="utf-8") as f:
        data = json.load(f)

    all_messages = data["messages"]
    tom_messages = [m for m in all_messages if is_tom(m["author"])]
    print(f"Backtest run: {backtest_run}")
    print(f"Total messages from Tom: {len(tom_messages)}")
    print(f"Batch size: {BATCH_SIZE}, Overlap: none (stateful mode)")
    print(f"Estimated batches: {len(tom_messages) // BATCH_SIZE + 1}\n")

    # open_trades tracks what the classifier believes is currently open
    # pair -> {direction, summary, opened_at, trade_id}
    open_trades: dict[str, dict] = {}

    processed_ids: set[str] = set()
    signals_saved = 0
    ideas_found = 0
    batch_num = 0
    i = 0

    while i < len(tom_messages):
        batch = tom_messages[i:i + BATCH_SIZE]
        batch_num += 1

        classifier_input = [
            {
                "index": j,
                "content": m["content"].strip(),
                "timestamp": m["timestamp"],
                "id": m["id"],
            }
            for j, m in enumerate(batch)
        ]

        print(f"Batch {batch_num}: messages {i+1}–{i+len(batch)} "
              f"({batch[0]['timestamp'][:10]} to {batch[-1]['timestamp'][:10]})")
        if open_trades:
            ctx = ', '.join(f"{p} {v['direction']}" for p, v in open_trades.items())
            print(f"  Open trades context: {ctx}")

        ideas = classify_stateful(classifier_input, open_trades)
        print(f"  → {len(ideas)} ideas/commentaries found")

        for idea in ideas:
            pair = idea.get("pair")
            direction = idea.get("direction")
            idea_status = idea.get("status", "idea")
            confidence = idea.get("confidence", "high")
            close_trigger = idea.get("close_trigger")
            final_r = idea.get("final_r")
            messages = idea.get("messages", [])

            if not messages:
                continue

            # Downgrade low-confidence closes to open
            if idea_status in ("closed_win", "closed_loss") and confidence == "low":
                print(f"    [DOWNGRADE] Low confidence close for {pair} → keeping as open")
                idea_status = "open"
                for m in messages:
                    if m.get("status") in ("closed_win", "closed_loss"):
                        m["status"] = "open"

            ideas_found += 1

            trade_id = None
            if idea_status != "commentary" and pair:
                existing_trade = find_active_trade_for_run(pair, backtest_run)
                if existing_trade:
                    trade_id = existing_trade["id"]
                    status_rank = {"idea": 0, "open": 1, "closed_win": 2, "closed_loss": 2, "cancelled": 2}
                    if status_rank.get(idea_status, 0) > status_rank.get(existing_trade["status"], 0):
                        r_to_save = final_r
                        if r_to_save is not None and idea_status == "closed_loss":
                            r_to_save = -abs(r_to_save)
                        update_trade_status(trade_id, idea_status, r_to_save)
                        get_client().table("trades").update({
                            "confidence": confidence,
                            "close_trigger": close_trigger,
                        }).eq("id", trade_id).execute()
                else:
                    first_msg_idx = messages[0].get("index", 0) if messages else 0
                    first_ts = batch[first_msg_idx]["timestamp"] if first_msg_idx < len(batch) else None
                    new_trade = create_trade(pair, direction, idea_status,
                                             source="backfill", backtest_run=backtest_run,
                                             opened_at=first_ts)
                    trade_id = new_trade.get("id")
                    if trade_id:
                        get_client().table("trades").update({
                            "confidence": confidence,
                            "close_trigger": close_trigger,
                        }).eq("id", trade_id).execute()
                    if idea_status in ("closed_win", "closed_loss") and trade_id:
                        r_to_save = final_r
                        if r_to_save is not None and idea_status == "closed_loss":
                            r_to_save = -abs(r_to_save)
                        update_trade_status(trade_id, idea_status, r_to_save)

            # Update in-memory open_trades state for next batch context
            if pair:
                if idea_status in ("idea", "open"):
                    open_trades[pair] = {
                        "direction": direction,
                        "summary": idea.get("summary", ""),
                        "opened_at": (batch[messages[0].get("index", 0)]["timestamp"]
                                      if messages and messages[0].get("index", 0) < len(batch) else ""),
                        "trade_id": trade_id,
                    }
                elif idea_status in ("closed_win", "closed_loss", "cancelled"):
                    open_trades.pop(pair, None)

            for msg in messages:
                idx = msg.get("index", 0)
                if idx >= len(batch):
                    continue

                original = batch[idx]
                msg_id = original["id"]

                if msg_id in processed_ids:
                    continue
                processed_ids.add(msg_id)

                msg_status = msg.get("status", idea_status)
                timestamp = original["timestamp"]
                content = original["content"].strip()

                insert_batch_signal(
                    discord_message_id=f"{backtest_run}_{msg_id}",
                    raw_message=content,
                    timestamp=timestamp,
                    idea=idea,
                    msg_status=msg_status,
                    trade_id=trade_id,
                    backtest_run=backtest_run,
                )
                signals_saved += 1
                trigger_note = f" [trigger: {close_trigger[:40]}]" if close_trigger and msg_status in ("closed_win", "closed_loss") else ""
                r_note = f" [{final_r:+.1f}R]" if final_r is not None and msg_status in ("closed_win", "closed_loss") else ""
                print(f"    [{msg_status}]{r_note} {pair or '?'} — {content[:60]}{'...' if len(content) > 60 else ''}{trigger_note}")

        i += BATCH_SIZE
        time.sleep(1)

    print(f"\n{'='*50}")
    print(f"Run: {backtest_run}")
    print(f"  Ideas/commentaries identified: {ideas_found}")
    print(f"  Signals saved to DB: {signals_saved}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=str, default=None,
                        help="Backtest run label (e.g. v3-stateful). Defaults to timestamped label.")
    args = parser.parse_args()

    run_label = args.run or f"stateful-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    run_backfill(run_label)
