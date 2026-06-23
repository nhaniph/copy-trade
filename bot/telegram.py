import os
import httpx

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

DIRECTION_EMOJI = {"LONG": "🟢", "SHORT": "🔴"}


def send_signal_alert(signal: dict, author: str, timestamp: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [Telegram] Not configured — skipping alert")
        return

    emoji = DIRECTION_EMOJI.get((signal.get("direction") or "").upper(), "⚪")
    direction = (signal.get("direction") or "?").upper()
    pair = signal.get("pair", "?")
    entry = signal.get("entry") or "—"
    target = signal.get("target") or "—"
    invalidation = signal.get("invalidation") or "—"
    notes = signal.get("notes") or ""

    lines = [
        f"{emoji} *{direction} — {pair}*",
        f"Entry: {entry}",
        f"Target: {target}",
        f"Invalidation: {invalidation}",
    ]
    if notes:
        lines.append(f"Notes: {notes}")
    lines.append(f"_Source: {author} · {timestamp}_")

    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = httpx.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    })
    resp.raise_for_status()
    print("  [Telegram] Alert sent")
