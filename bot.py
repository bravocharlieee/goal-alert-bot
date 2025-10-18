import os
import time
import logging
from datetime import datetime, timedelta, timezone

import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Config via environment variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")  # API-Football on RapidAPI
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
LEAGUE_FILTER = os.getenv("LEAGUE_FILTER", "")  # e.g. "England:Premier League,Italy:Serie A"
MINUTE_WINDOW_START = int(os.getenv("MINUTE_WINDOW_START", "30"))
MINUTE_WINDOW_END = int(os.getenv("MINUTE_WINDOW_END", "85"))
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "3.0"))  # raise/lower to tune sensitivity

# --- Logger ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger("goal-alert-bot")

# --- Simple in-memory storage ---
SUBSCRIBERS = set()          # chat IDs to notify
LAST_ALERT = {}              # fixture_id -> timestamp of last alert
ALERT_COOLDOWN_MIN = int(os.getenv("ALERT_COOLDOWN_MIN", "20"))

# --- Helpers ---
def parse_league_filter(filter_str: str):
    """
    Convert "Country:League,Country2:League2" to set of tuples {(country, league), ...}
    If empty -> no filter.
    """
    if not filter_str.strip():
        return None
    items = set()
    for token in filter_str.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            c, l = token.split(":", 1)
            items.add((c.strip().lower(), l.strip().lower()))
        else:
            items.add(("", token.strip().lower()))
    return items

LEAGUE_FILTER_PARSED = parse_league_filter(LEAGUE_FILTER)

def league_allowed(country: str, league: str) -> bool:
    if LEAGUE_FILTER_PARSED is None:
        return True
    c = (country or "").lower()
    l = (league or "").lower()
    return (c, l) in LEAGUE_FILTER_PARSED or ("", l) in LEAGUE_FILTER_PARSED

def api_get_live_fixtures():
    """
    Fetch live fixtures from API-Football (RapidAPI).
    Docs: https://rapidapi.com/api-sports/api/api-football/
    Endpoint: /v3/fixtures?live=all
    """
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "api-football-v1.p.rapidapi.com"
    }
    params = {"live": "all"}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("response", [])

def api_get_stats(fixture_id: int):
    """
    Fetch statistics for a fixture.
    Endpoint: /v3/fixtures/statistics?fixture={id}
    """
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures/statistics"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "api-football-v1.p.rapidapi.com"
    }
    params = {"fixture": fixture_id}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("response", [])

def safe_stat(stats_list, team_type, key):
    """
    stats_list: API response for statistics (list of two entries: home & away dicts)
    team_type: "home" or "away" -> index 0/home or 1/away is not guaranteed; we search by team id/name if necessary
    For simplicity, we sum both teams' stat values where applicable.
    """
    total = 0
    for t in stats_list:
        for s in t.get("statistics", []):
            if s.get("type", "").lower() == key.lower():
                val = s.get("value")
                if isinstance(val, str):
                    try:
                        val = int(val.replace("%", "").strip())
                    except:
                        val = 0
                if val is None:
                    val = 0
                if isinstance(val, (int, float)):
                    total += val
    return total

def score_fixture_for_goal(stats_list, minute: int) -> float:
    """
    Heuristic scoring for "goal likely soon". You can tweak coefficients via env if needed.
    Core components we try to use if present:
    - Shots on goal (a.k.a. shots on target)
    - Total shots
    - Dangerous attacks
    - Attacks
    - Possession (high & imbalanced can help)
    """
    # Extract stats (sum home+away where it makes sense)
    shots_on_goal = safe_stat(stats_list, None, "Shots on Goal")
    total_shots   = safe_stat(stats_list, None, "Total Shots")
    dangerous_att = safe_stat(stats_list, None, "Dangerous Attacks")
    attacks       = safe_stat(stats_list, None, "Attacks")
    possession    = safe_stat(stats_list, None, "Ball Possession")  # as percentage sum (≈ 100)

    # Normalize components roughly
    sog_norm = shots_on_goal / 6.0         # 6+ on target combined is hot
    shots_norm = total_shots / 20.0        # 20+ total shots combined is hot
    dang_norm = dangerous_att / 100.0      # 100+ dangerous attacks combined is hot
    atk_norm = attacks / 200.0             # 200+ attacks combined is hot
    poss_norm = (abs(possession - 100) / 100.0) if possession else 0.0  # imbalance

    # Minute pressure curve: favor 30-44 and 60-85 by pushing score up in those ranges
    minute_boost = 0.0
    if 30 <= minute <= 44 or 60 <= minute <= 85:
        minute_boost = 0.5
    elif 45 < minute < 60:
        minute_boost = 0.2

    # Final weighted score
    score = (
        0.45 * sog_norm +
        0.25 * shots_norm +
        0.15 * dang_norm +
        0.10 * atk_norm +
        0.05 * poss_norm +
        minute_boost
    )
    return round(score, 3)

def should_alert(fixture_id: int) -> bool:
    last = LAST_ALERT.get(fixture_id)
    if not last:
        return True
    return (datetime.now(timezone.utc) - last) >= timedelta(minutes=ALERT_COOLDOWN_MIN)

async def send_alert(context: ContextTypes.DEFAULT_TYPE, text: str):
    for chat_id in list(SUBSCRIBERS):
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
        except Exception as e:
            log.warning("Failed to message %s: %s", chat_id, e)

# --- Telegram Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)
    await update.message.reply_text(
        "Merhaba! Canlı maçlarda gol ihtimali yükseldiğinde haber vereceğim.\n"
        "Komutlar:\n"
        "• /start - Bildirimleri aç\n"
        "• /stop - Bildirimleri kapat\n"
        "• /status - Ayarları göster\n"
        "• /tune <eşik> - Duyarlılığı ayarla (örn: /tune 2.8)"
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.discard(update.effective_chat.id)
    await update.message.reply_text("Tamamdır, bildirimleri kapattım. Tekrar açmak için /start.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Aktif aboneler: {len(SUBSCRIBERS)}\n"
        f"Eşik (SCORE_THRESHOLD): {SCORE_THRESHOLD}\n"
        f"Tarama aralığı: {POLL_INTERVAL_SECONDS}s\n"
        f"Zaman penceresi: {MINUTE_WINDOW_START}-{MINUTE_WINDOW_END} dk\n"
        f"Lig filtresi: {LEAGUE_FILTER or 'yok'}"
    )

async def tune(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SCORE_THRESHOLD
    try:
        value = float(context.args[0])
        SCORE_THRESHOLD = value
        await update.message.reply_text(f"Eşik {SCORE_THRESHOLD} olarak güncellendi.")
    except Exception:
        await update.message.reply_text("Kullanım: /tune 2.8")

# --- Main polling loop ---
async def poll_loop(app):
    if not TELEGRAM_BOT_TOKEN or not RAPIDAPI_KEY:
        log.error("Missing TELEGRAM_BOT_TOKEN or RAPIDAPI_KEY in environment.")
        return

    while True:
        try:
            fixtures = api_get_live_fixtures()
            for f in fixtures:
                fixture = f.get("fixture", {})
                league  = f.get("league", {})
                teams   = f.get("teams", {})
                goals   = f.get("goals", {})
                status  = fixture.get("status", {})
                minute  = status.get("elapsed") or 0

                # Filter by minute window
                if not (MINUTE_WINDOW_START <= minute <= MINUTE_WINDOW_END):
                    continue

                country = league.get("country")
                league_name = league.get("name")
                if not league_allowed(country, league_name):
                    continue

                fixture_id = fixture.get("id")
                # Get stats
                stats = api_get_stats(fixture_id)
                if not stats:
                    continue

                score = score_fixture_for_goal(stats, minute)
                if score >= SCORE_THRESHOLD and should_alert(fixture_id):
                    LAST_ALERT[fixture_id] = datetime.now(timezone.utc)
                    home = teams.get("home", {}).get("name", "Home")
                    away = teams.get("away", {}).get("name", "Away")
                    hg = goals.get("home", 0)
                    ag = goals.get("away", 0)

                    text = (
                        f"🔥 Gol İhtimali Yüksek!\n"
                        f"{home} {hg} - {ag} {away}  |  {minute}'. dk\n"
                        f"Lig: {country} • {league_name}\n"
                        f"Skor: {hg}-{ag}\n"
                        f"Model skoru: {score} (eşik: {SCORE_THRESHOLD})\n"
                        f"İpucu: /tune ile eşiği ayarlayabilirsin."
                    )
                    await send_alert(app, text)
        except Exception as e:
            log.error("Poll error: %s", e)

        await app.bot._application.post_stop()  # no-op compatibility guard
        time.sleep(POLL_INTERVAL_SECONDS)

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in environment.")
    if not RAPIDAPI_KEY:
        raise SystemExit("Set RAPIDAPI_KEY (RapidAPI API-Football key) in environment.")

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("tune", tune))

    # Run polling + background task
    # Using application.run_polling() would block; we manually start and run our loop in a thread-like fashion.
    async def runner():
        await application.initialize()
        await application.start()
        try:
            await poll_loop(application)
        finally:
            await application.stop()
            await application.shutdown()

    import asyncio
    asyncio.run(runner())

if __name__ == "__main__":
    main()
