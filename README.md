# TR Trades Bot

Monitors Discord for trade signals from Tom, classifies them with Claude, logs to Supabase, sends Telegram alerts, and displays everything on a web dashboard.

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
```

Open `.env` and fill in:
- `ANTHROPIC_API_KEY` — from console.anthropic.com
- `SUPABASE_URL` and `SUPABASE_KEY` — from Supabase → Settings → API
- `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` — from @BotFather on Telegram
- `WATCHED_NAMES` — Tom's Discord display name, e.g. `Tom`
- `POLL_INTERVAL_SECONDS` — how often to screenshot (default: 60)

---

## Running

### Monitor (main process)
Takes a screenshot every 60 seconds. If anything changed on screen, sends it to Claude Vision to extract new messages from Tom, classifies them, logs to Supabase, and fires a Telegram alert.

**Discord must be open and visible with the vip-service channel active. Do not minimize it.**

```bash
python monitor.py
```

### Dashboard
```bash
uvicorn dashboard.main:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

---

## Backfill from DiscordChatExporter

To load historical messages from a DCE JSON export into Supabase:

1. Export the channel from DiscordChatExporter as JSON, save as `TR-VIP-JSON.json` in the project root
2. Run:
```bash
python backfill_json.py
```

Safe to re-run — duplicate message IDs are automatically skipped.

### Backfill runs

Each run is tagged with a label passed via `--run`:

```bash
python backfill_batch.py --run v2-confirmed
```

| Run | Description |
|---|---|
| `v1-estimated` | Original backfill, R defaults to 1R where not stated |
| `v2-confirmed` | Strict classifier, explicit exits only |
| `v3-reviewed` | Snapshot of v2 + manual corrections via review queue |

To create v3: go to the Backtest page, select `v2-confirmed`, click **📸 Snapshot → v3**.

---

## Database maintenance

### Check for duplicate trades before any cleanup
**Always run this SELECT first — never run a DELETE without seeing these results first.**

```sql
select backtest_run, pair, direction, opened_at::date, count(*) as dupes
from trades
where source = 'backfill'
group by backtest_run, pair, direction, opened_at::date
having count(*) > 1
order by dupes desc;
```

If it returns zero rows, no duplicates exist. If it returns rows, paste the output and investigate before deleting anything.

### Wipe a backfill run completely
```sql
update signals set trade_id = null where backtest_run = 'your-run-label';
delete from trades where backtest_run = 'your-run-label';
delete from signals where backtest_run = 'your-run-label';
```
