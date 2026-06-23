"""
Forensic analysis v2 — wider 50-message lookback with smart pre-filtering.

Finds all explicit exit messages, pulls up to 50 prior messages,
filters for relevance, then asks Opus to reconstruct the full trade
including the message thread.

Usage:
  python analysis.py --run analysis-v2
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
from exit_classifier import classify_exit
from database import get_client, create_trade, update_trade_status

JSON_FILE = Path(__file__).parent / "TR-VIP-JSON.json"
AUTHOR_NAME = "tr16"
AUTHOR_NICKNAME = "Tom"
LOOKBACK = 50
SOURCE = "analysis"

EXIT_KEYWORDS = [
    "stopped out", "stop hit", "sl hit", "got stopped", "stopped by",
    "closed for", "took profit", "hit target", "taken off", "booked",
    "secured", "out on", "out for", "out of", "i'm out", "im out",
    "cut it", "scratched", "closed it", "closed the", "closed my",
    "+1r", "+2r", "+3r", "+1.5r", "+0.", "-1r", "-0.", "xr",
    "loss on", "win on", "profit on", "trailed out", "trailed stop",
    "break even", "breakeven", "just took a", "just got out",
]


def is_tom(author: dict) -> bool:
    return author.get("name") == AUTHOR_NAME or author.get("nickname") == AUTHOR_NICKNAME


def looks_like_exit(content: str) -> bool:
    lower = content.lower()
    return any(kw in lower for kw in EXIT_KEYWORDS)


def save_trade_record(result: dict, exit_msg: dict, run_label: str,
                      all_tom_messages: list, exit_msg_idx: int) -> bool:
    """Save a classified trade and its thread messages to DB."""
    if result.get("skip"):
        return False

    db = get_client()
    pair = result.get("pair") or "UNKNOWN"
    direction = result.get("direction")
    status = result.get("status", "closed_win")
    final_r = result.get("final_r")
    close_trigger = result.get("close_trigger")
    summary = result.get("summary", "")
    opened_at = result.get("opened_at") or exit_msg["timestamp"]
    confidence = result.get("confidence", "medium")
    thread_messages = result.get("thread_messages", [])
    filtered_context = result.get("_filtered_context", [])

    # Create trade
    trade = create_trade(pair=pair, direction=direction, status="open",
                         source=SOURCE, opened_at=opened_at)
    trade_id = trade.get("id")
    if not trade_id:
        print(f"  → DB error: could not create trade")
        return False

    r_to_save = final_r
    if r_to_save is not None and status == "closed_loss":
        r_to_save = -abs(r_to_save)

    update_trade_status(trade_id, status, r_to_save)
    db.table("trades").update({
        "confidence": confidence,
        "close_trigger": close_trigger,
        "notes": summary,
        "backtest_run": run_label,
    }).eq("id", trade_id).execute()

    # Save exit message as signal
    exit_signal = {
        "discord_message_id": f"{run_label}_{exit_msg.get('id', exit_msg['timestamp'])}_{pair}",
        "author": AUTHOR_NICKNAME,
        "raw_message": exit_msg["content"].strip(),
        "pair": pair,
        "direction": direction,
        "notes": summary,
        "status": status,
        "trade_id": trade_id,
        "source": SOURCE,
        "backtest_run": run_label,
        "created_at": exit_msg["timestamp"],
    }
    try:
        db.table("signals").insert(exit_signal).execute()
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            print(f"  [DB error - exit signal] {e}")

    # Save thread messages as signals
    # Build a lookup from filtered_context by index
    saved_contents = {exit_msg["content"].strip()}

    for tm in thread_messages:
        tm_idx = tm.get("index")
        tm_content = tm.get("content", "").strip()
        tm_timestamp = tm.get("timestamp", "")
        tm_role = tm.get("role", "update")

        if not tm_content or tm_content in saved_contents:
            continue
        saved_contents.add(tm_content)

        # Try to match to original message for its ID
        original_id = None
        if tm_idx is not None and tm_idx < len(filtered_context):
            original_msg = filtered_context[tm_idx]
            original_id = original_msg.get("id") or original_msg.get("timestamp")
            tm_timestamp = original_msg.get("timestamp", tm_timestamp)

        signal_id = f"{run_label}_{original_id or tm_timestamp}_{pair}_{tm_role}"

        thread_signal = {
            "discord_message_id": signal_id,
            "author": AUTHOR_NICKNAME,
            "raw_message": tm_content,
            "pair": pair,
            "direction": direction,
            "notes": tm_role,
            "status": "open" if tm_role in ("entry", "update") else status,
            "trade_id": trade_id,
            "source": SOURCE,
            "backtest_run": run_label,
            "created_at": tm_timestamp or exit_msg["timestamp"],
        }
        try:
            db.table("signals").insert(thread_signal).execute()
        except Exception as e:
            if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
                print(f"  [DB error - thread signal] {e}")

    return True


def run_analysis(run_label: str):
    with open(JSON_FILE, encoding="utf-8") as f:
        data = json.load(f)

    all_messages = data["messages"]
    tom_messages = [m for m in all_messages if is_tom(m["author"])]

    print(f"Analysis run: {run_label}")
    print(f"Total Tom messages: {len(tom_messages)}")
    print(f"Lookback window: {LOOKBACK} messages\n")

    exit_candidates = [
        (i, m) for i, m in enumerate(tom_messages)
        if looks_like_exit(m["content"])
    ]
    print(f"Exit candidates: {len(exit_candidates)}\n")

    trades_saved = 0
    skipped = 0

    for idx, (msg_idx, exit_msg) in enumerate(exit_candidates):
        start = max(0, msg_idx - LOOKBACK)
        context = tom_messages[start:msg_idx]

        # Attach original message IDs and indices to context for thread saving
        for j, ctx_msg in enumerate(context):
            ctx_msg["_local_index"] = j

        content_preview = exit_msg["content"][:70]
        print(f"[{idx+1}/{len(exit_candidates)}] {exit_msg['timestamp'][:10]} — "
              f"{content_preview}{'...' if len(exit_msg['content']) > 70 else ''}")

        result = classify_exit(exit_msg, context)

        if isinstance(result, list):
            for item in result:
                if save_trade_record(item, exit_msg, run_label, tom_messages, msg_idx):
                    trades_saved += 1
                    print(f"  → SAVED: {item.get('pair')} {item.get('direction')} "
                          f"{item.get('status')} R={item.get('final_r')} "
                          f"conf={item.get('confidence')} "
                          f"thread={len(item.get('thread_messages', []))} msgs")
                else:
                    skipped += 1
        else:
            if save_trade_record(result, exit_msg, run_label, tom_messages, msg_idx):
                trades_saved += 1
                print(f"  → SAVED: {result.get('pair')} {result.get('direction')} "
                      f"{result.get('status')} R={result.get('final_r')} "
                      f"conf={result.get('confidence')} "
                      f"thread={len(result.get('thread_messages', []))} msgs")
            else:
                skipped += 1
                print(f"  → SKIP: {result.get('reason', '?')}")

        time.sleep(0.5)

    print(f"\n{'='*50}")
    print(f"Run: {run_label}")
    print(f"  Trades saved:      {trades_saved}")
    print(f"  Skipped:           {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=str, default="analysis-v2",
                        help="Run label (e.g. analysis-v2)")
    args = parser.parse_args()
    run_analysis(args.run)
