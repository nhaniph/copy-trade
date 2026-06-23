import os
import json
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """You are analyzing a batch of messages from a private trading Discord channel posted by an experienced trader named Tom. He posts casually about markets, setups he is watching, trades he is in, and results.

Your job is to read ALL the messages together as a conversation and identify distinct trade ideas. Group related messages about the same instrument and thesis into one idea.

═══════════════════════════════════════════
OPEN TRADES CONTEXT — CRITICAL
═══════════════════════════════════════════

At the start of each batch you will be given a list of trades Tom currently has open or is actively watching. Use this to:
- Correctly attribute exit messages to the right instrument (e.g. "out for 1.7R" → match to whichever open trade fits)
- Avoid creating a new trade for an instrument already open — add messages to the existing one instead
- If Tom says "cable" or "EG" or any shorthand and that instrument is in the open trades list, it belongs to that trade

═══════════════════════════════════════════
PHASE DEFINITIONS — READ CAREFULLY
═══════════════════════════════════════════

"idea"
  Tom is watching or planning a setup. He has a directional lean or specific conditions but has NOT entered yet.

"open"
  Tom explicitly states he is entering or is already in a position.
  Trigger words: "in", "entered", "order in", "long from", "short from", "bought", "sold", "running", "position on".

"closed_win"
  Tom explicitly confirms he exited for a profit.
  REQUIRED trigger words or phrases: "out", "closed", "took profit", "hit target", "taken off", "done", "booked", "secured", "+XR", "XR profit", "made X", "off the table".
  A trade moving in his favor is NOT a close. Tom commenting positively on price action is NOT a close.
  If you are not certain he exited — use "open".

"closed_loss"
  Tom explicitly confirms he was stopped out or cut the trade.
  REQUIRED trigger words: "stopped", "stopped out", "SL hit", "stop hit", "got stopped", "cut it", "closed for a loss", "-XR", "loss", "scratched".
  If you are not certain — use "open".

"cancelled"
  Setup is explicitly invalidated before entry. Tom says it's no longer valid, missed, or he's not taking it.
  Trigger words: "not taking", "missed", "invalidated", "no longer valid", "pass", "cancelled", "didn't take".

"commentary"
  General market observation about an instrument. No clear actionable bias or setup. No entry plan stated.

═══════════════════════════════════════════
CONSERVATIVE RULES
═══════════════════════════════════════════

1. When in doubt about a close, always use the LOWER status:
   - Uncertain if entered → keep "idea"
   - Uncertain if exited → keep "open"
   - Uncertain if cancelled or just waiting → keep "idea"

2. R values: ONLY extract R if Tom explicitly states it as a result (e.g. "+2R", "closed for 1.5R", "stopped for -1R").
   Do NOT infer R from targets or distances. Leave "final_r" as null if not stated.

3. A trade moving in Tom's favor does NOT mean it closed. He may hold for days.

4. One idea per instrument per thesis. A new idea for the same instrument only starts after the previous is
   explicitly closed/cancelled, or the thesis is clearly different (different direction or completely new setup).

5. Include a "close_trigger" field: the exact phrase that caused you to mark closed_win or closed_loss.
   If closed_win or closed_loss but you cannot quote a specific exit phrase — downgrade to "open".

6. If an exit message matches an instrument in the open trades list, always prefer that attribution over
   creating a new trade.

═══════════════════════════════════════════
TOM DANTE TERMINOLOGY
═══════════════════════════════════════════

SFP (swing failure pattern), IWF (inside week/day failure), ATR, W1/D1/H4/H1/M15 (timeframes),
hammer, inside day, daily/weekly close, sweep, retest, break and retest, vulnerable stops,
pa (price action), order in, runner, R (risk unit), managed, SL, TP, long, short,
entry, target, invalidation, bias, setup, level.

Instrument shorthand:
UJ=USDJPY, GU/Cable=GBPUSD, EU=EURUSD, Gold=XAUUSD, Silver=XAGUSD, Swissy=USDCHF,
DAX=GER40, DOW=US30, NQ=US100, FTSE=UK100, WTI/Oil=USOIL, DXY=Dollar index, EG=EURGBP,
EC=EURCAD, AU=AUDUSD, UC=USDCAD, ETH=Ethereum, BTC=Bitcoin.

═══════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════

Return a JSON array. Each object is one distinct trade idea or commentary:

[
  {
    "pair": "USDJPY",
    "direction": "LONG" | "SHORT" | null,
    "status": "idea" | "open" | "closed_win" | "closed_loss" | "cancelled" | "commentary",
    "entry": "entry condition or price — or null",
    "target": "target if mentioned — or null",
    "invalidation": "stop or invalidation level — or null",
    "final_r": 2.0 | -1.0 | null,
    "close_trigger": "exact phrase Tom used to exit — or null",
    "confidence": "high" | "medium" | "low",
    "summary": "one sentence summary",
    "messages": [
      {
        "index": 0,
        "content": "exact message text",
        "status": "idea" | "open" | "closed_win" | "closed_loss" | "cancelled" | "commentary"
      }
    ]
  }
]

Exclude purely social or admin messages entirely (greetings, payment info, welcome messages).
Messages marked "[CONTEXT ONLY — already processed]" have negative indices. Use them for context only — do NOT include them in your output. Only output ideas containing at least one message with index >= 0.
Return only valid JSON. No markdown, no explanation."""


def classify_stateful(messages: list[dict], open_trades: dict) -> list[dict]:
    """
    Classify a batch of messages with awareness of currently open trades.

    messages: list of {index, content, timestamp, id} dicts
    open_trades: dict of pair -> {direction, summary, opened_at} for trades currently open
    Returns list of idea objects.
    """
    numbered = "\n".join(
        f"[{m['index']}] {m.get('timestamp', '')[:10]} — {m['content']}"
        for m in messages
    )

    if open_trades:
        context_lines = []
        for pair, info in open_trades.items():
            direction = info.get("direction") or "?"
            opened = (info.get("opened_at") or "")[:10]
            summary = info.get("summary") or ""
            context_lines.append(f"  - {pair} {direction} (opened {opened}): {summary}")
        open_trades_block = "CURRENTLY OPEN TRADES:\n" + "\n".join(context_lines) + "\n\n"
    else:
        open_trades_block = "CURRENTLY OPEN TRADES: none\n\n"

    user_content = f"{open_trades_block}Here are Tom's messages:\n\n{numbered}"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        print(f"  [Stateful] Could not parse response: {text[:300]}")
        return []
