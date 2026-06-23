import os
import json
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """You are reading messages from a private trading Discord channel posted by an experienced trader named Tom. He is not running a signal service — he posts casually about what he is watching, thinking, or doing in the markets.

You will be given Tom's message AND the recent conversation context leading up to it. Use the context to understand what instrument or setup Tom is referring to, especially for short follow-up messages like "yes, gold as well", "still valid", "out for 2R", "in now" etc.

THE GOLDEN RULE: If Tom's message (when read in context) relates to a specific instrument or trade — SAVE IT. When in doubt, save it as an idea.

Tom Dante terminology — always trade-relevant when mentioned:
SFP (swing failure pattern), IWF (inside week/day failure), ATR (average true range used as confluence), W1/D1/H4/H1/M15 (timeframes), hammer, inside day, daily/weekly close, sweep, retest, break and retest, vulnerable stops, liquidity, pa (price action), order in, runner, trailing stop, R (risk/reward e.g. 1R, 2.4R, -0.5R), managed, SL (stop loss), TP (take profit), long, short, entry, target, invalidation, bias, setup, level.

Common instrument shorthand Tom uses:
UJ = USDJPY, GU or Cable = GBPUSD, EU = EURUSD, Gold = XAUUSD, Silver = XAGUSD, Swissy = USDCHF, DAX = GER40, DOW = US30, NQ = US100, FTSE = UK100, WTI = Oil, DXY = Dollar index.

PHASE definitions:
- "idea": Tom is watching, analyzing, or planning. Has not entered. DEFAULT when unsure.
- "open": Tom is clearly in a position. Look for "in", "took", "entered", "long/short from", "filled", "triggered", "order in".
- "closed_win": Exited for a profit. Look for positive R mention, "out", "done", "secured", "target hit", "booked".
- "closed_loss": Stopped out or cut for a loss. Look for negative R, "stopped", "out for a loss", "cut it".
- "cancelled": Setup no longer valid, never entered. Look for "no longer valid", "missed", "moved on", "setup gone", "not valid".

SAVE the message if Tom:
- Mentions any instrument with any opinion, bias, plan, or observation
- Uses any trading terminology in context of a market
- Describes what he is watching, waiting for, or considering
- References a previous setup (context will tell you what instrument)
- Says he is in a trade, entered, or exited
- Mentions a result in R

DO NOT save only if the message is pure social/admin with zero market content (welcomes, payment info, "good morning", "no problem mate").

Respond ONLY with valid JSON. No markdown, no explanation.

If trade-related:
{
  "is_signal": true,
  "status": "idea" | "open" | "closed_win" | "closed_loss" | "cancelled",
  "pair": "instrument as Tom writes it — use context to infer if not explicit, or null",
  "direction": "LONG" or "SHORT" or null,
  "entry": "entry condition or price if mentioned — or null",
  "target": "target if mentioned — or null",
  "invalidation": "stop or invalidation if mentioned — or null",
  "notes": "copy the key part of his message verbatim, include context clues"
}

If not trade-related:
{
  "is_signal": false
}"""


def classify_message_with_context(message: str, context: str = "") -> dict:
    """Classify a message with optional conversation context."""
    if context:
        user_content = f"""Recent conversation context:
{context}

Classify this new message from Tom:
{message}"""
    else:
        user_content = message

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    text = response.content[0].text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed[0] if parsed else {"is_signal": False}
        return parsed
    except json.JSONDecodeError:
        return {"is_signal": False, "parse_error": text}


def classify_message(message: str) -> dict:
    """Classify a message without context — used by backfill."""
    return classify_message_with_context(message)
