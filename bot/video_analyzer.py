"""
Analyzes Tom's weekly video using Gemini 1.5 Pro.
Extracts structured trade ideas from what he says.
"""

import os
import re
import time
import json
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


def _extract_json(text: str) -> list[dict]:
    """Extract a JSON array from Gemini's response, tolerating markdown fences and stray characters."""
    # Try direct parse first
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        pass

    # Find the outermost [...] block
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            pass

    print(f"Could not parse Gemini response: {text[:300]}")
    return []

PROMPT = """You are watching a weekly trading video from an experienced trader named Tom Dante.

Your job is to extract every trade idea he mentions — instruments he is watching, setups he likes, and conditions he wants to see before entering.

═══════════════════════════════════════════
INSTRUMENT SHORTHAND
═══════════════════════════════════════════

UJ=USDJPY, GU/Cable=GBPUSD, EU=EURUSD, Gold=XAUUSD, Silver=XAGUSD, Swissy=USDCHF,
DAX=GER40, DOW=US30, NQ=US100, FTSE=UK100, WTI/Oil=USOIL, DXY=Dollar index, EG=EURGBP,
EC=EURCAD, AU/Aussie=AUDUSD, UC/UCAD=USDCAD, Kiwi=NZDUSD, GJ=GBPJPY, EJ=EURJPY,
STOXX=EU50, BTC=BTCUSD, ETH=ETHUSD.

═══════════════════════════════════════════
WHAT COUNTS AS A TRADE IDEA
═══════════════════════════════════════════

Include an idea if Tom:
- Names an instrument and describes a directional bias AND at least one of: an entry condition, a specific level, or a setup trigger
- Examples that qualify: "I'm looking for shorts on cable if we get a break of X", "I want to see a retest of Y before going long", "bullish on gold above Z level"

Do NOT include:
- Pure passing mentions with zero detail ("gold is interesting")
- Pure educational commentary with no specific instrument/setup
- Markets he explicitly says he is NOT interested in this week
- Duplicate instruments — if Tom mentions the same pair more than once, include only the most detailed version of that idea

═══════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════

Return a JSON array. One object per trade idea:

[
  {
    "pair": "GBPUSD",
    "direction": "LONG" | "SHORT" | null,
    "entry_condition": "description of what Tom wants to see before entering",
    "target": "target level or description — or null",
    "invalidation": "stop or invalidation level — or null",
    "timeframe": "D1" | "H4" | "H1" | null,
    "confidence": "high" | "medium" | "low",
    "summary": "one sentence describing the idea as Tom would say it",
    "chart_time": 42
  }
]

For "chart_time": provide the number of seconds into the video where the chart for THIS specific instrument is clearly visible on screen AND the instrument ticker/name is legible in the chart header or title bar. Only provide a timestamp if you are confident the chart shown matches the pair in this idea. If you are not certain, use null — a wrong chart is worse than no chart.

If no trade ideas are found, return an empty array [].
Return only valid JSON. No markdown, no explanation."""


def extract_frame(video_path: str, seconds: float, output_path: str) -> bool:
    """Extract a single frame at `seconds` from the video and save to output_path."""
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(seconds * fps))
        ret, frame = cap.read()
        cap.release()
        if ret:
            cv2.imwrite(output_path, frame)
            return True
        return False
    except Exception as e:
        print(f"Frame extraction failed: {e}")
        return False


def analyze_video(video_path: str) -> list[dict]:
    """Upload video to Gemini and extract trade ideas."""
    print(f"Uploading video to Gemini: {video_path}")

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    # Determine mime type from extension
    ext = os.path.splitext(video_path)[1].lower()
    mime_map = {".mp4": "video/mp4", ".mov": "video/quicktime",
                ".avi": "video/avi", ".mkv": "video/x-matroska",
                ".webm": "video/webm"}
    mime_type = mime_map.get(ext, "video/mp4")

    print("Sending video to Gemini for analysis...")
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[
            types.Part.from_bytes(data=video_bytes, mime_type=mime_type),
            PROMPT,
        ],
    )

    text = response.text.strip()
    ideas = _extract_json(text)
    print(f"Extracted {len(ideas)} trade ideas from video")
    return ideas


def analyze_image(image_path: str, caption: str = "") -> list[dict]:
    """Analyze a chart screenshot using Gemini Vision."""
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp"}
    mime_type = mime_map.get(ext, "image/png")

    prompt = PROMPT
    if caption:
        prompt = f"Tom's caption on this chart image: {caption}\n\n{PROMPT}"

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt,
        ],
    )

    text = response.text.strip()
    return _extract_json(text)
