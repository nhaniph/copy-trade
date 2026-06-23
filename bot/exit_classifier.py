import os
import json
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """You are analyzing messages from a private trading Discord channel posted by an experienced trader named Tom.

You will be given an exit message and a set of prior messages filtered for relevance. Your job is to reconstruct the full trade.

═══════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════

1. Identify what instrument Tom closed
2. Identify the direction (LONG or SHORT)
3. Confirm it was a win or loss
4. Extract the R value if explicitly stated
5. Find the entry message — the specific message where Tom said he entered
6. Identify ALL messages that belong to this trade's lifecycle (entry → updates → exit)

═══════════════════════════════════════════
EXIT LANGUAGE
═══════════════════════════════════════════

closed_win: "out", "closed", "took profit", "hit target", "booked", "secured", "+XR", "XR profit", "made X", "off the table"
closed_loss: "stopped", "stopped out", "SL hit", "stop hit", "got stopped", "cut it", "-XR", "loss", "scratched"
Break even: use status "closed_win" and final_r 0.0

═══════════════════════════════════════════
R VALUES
═══════════════════════════════════════════

Only extract final_r if Tom explicitly states it as a result.
Do NOT infer from targets or distances. Use null if not stated.

═══════════════════════════════════════════
MULTIPLE TRADES IN ONE MESSAGE
═══════════════════════════════════════════

If Tom closes multiple trades in one message (e.g. "-0.47R on EG and -0.09R in Aussie"),
return a JSON array with one object per trade.

═══════════════════════════════════════════
MISSING INFORMATION — NEVER SKIP
═══════════════════════════════════════════

NEVER return skip: true if there is any exit language. Always create a record:
- Unknown instrument → "pair": "UNKNOWN"
- Unknown direction → "direction": null
- Break even → "status": "closed_win", "final_r": 0.0
- No R stated → "final_r": null

Only skip if the message has zero exit language (pure commentary, setup alerts, scheduling).

═══════════════════════════════════════════
INSTRUMENT SHORTHAND
═══════════════════════════════════════════

UJ=USDJPY, GU/Cable=GBPUSD, EU=EURUSD, Gold=XAUUSD, Silver=XAGUSD, Swissy=USDCHF,
DAX=GER40, DOW=US30, NQ=US100, FTSE=UK100, WTI/Oil=USOIL, DXY=Dollar index, EG=EURGBP,
EC=EURCAD, AU/Aussie=AUDUSD, UC/UCAD=USDCAD, Kiwi=NZDUSD, GJ=GBPJPY, EJ=EURJPY,
STOXX/Stoxx=EU50, BTC=BTCUSD, ETH=ETHUSD.

═══════════════════════════════════════════
THREAD MESSAGES
═══════════════════════════════════════════

In the thread_messages array, include only messages directly related to this trade:
- The entry message (where Tom said he entered)
- Any updates while in the trade (stop moved, partial TP, still holding)
- The exit message itself

Do NOT include general commentary, setup discussions before entry, or messages about other instruments.
Each thread message must include its original index number from the context.

═══════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════

Single trade:
{
  "pair": "GBPUSD",
  "direction": "SHORT",
  "status": "closed_win" | "closed_loss",
  "final_r": 1.7 | null,
  "close_trigger": "exact exit phrase",
  "confidence": "high" | "medium" | "low",
  "summary": "one sentence describing the trade",
  "opened_at": "ISO timestamp of entry message or null",
  "skip": false,
  "thread_messages": [
    {"index": 3, "timestamp": "2025-05-04T10:30:00", "content": "exact message text", "role": "entry" | "update" | "exit"}
  ]
}

Multiple trades in one exit message: return a JSON array of the above objects.

If genuinely no exit language: {"skip": true, "reason": "brief explanation"}

Return only valid JSON. No markdown, no explanation."""


# Instrument keyword map for pre-filtering
INSTRUMENT_KEYWORDS = {
    "GBPUSD": ["gbpusd", "cable", "gu", "pound", "sterling", "gbp"],
    "EURUSD": ["eurusd", "eu", "euro", "eur/usd"],
    "USDJPY": ["usdjpy", "uj", "dollar yen", "usd/jpy"],
    "XAUUSD": ["xauusd", "gold", "xau"],
    "XAGUSD": ["xagusd", "silver", "xag"],
    "USDCHF": ["usdchf", "swissy", "swiss", "chf"],
    "GER40":  ["ger40", "dax", "german"],
    "US30":   ["us30", "dow", "dow jones"],
    "US100":  ["us100", "nq", "nasdaq"],
    "UK100":  ["uk100", "ftse"],
    "USOIL":  ["usoil", "wti", "oil", "crude"],
    "EURGBP": ["eurgbp", "eg", "eur/gbp"],
    "EURCAD": ["eurcad", "ec", "eur/cad"],
    "AUDUSD": ["audusd", "au", "aussie", "aud"],
    "USDCAD": ["usdcad", "uc", "ucad", "cad", "loonie"],
    "NZDUSD": ["nzdusd", "kiwi", "nzd"],
    "GBPJPY": ["gbpjpy", "gj", "pound yen"],
    "EURJPY": ["eurjpy", "ej", "euro yen"],
    "EU50":   ["eu50", "stoxx", "eurostoxx"],
    "BTCUSD": ["btcusd", "btc", "bitcoin"],
    "ETHUSD": ["ethusd", "eth", "ethereum"],
}

ENTRY_VERBS = ["i'm in", "im in", "entered", "long from", "short from", "order in",
               "bought", "sold", "i've entered", "ive entered", "in on", "took a long",
               "took a short", "running long", "running short", "position on"]


def extract_instruments_from_text(text: str) -> set[str]:
    """Return set of instrument keys mentioned in text."""
    lower = text.lower()
    found = set()
    for pair, keywords in INSTRUMENT_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            found.add(pair)
    return found


def filter_relevant_messages(exit_content: str, context_messages: list[dict]) -> list[dict]:
    """
    From up to 50 context messages, return only those relevant to the exit.
    Always includes the last 5 messages. Also includes messages mentioning
    the same instrument or containing entry language.
    """
    if not context_messages:
        return []

    exit_instruments = extract_instruments_from_text(exit_content)
    always_include = set(range(max(0, len(context_messages) - 5), len(context_messages)))

    relevant = list(always_include)
    for i, msg in enumerate(context_messages):
        if i in always_include:
            continue
        content_lower = msg["content"].lower()
        # Include if same instrument mentioned
        msg_instruments = extract_instruments_from_text(msg["content"])
        if exit_instruments and exit_instruments & msg_instruments:
            relevant.append(i)
            continue
        # Include if contains entry language
        if any(verb in content_lower for verb in ENTRY_VERBS):
            relevant.append(i)

    relevant = sorted(set(relevant))
    return [context_messages[i] for i in relevant]


def classify_exit(exit_message: dict, context_messages: list[dict]) -> dict | list:
    """
    Classify a single exit message with filtered context.
    context_messages should already be pre-filtered (up to 50, then filtered for relevance).
    Returns a dict or list of dicts (multiple trades), or {"skip": True}.
    """
    filtered = filter_relevant_messages(exit_message["content"], context_messages)

    context_lines = "\n".join(
        f"[{i}] {m.get('timestamp', '')[:16]} — {m['content']}"
        for i, m in enumerate(filtered)
    )

    user_content = (
        f"{context_lines}\n\n"
        f"[EXIT] {exit_message.get('timestamp', '')[:16]} — {exit_message['content']}"
    )

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
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
        # Attach filtered context so caller can save thread messages
        if isinstance(result, list):
            for r in result:
                r["_filtered_context"] = filtered
        elif isinstance(result, dict) and not result.get("skip"):
            result["_filtered_context"] = filtered
        return result
    except json.JSONDecodeError:
        print(f"  [Exit classifier] Parse error: {text[:200]}")
        return {"skip": True, "reason": "parse error"}
