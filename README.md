# Goal Alert Telegram Bot (API-Sports direct)

Bu sürüm RapidAPI kullanmaz; **API-Sports (API-FOOTBALL)** ile doğrudan konuşur.

## Gerekli anahtarlar
- `TELEGRAM_BOT_TOKEN` (BotFather)
- `APISPORTS_KEY` (https://api-sports.io → API-FOOTBALL)

## Çalıştırma (Render)
- Build: `pip install -r requirements.txt`
- Start: `python bot.py`

## Ayarlar (Env)
- `POLL_INTERVAL_SECONDS` (60)
- `SCORE_THRESHOLD` (3.0)
- `MINUTE_WINDOW_START` / `MINUTE_WINDOW_END` (30–85)
- `ALERT_COOLDOWN_MIN` (20)
- `LEAGUE_FILTER` (örn. `Turkey:Süper Lig,England:Premier League`)

## Komutlar
- `/start`, `/stop`, `/status`, `/tune <eşik>`
