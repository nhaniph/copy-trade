import os
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

_client: Client | None = None

TRADE_EXPIRY_DAYS = 7  # auto-cancel idea if no update for this many days


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


def find_active_trade(pair: str) -> dict | None:
    """Find an active (idea or open) trade for this instrument within expiry window."""
    if not pair:
        return None

    cutoff = (datetime.now(timezone.utc) - timedelta(days=TRADE_EXPIRY_DAYS)).isoformat()

    result = get_client().table("trades") \
        .select("*") \
        .ilike("pair", pair) \
        .in_("status", ["idea", "open"]) \
        .gte("opened_at", cutoff) \
        .order("opened_at", desc=True) \
        .limit(1) \
        .execute()

    return result.data[0] if result.data else None


def create_trade(pair: str, direction: str | None, status: str, source: str = "live",
                 backtest_run: str | None = None, opened_at: str | None = None) -> dict:
    """Create a new parent trade record."""
    row = {
        "pair": pair,
        "direction": direction,
        "status": status,
        "source": source,
        "opened_at": opened_at or datetime.now(timezone.utc).isoformat(),
    }
    if backtest_run:
        row["backtest_run"] = backtest_run
    result = get_client().table("trades").insert(row).execute()
    return result.data[0] if result.data else {}


def update_trade_status(trade_id: str, status: str, final_r: float | None = None) -> None:
    """Update trade status and optionally set final R and closed_at."""
    updates = {"status": status}
    if status in ("closed_win", "closed_loss", "cancelled"):
        updates["closed_at"] = datetime.now(timezone.utc).isoformat()
    if final_r is not None:
        updates["final_r"] = final_r
    get_client().table("trades").update(updates).eq("id", trade_id).execute()


def find_watchlist_idea(pair: str) -> dict | None:
    """Find an active watchlist idea for this instrument in the current week."""
    if not pair:
        return None
    result = get_client().table("trades") \
        .select("*") \
        .ilike("pair", pair) \
        .eq("source", "watchlist") \
        .eq("status", "idea") \
        .order("opened_at", desc=True) \
        .limit(1) \
        .execute()
    return result.data[0] if result.data else None


def insert_signal(
    discord_message_id: str,
    author: str,
    raw_message: str,
    signal: dict,
) -> dict:
    """Insert a signal and link it to an active trade or create a new one."""
    db = get_client()
    pair = signal.get("pair")
    direction = signal.get("direction")
    status = signal.get("status", "idea")

    # Try to extract R value from notes for closed trades
    final_r = None
    if status in ("closed_win", "closed_loss"):
        import re
        text = (signal.get("notes") or "") + " " + (signal.get("entry") or "")
        match = re.search(r"([+-]?\d+\.?\d*)\s*R", text, re.IGNORECASE)
        if match:
            final_r = float(match.group(1))
            if status == "closed_loss":
                final_r = -abs(final_r)

    # Find or create parent trade
    trade = find_active_trade(pair) if pair else None

    if trade:
        trade_id = trade["id"]
        # Update trade status if it has progressed
        status_rank = {"idea": 0, "open": 1, "closed_win": 2, "closed_loss": 2, "cancelled": 2}
        if status_rank.get(status, 0) > status_rank.get(trade["status"], 0):
            update_trade_status(trade_id, status, final_r)
        # Update direction if we now know it and didn't before
        if direction and not trade.get("direction"):
            db.table("trades").update({"direction": direction}).eq("id", trade_id).execute()
    else:
        # No active trade — create a new one
        # If old idea expired, it stays as-is in DB (no explicit cancel needed)
        new_trade = create_trade(pair, direction, status)
        trade_id = new_trade.get("id")

    row = {
        "discord_message_id": discord_message_id,
        "author": author,
        "raw_message": raw_message,
        "pair": pair,
        "direction": direction,
        "entry": signal.get("entry"),
        "target": signal.get("target"),
        "invalidation": signal.get("invalidation"),
        "notes": signal.get("notes"),
        "status": status,
        "trade_id": trade_id,
        "source": signal.get("source", "live"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = db.table("signals").insert(row).execute()

    # If this message mentions an active watchlist idea, save it as an update there too
    if pair:
        watchlist_idea = find_watchlist_idea(pair)
        if watchlist_idea and watchlist_idea["id"] != trade_id:
            update_row = {
                "discord_message_id": f"watchlist_update_{discord_message_id}",
                "author": author,
                "raw_message": raw_message,
                "pair": pair,
                "direction": direction,
                "notes": signal.get("notes"),
                "status": status,
                "trade_id": watchlist_idea["id"],
                "source": "live",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                db.table("signals").insert(update_row).execute()
            except Exception:
                pass

    return result.data[0] if result.data else {}
