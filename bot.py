import os
import time
import logging
from datetime import datetime, timedelta, timezone

import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Config via environment variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
APISPORTS_KEY = os.getenv("APISPORTS_KEY")  # API-Sports direct key
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
LEAGUE_FILTER = os.getenv("LEAGUE_FILTER", "")  # e.g. "England:Premier League,Italy:Serie A"
MINUTE_WINDOW_START = int(os.getenv("MINUTE_WINDOW_START", "30"))
MINUTE_WINDOW_END = int(os.getenv("MINUTE_WINDOW_END", "85"))
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "3.0"))
ALERT_COOLDOWN_MIN = int(os.getenv("ALERT_COOLDOWN_MIN", "20"))

# --- Logger ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger("goal-alert-bot")

# --- Memory storage ---
SUBSCRIBERS = set()
LAST_ALERT = {}

# --- Helpers ---
def parse_league_filter(filter_str: str):
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
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": APISPORTS_KEY}
    params = {"live": "all"}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    if not r.ok:
        log.error("API error %s: %s", r.status_code, r.text)
    r.raise_for_status()
    return r.json().get("response", [])

def api_get_stats(fixture_id: int):
    url = "https://v3.football.api-sports.io/fixtures/statistics"
    headers = {"x-apisports-key": APISPORTS_KEY}
    params = {"fixture": fixture_id}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    if not r.ok:
        log.error("API stats error %s: %s", r.status_code, r.text)
    r.raise_for_status()
    return r.json().get("response", [])

def safe_stat(stats_list, key):
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
                total += int(val)
    return total

def score_fixture_for_goal(stats_list, minute: int) -> float:
    shots_on_goal = safe_stat(stats_list, "Shots on Goal")
    total_shots = safe_stat(stats_list, "Total Shots")
    dangerous_att = safe_stat(stats_list, "Dangerous Attacks")
    attacks = safe_stat(stats_list, "Attacks")
    possession = safe_stat(stats_list, "Ball Possession")

    sog_norm = shots_on_goal / 6.0
    shots_norm = total_shots / 20.0
    dang_norm = dangerous_att / 100.0
    atk_norm = attacks / 200.0
    poss_norm = (abs(possession - 100) / 100.0) if possession else 0.0

    minute_boost = 0.0
    if 30 <= minute <= 44 or 60 <= minute <= 85:
        minute_boost = 0.5
    elif 45 < minute < 60:
        minute_boost = 0.2

    score = (
        0.45 * sog_norm
        + 0.25 * shots_norm
        + 0.15 * dang_norm
        + 0.10 * atk_norm
        + 0.05 * poss_norm
        + minute_boost
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
    if not TELEGRAM_BOT_TOKEN or not APISPORTS_KEY:
        log.error("Missing TELEGRAM_BOT_TOKEN or APISPORTS_KEY in environment.")
        return

    while True:
        try:
            fixtures = api_get_live_fixtures()
            for f in fixtures:
                fixture = f.get("fixture", {})
                league = f.get("league", {})
                teams = f.get("teams", {})
                goals = f.get("goals", {})
                status = fixture.get("status", {})
                minute = status.get("elapsed") or 0

                if not (MINUTE_WINDOW_START <= minute <= MINUTE_WINDOW_END):
                    continue

                country = league.get("country")
                league_name = league.get("name")
                if not league_allowed(country, league_name):
                    continue

                fixture_id = fixture.get("id")
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
                        f"{home} {hg}-{ag} {away} | {minute}'. dk\n"
                        f"Lig: {country} • {league_name}\n"
                        f"Model skoru: {score} (eşik: {SCORE_THRESHOLD})"
                    )
                    await send_alert(app, text)
        except Exception as e:
            log.error("Poll error: %s", e)

        time.sleep(POLL_INTERVAL_SECONDS)

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in environment.")
    if not APISPORTS_KEY:
        raise SystemExit("Set APISPORTS_KEY (API-Sports key) in environment.")

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("tune", tune))

    async def runner():
        import asyncio
        await application.initialize()
        await application.start()
        await application.updater.start_polling()  # 🔹 Telegram komutlarını dinle
        try:
            await poll_loop(application)  # 🔹 Canlı maç tarama döngüsü
        finally:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

    import asyncio
    asyncio.run(runner())

if __name__ == "__main__":
    main()
