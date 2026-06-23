"""
Screenshot monitor — takes a screenshot every 60 seconds, detects pixel
changes in the Discord message area, sends to Claude Vision to extract
all messages with authors, then classifies Tom's new messages with
full conversation context.
"""

import os
import sys
import time
import base64
import json
from collections import deque
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
import mss
import mss.tools
from PIL import Image, ImageChops
import io
import anthropic

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent / "bot"))
from classifier import classify_message_with_context
from database import insert_signal
from telegram import send_signal_alert

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
WATCHED_NAME = os.environ.get("WATCHED_NAMES", "Tom").split(",")[0].strip()
CONTEXT_WINDOW = 15  # number of recent messages to pass as context
SEEN_FILE = Path(__file__).parent / ".seen_messages.json"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(json.dumps(list(seen)), encoding="utf-8")


VISION_PROMPT = """Look at this Discord screenshot and extract ALL visible chat messages in order from top to bottom.

For each message return the author name and the message content. Ignore reply preview quotes (the small grey quoted text above a message). Only extract the actual messages people wrote.

Return ONLY a JSON array of objects. Example:
[
  {"author": "Istan", "content": "If one has personal thoughts..."},
  {"author": "Tom", "content": "Completely up to you mate"},
  {"author": "Tom", "content": "A lot of the members usually dm me..."}
]

Return only valid JSON. No markdown, no explanation."""


def screenshot_to_base64() -> tuple[str, Image.Image]:
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64 = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
    return b64, img


def images_differ(img1: Image.Image, img2: Image.Image, threshold: int = 10) -> bool:
    if img1.size != img2.size:
        return True
    diff = ImageChops.difference(img1, img2)
    bbox = diff.getbbox()
    if bbox is None:
        return False
    changed_pixels = sum(diff.crop(bbox).convert("L").getdata())
    total_pixels = img1.width * img1.height
    return (changed_pixels / total_pixels) > threshold


def extract_all_messages(b64_image: str) -> list[dict]:
    """Send screenshot to Vision — returns list of {author, content} dicts."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64_image}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    )
    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        print(f"  [Vision] Could not parse response: {text[:200]}")
        return []


def run_monitor():
    print(f"Monitor started. Watching for messages from: {WATCHED_NAME}")
    print(f"Screenshot interval: {POLL_INTERVAL}s\n")

    last_image: Image.Image | None = None
    seen_messages: set[str] = load_seen()

    # Rolling buffer of recent messages for context — stores {author, content} dicts
    context_buffer: deque[dict] = deque(maxlen=CONTEXT_WINDOW)

    print("Taking initial screenshot to seed seen messages...")
    b64, last_image = screenshot_to_base64()
    all_msgs = extract_all_messages(b64)

    # Build context buffer from everything visible
    for m in all_msgs:
        content = m.get("content", "").strip()
        author = m.get("author", "unknown")
        if content:
            context_buffer.append({"author": author, "content": content})

    # Build context string
    context_str = "\n".join(f"{m['author']}: {m['content']}" for m in context_buffer)

    # Classify and save any new Tom messages not already in DB
    tom_visible = [m for m in all_msgs if m.get("author") == WATCHED_NAME]
    print(f"\nSeeded {len(tom_visible)} Tom messages from current screen — checking for new trade ideas...\n")

    for m in tom_visible:
        content = m.get("content", "").strip()
        if not content:
            continue
        seen_messages.add(content)

        result = classify_message_with_context(content, context_str)
        if not result.get("is_signal"):
            print(f"  • [skip] {content[:80]}")
            continue

        msg_id = f"screenshot_{hash(content)}"
        try:
            insert_signal(
                discord_message_id=msg_id,
                author=WATCHED_NAME,
                raw_message=content,
                signal=result,
            )
            print(f"  • [saved] {result.get('status')} | {result.get('direction')} {result.get('pair')} — {content[:60]}")
            try:
                timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
                send_signal_alert(result, WATCHED_NAME, timestamp)
            except Exception as e:
                print(f"    → Telegram error: {e}")
        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                print(f"  • [in DB]  {content[:80]}")
            else:
                print(f"  • [error]  {e}")

    save_seen(seen_messages)
    print(f"\nWatching for new ones...\n")

    while True:
        time.sleep(POLL_INTERVAL)

        b64, current_image = screenshot_to_base64()

        if last_image is not None and not images_differ(last_image, current_image):
            print(f"[{datetime.now().strftime('%H:%M')}] No change detected")
            last_image = current_image
            continue

        print(f"[{datetime.now().strftime('%H:%M')}] Change detected — sending to Vision...")
        last_image = current_image

        all_msgs = extract_all_messages(b64)

        if not all_msgs:
            print("  [Vision] No messages returned")
            continue

        # Find new Tom messages
        new_tom_messages = []
        for m in all_msgs:
            content = m.get("content", "").strip()
            author = m.get("author", "unknown")
            if not content:
                continue
            if author == WATCHED_NAME and content not in seen_messages:
                new_tom_messages.append(content)

        # Update context buffer with everything visible
        for m in all_msgs:
            content = m.get("content", "").strip()
            author = m.get("author", "unknown")
            if content:
                # Only add if not already the last entry (avoid dupes in buffer)
                if not context_buffer or context_buffer[-1]["content"] != content:
                    context_buffer.append({"author": author, "content": content})

        if not new_tom_messages:
            print("  No new messages from Tom")
            continue

        # Build context string for the classifier
        context_lines = []
        for m in context_buffer:
            context_lines.append(f"{m['author']}: {m['content']}")
        context_str = "\n".join(context_lines)

        for msg in new_tom_messages:
            seen_messages.add(msg)
            save_seen(seen_messages)
            timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
            print(f"  New message from Tom: {msg}")

            result = classify_message_with_context(msg, context_str)

            if result.get("is_signal"):
                print(f"  → SIGNAL: {result.get('status')} | {result.get('direction')} {result.get('pair')}")

                msg_id = f"screenshot_{hash(msg)}"
                try:
                    insert_signal(
                        discord_message_id=msg_id,
                        author=WATCHED_NAME,
                        raw_message=msg,
                        signal=result,
                    )
                    print("  → Logged to Supabase")
                except Exception as e:
                    if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                        print("  → Already in DB, skipping")
                    else:
                        print(f"  → DB error: {e}")

                try:
                    send_signal_alert(result, WATCHED_NAME, timestamp)
                except Exception as e:
                    print(f"  → Telegram error: {e}")
            else:
                print("  → Not a signal")


if __name__ == "__main__":
    run_monitor()
