import os
import sys
import re
import shutil
import statistics
import tempfile
import httpx
import anthropic
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent / "bot"))
from database import get_client

app = FastAPI()
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/")
def index():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/watchlist")

@app.get("/watchlist")
def watchlist_page():
    return FileResponse(Path(__file__).parent / "static" / "watchlist.html")

@app.get("/results")
def results_page():
    return FileResponse(Path(__file__).parent / "static" / "results.html")

@app.get("/ideas")
def ideas_page():
    return FileResponse(Path(__file__).parent / "static" / "ideas.html")


def _calc_stats(wins: list, losses: list, all_trades: list) -> dict:
    """Core stats calculation given pre-filtered win/loss R lists."""
    win_rs = [abs(float(t["final_r"])) for t in wins]
    loss_rs = [abs(float(t["final_r"])) for t in losses]

    total_r = sum(win_rs) - sum(loss_rs)
    avg_win = sum(win_rs) / len(win_rs) if win_rs else 0
    avg_loss = sum(loss_rs) / len(loss_rs) if loss_rs else 0
    win_rate = len(wins) / len(all_trades) if all_trades else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    profit_factor = sum(win_rs) / sum(loss_rs) if sum(loss_rs) > 0 else 0

    all_rs = win_rs + [-r for r in loss_rs]
    sharpe = 0
    if len(all_rs) > 1:
        mean_r = sum(all_rs) / len(all_rs)
        std_r = statistics.stdev(all_rs)
        sharpe = round(mean_r / std_r, 2) if std_r > 0 else 0

    return {
        "total_trades": len(all_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate * 100, 1),
        "total_r": round(total_r, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "profit_factor": round(profit_factor, 2),
        "sharpe": sharpe,
    }


EMPTY_STATS = {
    "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
    "total_r": 0, "avg_win": 0, "avg_loss": 0,
    "expectancy": 0, "profit_factor": 0, "sharpe": 0,
}


def compute_stats(trades: list[dict]) -> dict:
    """
    Returns two stat sets:
      confirmed — only trades with an explicit final_r from Tom's messages
      estimated — all trades, filling missing final_r with 1R/-1R
    """
    if not trades:
        return {"confirmed": EMPTY_STATS, "estimated": EMPTY_STATS,
                "confirmed_count": 0, "total_count": 0}

    all_wins = [t for t in trades if t["status"] == "closed_win"]
    all_losses = [t for t in trades if t["status"] == "closed_loss"]

    # Confirmed: only trades where final_r was explicitly recorded
    conf_wins = [t for t in all_wins if t.get("final_r") is not None]
    conf_losses = [t for t in all_losses if t.get("final_r") is not None]
    conf_trades = conf_wins + conf_losses
    confirmed = _calc_stats(conf_wins, conf_losses, conf_trades) if conf_trades else EMPTY_STATS

    # Estimated: fill missing final_r with 1R default
    def fill_r(t):
        if t.get("final_r") is not None:
            return t
        return {**t, "final_r": 1.0 if t["status"] == "closed_win" else -1.0}

    est_wins = [fill_r(t) for t in all_wins]
    est_losses = [fill_r(t) for t in all_losses]
    estimated = _calc_stats(est_wins, est_losses, trades)

    return {
        "confirmed": confirmed,
        "estimated": estimated,
        "confirmed_count": len(conf_trades),
        "total_count": len(trades),
    }


def compute_equity(trades: list[dict], confirmed_only: bool = False) -> list[dict]:
    points = []
    cumulative = 0
    for t in sorted(trades, key=lambda x: x.get("opened_at") or ""):
        has_r = t.get("final_r") is not None
        if confirmed_only and not has_r:
            continue
        r = float(t["final_r"]) if has_r else (1.0 if t["status"] == "closed_win" else -1.0)
        if t["status"] == "closed_loss":
            r = -abs(r)
        cumulative += r
        points.append({
            "date": (t.get("closed_at") or t.get("opened_at") or "")[:10],
            "r": round(cumulative, 2),
            "pair": t.get("pair") or "?",
            "confirmed": has_r,
        })
    return points


@app.get("/api/results/date-range")
def get_results_date_range():
    db = get_client()
    result = db.table("signals").select("created_at") \
        .eq("source", "analysis") \
        .order("created_at").execute()
    data = result.data or []
    if not data:
        return {"from": None, "to": None}
    return {"from": data[0]["created_at"][:10], "to": data[-1]["created_at"][:10]}


@app.get("/api/results/trades")
def get_results_trades(page: int = 1, limit: int = 20):
    db = get_client()
    offset = (page - 1) * limit
    trades_result = db.table("trades").select("*") \
        .eq("source", "analysis") \
        .in_("status", ["closed_win", "closed_loss"]) \
        .order("opened_at", desc=True) \
        .range(offset, offset + limit - 1).execute()
    trades = trades_result.data or []

    count_result = db.table("trades").select("id", count="exact") \
        .eq("source", "analysis") \
        .in_("status", ["closed_win", "closed_loss"]).execute()

    threads = []
    for trade in trades:
        signals = db.table("signals").select("*") \
            .eq("trade_id", trade["id"]) \
            .order("created_at").execute().data or []
        threads.append({"trade": trade, "signals": signals})

    return {"threads": threads, "total": count_result.count or 0, "page": page, "limit": limit}


@app.get("/api/backtest/runs")
def get_backtest_runs():
    db = get_client()
    result = db.table("trades").select("backtest_run").eq("source", "backfill").execute()
    runs = sorted({r["backtest_run"] for r in (result.data or []) if r.get("backtest_run")})
    return runs


@app.get("/api/stats")
def get_stats(source: str = None, run: str = None, reviewed_only: bool = False):
    db = get_client()
    query = db.table("trades").select("*").in_("status", ["closed_win", "closed_loss"])
    if source:
        query = query.eq("source", source)
    if run:
        query = query.eq("backtest_run", run)
    if reviewed_only:
        query = query.eq("reviewed", True)
    result = query.execute()
    return compute_stats(result.data or [])


@app.get("/api/equity")
def get_equity(source: str = None, run: str = None, confirmed_only: bool = False, reviewed_only: bool = False):
    db = get_client()
    query = db.table("trades").select("*").in_("status", ["closed_win", "closed_loss"])
    if source:
        query = query.eq("source", source)
    if run:
        query = query.eq("backtest_run", run)
    if reviewed_only:
        query = query.eq("reviewed", True)
    result = query.execute()
    return compute_equity(result.data or [], confirmed_only=confirmed_only)


@app.get("/api/trades")
def get_trades(page: int = 1, limit: int = 50, source: str = None, run: str = None, reviewed_only: bool = False):
    db = get_client()
    offset = (page - 1) * limit
    query = db.table("trades").select("*").in_("status", ["closed_win", "closed_loss"])
    if source:
        query = query.eq("source", source)
    if run:
        query = query.eq("backtest_run", run)
    if reviewed_only:
        query = query.eq("reviewed", True)
    result = query.order("opened_at", desc=True).range(offset, offset + limit - 1).execute()
    count_query = db.table("trades").select("id", count="exact").in_("status", ["closed_win", "closed_loss"])
    if source:
        count_query = count_query.eq("source", source)
    if run:
        count_query = count_query.eq("backtest_run", run)
    if reviewed_only:
        count_query = count_query.eq("reviewed", True)
    count_result = count_query.execute()
    return {"trades": result.data or [], "total": count_result.count or 0, "page": page, "limit": limit}


@app.get("/api/trade-threads")
def get_trade_threads(page: int = 1, limit: int = 10, status: str = None, pair: str = None, source: str = None):
    db = get_client()
    offset = (page - 1) * limit

    query = db.table("trades").select("*")
    if status:
        query = query.eq("status", status)
    if pair:
        query = query.ilike("pair", f"%{pair}%")
    if source:
        query = query.eq("source", source)

    result = query.order("opened_at", desc=True).range(offset, offset + limit - 1).execute()
    trades = result.data or []

    count_query = db.table("trades").select("id", count="exact")
    if status:
        count_query = count_query.eq("status", status)
    if pair:
        count_query = count_query.ilike("pair", f"%{pair}%")
    if source:
        count_query = count_query.eq("source", source)
    count_result = count_query.execute()

    threads = []
    for trade in trades:
        signals_result = db.table("signals").select("*") \
            .eq("trade_id", trade["id"]) \
            .order("created_at").execute()
        threads.append({"trade": trade, "signals": signals_result.data or []})

    return {"threads": threads, "total": count_result.count or 0, "page": page, "limit": limit}


@app.get("/api/backtest/date-range")
def get_backtest_date_range(run: str = None):
    db = get_client()
    query = db.table("signals").select("created_at").eq("source", "backfill")
    if run:
        query = query.eq("backtest_run", run)
    result = query.order("created_at").execute()
    data = result.data or []
    if not data:
        return {"from": None, "to": None}
    return {
        "from": data[0]["created_at"][:10],
        "to": data[-1]["created_at"][:10],
    }


@app.get("/api/ideas")
def get_ideas(page: int = 1, limit: int = 25, status: str = None, pair: str = None, source: str = None):
    db = get_client()
    offset = (page - 1) * limit
    query = db.table("signals").select("*")
    if status:
        query = query.eq("status", status)
    else:
        query = query.in_("status", ["idea", "cancelled"])
    if pair:
        query = query.ilike("pair", f"%{pair}%")
    if source:
        query = query.eq("source", source)
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    count_query = db.table("signals").select("id", count="exact")
    if status:
        count_query = count_query.eq("status", status)
    else:
        count_query = count_query.in_("status", ["idea", "cancelled"])
    if pair:
        count_query = count_query.ilike("pair", f"%{pair}%")
    if source:
        count_query = count_query.eq("source", source)
    count_result = count_query.execute()
    return {"ideas": result.data or [], "total": count_result.count or 0, "page": page, "limit": limit}


# ── Review queue ──────────────────────────────────────────────────────────────

class ReviewAction(BaseModel):
    final_r: Optional[float] = None
    status: Optional[str] = None  # allow reopening as open/idea


@app.post("/api/backtest/snapshot")
def create_snapshot(source_run: str, target_run: str):
    """
    Copy all trades from source_run into target_run, preserving all fields
    and setting original_trade_id to the source trade's id.
    """
    db = get_client()

    existing = db.table("trades").select("id", count="exact") \
        .eq("backtest_run", target_run).execute()
    if (existing.count or 0) > 0:
        raise HTTPException(400, f"Run '{target_run}' already exists — delete it first")

    source_trades = db.table("trades").select("*") \
        .eq("backtest_run", source_run).execute().data or []

    if not source_trades:
        raise HTTPException(404, f"No trades found for run '{source_run}'")

    EXCLUDE = {"id", "created_at"}
    copied = 0
    for t in source_trades:
        row = {k: v for k, v in t.items() if k not in EXCLUDE}
        row["backtest_run"] = target_run
        row["original_trade_id"] = t["id"]
        row["reviewed"] = False  # reset review state for fresh review pass
        db.table("trades").insert(row).execute()
        copied += 1

    return {"ok": True, "copied": copied, "target_run": target_run}


@app.get("/api/review/queue")
def get_review_queue(run: str = None, page: int = 1, limit: int = 20):
    """
    Returns closed trades pending review, sorted by confidence (medium/low first,
    then high). Excludes already-reviewed trades. For snapshot runs, fetches
    signals via original_trade_id so v2 messages are visible when reviewing v3.
    """
    db = get_client()
    offset = (page - 1) * limit

    query = db.table("trades").select("*") \
        .in_("status", ["closed_win", "closed_loss"]) \
        .eq("reviewed", False)
    if run:
        query = query.eq("backtest_run", run)

    all_pending = query.order("opened_at", desc=False).execute().data or []

    CONF_ORDER = {"low": 0, "medium": 1, "high": 2, None: 2}
    all_pending.sort(key=lambda t: CONF_ORDER.get(t.get("confidence"), 2))

    # Deduplicate: keep the trade with the most signals when pair+direction+opened_at match
    seen: dict = {}
    for t in all_pending:
        key = (t.get("pair"), t.get("direction"), (t.get("opened_at") or "")[:10])
        if key not in seen:
            seen[key] = t
        else:
            # Keep whichever has final_r set, otherwise keep first
            if t.get("final_r") is not None and seen[key].get("final_r") is None:
                seen[key] = t
    all_pending = list(seen.values())
    all_pending.sort(key=lambda t: CONF_ORDER.get(t.get("confidence"), 2))

    total = len(all_pending)
    page_trades = all_pending[offset:offset + limit]

    threads = []
    for trade in page_trades:
        # Use original_trade_id for signal lookup on snapshot runs
        signal_trade_id = trade.get("original_trade_id") or trade["id"]
        signals = db.table("signals").select("*") \
            .eq("trade_id", signal_trade_id) \
            .order("created_at").execute().data or []
        threads.append({"trade": trade, "signals": signals})

    reviewed_count = db.table("trades").select("id", count="exact") \
        .in_("status", ["closed_win", "closed_loss"]) \
        .eq("reviewed", True) \
        .eq("backtest_run", run).execute().count or 0 if run else 0

    total_closed = db.table("trades").select("id", count="exact") \
        .in_("status", ["closed_win", "closed_loss"]) \
        .eq("backtest_run", run).execute().count or 0 if run else total + reviewed_count

    return {
        "threads": threads,
        "total_pending": total,
        "total_reviewed": reviewed_count,
        "total_closed": total_closed,
        "page": page,
        "limit": limit,
    }


@app.post("/api/review/approve/{trade_id}")
def review_approve(trade_id: str):
    """Mark trade as reviewed with no changes."""
    get_client().table("trades").update({"reviewed": True}).eq("id", trade_id).execute()
    return {"ok": True}


@app.post("/api/review/fix/{trade_id}")
def review_fix(trade_id: str, body: ReviewAction):
    """Correct final_r and/or status, then mark reviewed."""
    updates: dict = {"reviewed": True}
    if body.final_r is not None:
        updates["final_r"] = body.final_r
    if body.status:
        updates["status"] = body.status
        if body.status in ("open", "idea"):
            updates["final_r"] = None
            updates["closed_at"] = None
    get_client().table("trades").update(updates).eq("id", trade_id).execute()
    return {"ok": True}


@app.post("/api/review/nullify/{trade_id}")
def review_nullify(trade_id: str):
    """Remove the final_r (R was from a target mention, not an exit), keep status."""
    get_client().table("trades").update({"final_r": None, "reviewed": True}).eq("id", trade_id).execute()
    return {"ok": True}


@app.post("/api/review/reopen/{trade_id}")
def review_reopen(trade_id: str):
    """Trade was a phantom close — revert to open status."""
    get_client().table("trades").update({
        "status": "open",
        "final_r": None,
        "closed_at": None,
        "reviewed": True,
    }).eq("id", trade_id).execute()
    return {"ok": True}


@app.post("/api/review/cancel/{trade_id}")
def review_cancel(trade_id: str):
    """Trade was never entered — mark as cancelled."""
    get_client().table("trades").update({
        "status": "cancelled",
        "final_r": None,
        "closed_at": None,
        "reviewed": True,
    }).eq("id", trade_id).execute()
    return {"ok": True}


# ── Watchlist ─────────────────────────────────────────────────────────────────

def _week_start(date_str: str | None = None) -> str:
    """Return the Sunday of the week containing date_str (or today). Trading week = Sun–Sat."""
    if date_str:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        d = datetime.now(timezone.utc).date()
    # weekday(): Mon=0 … Sun=6. We want Sunday as start, so shift by (weekday+1)%7
    days_since_sunday = (d.weekday() + 1) % 7
    sunday = d - __import__("datetime").timedelta(days=days_since_sunday)
    return f"week-{sunday.strftime('%Y-%m-%d')}"


def _current_week_label() -> str:
    return _week_start()


def _save_watchlist_ideas(ideas: list[dict], source: str, week_label: str,
                          video_type: str = "weekly_prep", video_date: str | None = None,
                          chart_files: dict | None = None) -> int:
    db = get_client()
    saved = 0
    opened_at = (video_date + "T12:00:00+00:00") if video_date else datetime.now(timezone.utc).isoformat()
    for idea in ideas:
        pair = idea.get("pair") or "UNKNOWN"
        row = {
            "pair": pair,
            "direction": idea.get("direction"),
            "status": "idea",
            "source": "watchlist",
            "backtest_run": week_label,
            "opened_at": opened_at,
            "notes": video_type,
            "confidence": idea.get("confidence", "medium"),
        }
        trade = db.table("trades").insert(row).execute()
        trade_id = trade.data[0]["id"] if trade.data else None
        if not trade_id:
            continue

        # Save extra fields to a signal row
        signal = {
            "discord_message_id": f"watchlist_{week_label}_{pair}_{saved}",
            "author": "Tom",
            "raw_message": idea.get("summary") or idea.get("entry_condition") or "",
            "pair": pair,
            "direction": idea.get("direction"),
            "entry": idea.get("entry_condition"),
            "target": idea.get("target"),
            "invalidation": idea.get("invalidation"),
            "notes": idea.get("timeframe"),
            "status": "idea",
            "trade_id": trade_id,
            "source": "watchlist",
            "backtest_run": week_label,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            db.table("signals").insert(signal).execute()
        except Exception:
            pass

        # Save chart image signal if one was extracted for this idea
        if chart_files and saved < len(chart_files):
            chart_filename = chart_files.get(saved)
            if chart_filename:
                try:
                    db.table("signals").insert({
                        "discord_message_id": f"chart_{trade_id}",
                        "author": "upload",
                        "raw_message": chart_filename,
                        "pair": pair,
                        "status": "idea",
                        "trade_id": trade_id,
                        "source": "chart",
                        "created_at": opened_at,
                    }).execute()
                except Exception:
                    pass

        saved += 1
    return saved


@app.get("/api/watchlist/weeks")
def get_watchlist_weeks():
    db = get_client()
    result = db.table("trades").select("backtest_run, opened_at") \
        .eq("source", "watchlist").eq("status", "idea") \
        .order("opened_at", desc=True).execute()
    seen = {}
    for row in (result.data or []):
        label = row.get("backtest_run")
        if label and label not in seen:
            seen[label] = label.replace("week-", "")
    weeks = [{"label": k, "date": v} for k, v in seen.items()]
    return weeks


@app.get("/api/watchlist/ideas")
def get_watchlist_ideas(week: str | None = None):
    db = get_client()

    if not week:
        # Default to most recent week
        result = db.table("trades").select("backtest_run") \
            .eq("source", "watchlist").eq("status", "idea") \
            .order("opened_at", desc=True).limit(1).execute()
        if not result.data:
            return {"week": None, "ideas": []}
        week = result.data[0]["backtest_run"]

    week_label = week
    trades = db.table("trades").select("*") \
        .eq("source", "watchlist").eq("status", "idea") \
        .eq("backtest_run", week_label) \
        .order("opened_at").execute().data or []

    ideas = []
    for trade in trades:
        # Get base signal for extra fields
        trade["video_type"] = trade.get("notes") or "weekly_prep"
        sig = db.table("signals").select("*").eq("trade_id", trade["id"]) \
            .eq("status", "idea").limit(1).execute().data
        if sig:
            trade["entry_condition"] = sig[0].get("entry")
            trade["target"] = sig[0].get("target")
            trade["invalidation"] = sig[0].get("invalidation")
            trade["timeframe"] = sig[0].get("notes")
            trade["summary"] = sig[0].get("raw_message")

        # Get chart image if any
        chart_sig = db.table("signals").select("raw_message").eq("trade_id", trade["id"]) \
            .eq("source", "chart").limit(1).execute().data
        trade["chart_url"] = chart_sig[0]["raw_message"] if chart_sig else None

        # Get chat updates (non-idea signals)
        updates = db.table("signals").select("*").eq("trade_id", trade["id"]) \
            .neq("status", "idea").neq("source", "chart").order("created_at").execute().data or []

        ideas.append({"idea": trade, "updates": updates})

    week_display = week_label.replace("week-", "")
    return {"week": week_display, "ideas": ideas}


@app.post("/api/watchlist/ideas/{trade_id}/chart")
async def upload_chart(trade_id: str, file: UploadFile = File(...)):
    charts_dir = Path(__file__).parent / "static" / "charts"
    charts_dir.mkdir(exist_ok=True)

    suffix = Path(file.filename).suffix or ".png"
    filename = f"{trade_id}{suffix}"
    dest = charts_dir / filename

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    db = get_client()
    # Remove any existing chart signal for this trade
    db.table("signals").delete().eq("trade_id", trade_id).eq("source", "chart").execute()
    db.table("signals").insert({
        "discord_message_id": f"chart_{trade_id}",
        "author": "upload",
        "raw_message": filename,
        "pair": None,
        "status": "idea",
        "trade_id": trade_id,
        "source": "chart",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    return {"ok": True, "url": f"/static/charts/{filename}"}


@app.post("/api/watchlist/upload-video")
async def upload_video(file: UploadFile = File(...), video_type: str = Form(default="weekly_prep"), video_date: str = Form(default="")):
    sys.path.insert(0, str(Path(__file__).parent.parent / "bot"))
    from video_analyzer import analyze_video, extract_frame

    suffix = Path(file.filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        ideas = analyze_video(tmp_path)

        # Extract chart frames and upload to Supabase Storage
        chart_files: dict[int, str] = {}
        supabase_url = os.environ.get("SUPABASE_URL", "")
        for i, idea in enumerate(ideas):
            t = idea.get("chart_time")
            if t is None:
                continue
            pair_slug = (idea.get("pair") or "unknown").replace("/", "")
            filename = f"{pair_slug}_{video_date or datetime.now(timezone.utc).strftime('%Y%m%d')}_{i}.jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as ftmp:
                frame_path = ftmp.name
            try:
                if extract_frame(tmp_path, float(t), frame_path):
                    with open(frame_path, "rb") as img:
                        img_bytes = img.read()
                    get_client().storage.from_("charts").upload(
                        filename, img_bytes,
                        {"content-type": "image/jpeg", "x-upsert": "true"}
                    )
                    public_url = f"{supabase_url}/storage/v1/object/public/charts/{filename}"
                    chart_files[i] = public_url
                    print(f"  Chart uploaded for {idea.get('pair')} at {t}s → {filename}")
            except Exception as e:
                print(f"  Chart upload failed for {idea.get('pair')}: {e}")
            finally:
                os.unlink(frame_path)
    finally:
        os.unlink(tmp_path)

    if not ideas:
        raise HTTPException(400, "No trade ideas found in video")

    week_label = _week_start(video_date if video_date else None)
    saved = _save_watchlist_ideas(ideas, "video", week_label, video_type=video_type,
                                  video_date=video_date or None, chart_files=chart_files)
    return {"ok": True, "ideas_saved": saved, "week": week_label}


@app.post("/api/watchlist/upload-image")
async def upload_image(file: UploadFile = File(...), caption: str = Form(default="")):
    sys.path.insert(0, str(Path(__file__).parent.parent / "bot"))
    from video_analyzer import analyze_image

    suffix = Path(file.filename).suffix or ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        ideas = analyze_image(tmp_path, caption)
    finally:
        os.unlink(tmp_path)

    if not ideas:
        raise HTTPException(400, "No trade ideas found in image")

    week_label = _current_week_label()
    saved = _save_watchlist_ideas(ideas, "image", week_label)
    return {"ok": True, "ideas_saved": saved, "week": week_label}


# ── Pushover ──────────────────────────────────────────────────────────────────

def send_pushover(title: str, message: str, priority: int = 1) -> bool:
    """
    Send a Pushover notification.
    priority: 0=normal, 1=high (bypasses DND), 2=emergency (repeats until acknowledged)
    """
    payload = {
        "token": os.environ.get("PUSHOVER_API_TOKEN", ""),
        "user": os.environ.get("PUSHOVER_USER_KEY", ""),
        "title": title,
        "message": message,
        "priority": priority,
        "sound": "siren",
    }
    if priority == 2:
        payload["retry"] = 30    # retry every 30s
        payload["expire"] = 3600  # give up after 1 hour

    try:
        r = httpx.post("https://api.pushover.net/1/messages.json", data=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Pushover error: {e}")
        return False


def _enrich_alert_with_claude(pair: str, price: str, note: str, idea: dict, updates: list) -> str:
    """Ask Claude to write a clear, actionable alert message using trade idea context."""
    updates_text = ""
    if updates:
        updates_text = "\n".join(
            f"- {u.get('created_at', '')[:10]}: {u.get('raw_message', '')}"
            for u in updates[-3:]  # last 3 updates only
        )

    prompt = f"""TradingView just fired an alert: {pair} reached {price}.
{f'Alert note: {note}' if note else ''}

Trade idea context from Tom's weekly prep:
- Direction: {idea.get('direction') or 'unknown'}
- Entry condition: {idea.get('entry_condition') or idea.get('notes') or 'n/a'}
- Target: {idea.get('target') or 'n/a'}
- Invalidation: {idea.get('invalidation') or 'n/a'}
- Timeframe: {idea.get('timeframe') or 'n/a'}
- Confidence: {idea.get('confidence') or 'n/a'}
{f'Recent Discord updates:{chr(10)}{updates_text}' if updates_text else ''}

Write a short alert message (4-5 sentences max) telling me exactly what just happened, what Tom's setup is, and what I should be looking for. Be direct and specific — I may be asleep. Do not use bullet points, just plain sentences."""

    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"Claude enrichment error: {e}")
        # Fallback to a plain message if Claude fails
        return (
            f"{pair} hit {price}. "
            f"Tom's setup: {idea.get('entry_condition') or idea.get('notes') or 'see watchlist'}. "
            f"Target: {idea.get('target') or 'n/a'}. "
            f"Invalidation: {idea.get('invalidation') or 'n/a'}."
        )


# ── TradingView webhook ───────────────────────────────────────────────────────

@app.post("/api/alerts/tradingview")
async def tradingview_webhook(request: Request):
    """
    Receives TradingView alerts. Expected payload:
    {"pair": "GBPUSD", "price": "{{close}}", "note": "optional context"}
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    pair = (body.get("pair") or "").upper().strip()
    price = str(body.get("price") or "")
    note = body.get("note") or ""

    print(f"TradingView alert received: {pair} @ {price} | {note}")

    if not pair:
        raise HTTPException(400, "Missing pair in alert payload")

    db = get_client()

    # Find the active watchlist idea for this pair
    result = db.table("trades").select("*") \
        .eq("source", "watchlist").eq("status", "idea") \
        .ilike("pair", pair) \
        .order("opened_at", desc=True).limit(1).execute()

    if not result.data:
        # No matching idea — send a simple alert anyway
        send_pushover(
            title=f"⚡ {pair} Alert",
            message=f"{pair} hit {price}. No active watchlist idea found for this pair.",
            priority=1,
        )
        return {"ok": True, "matched_idea": False}

    idea = result.data[0]

    # Enrich idea with signal fields
    sig = db.table("signals").select("*").eq("trade_id", idea["id"]) \
        .eq("status", "idea").limit(1).execute().data
    if sig:
        idea["entry_condition"] = sig[0].get("entry")
        idea["target"] = sig[0].get("target")
        idea["invalidation"] = sig[0].get("invalidation")
        idea["timeframe"] = sig[0].get("notes")

    # Get recent Discord updates
    updates = db.table("signals").select("*").eq("trade_id", idea["id"]) \
        .neq("status", "idea").order("created_at", desc=True).limit(3).execute().data or []

    # Ask Claude to write the alert message
    message = _enrich_alert_with_claude(pair, price, note, idea, updates)

    direction = idea.get("direction") or ""
    title = f"🔔 {pair} {direction} — Entry Alert"

    sent = send_pushover(title=title, message=message, priority=1)
    print(f"Pushover sent: {sent} | {title}")

    return {"ok": True, "matched_idea": True, "alert_sent": sent, "message": message}
