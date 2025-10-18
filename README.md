# Goal Alert Telegram Bot (API-Football)

Canlı maçlarda gol olma ihtimali yükseldiğinde sana Telegram'dan bildirim atar.

## 1) Gerekenler
- **Telegram bot token** (BotFather üzerinden alınır)
- **RapidAPI / API-Football** API anahtarı: https://rapidapi.com/api-sports/api/api-football/
- Bir bilgisayar veya sunucu (Windows, macOS, Linux).

## 2) Kurulum (3 dakikada)

```bash
# 1) Proje klasörüne gir
cd goal_alert_bot

# 2) Sanal ortam oluştur (opsiyonel ama tavsiye)
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3) Bağımlılıkları kur
pip install -r requirements.txt

# 4) Ortam değişkenlerini ayarla
# Linux/macOS (örnek):
export TELEGRAM_BOT_TOKEN="BOT_TOKENIN"
export RAPIDAPI_KEY="RAPIDAPI_ANAHTARIN"
export POLL_INTERVAL_SECONDS=60
export SCORE_THRESHOLD=3.0

# Windows (PowerShell):
# setx TELEGRAM_BOT_TOKEN "BOT_TOKENIN"
# setx RAPIDAPI_KEY "RAPIDAPI_ANAHTARIN"
```

Alternatif: `.env` yerine `config.example.env` dosyasındaki değerleri kopyalayıp elle export edebilirsin.

## 3) Çalıştırma

```bash
python bot.py
```

Botu başlattıktan sonra Telegram’da botuna `/start` yaz. Sonrasında gol ihtimali yüksek gördüğünde otomatik mesaj gelir.

## 4) Nasıl karar veriyor?
Basit bir **heuristic skor** kullanır (tamamen yerelde çalışır):
- **Shots on Goal (kaleyi bulan şut)**, **Total Shots (toplam şut)**,
- **Dangerous Attacks**, **Attacks**, **Ball Possession** (denge/ dengesizlik),
- **Dakika etkisi** (30-44 ve 60-85 arası daha baskın).

Skor `SCORE_THRESHOLD` değerini geçerse bildirim gönderir. `/tune <eşik>` ile hassasiyeti maç sırasında bile değiştirebilirsin.

> Not: API-Football bazı maçlarda istatistiği anlık geç gönderebilir. Bu normaldir. Bot uygun veri bulamadığında maçları atlar.

## 5) Lig filtresi (opsiyonel)
Sadece belirli ligleri takip etmek istersen `LEAGUE_FILTER` değişkenini kullan:
```
LEAGUE_FILTER="England:Premier League,Italy:Serie A,Spain:La Liga"
```

## 6) Barındırma (hosting) önerileri
- **PythonAnywhere / Render / Railway / VPS**: `python bot.py` komutuyla sürekli çalıştır.
- Süreklilik için bir **Supervisor** ya da platformun "background worker" özelliğini kullan.

## 7) Sık Sorulanlar
**S: Kod yazmayı bilmiyorum, gerçekten yapabilir miyim?**  
Evet. Sadece token ve API anahtarını girip `python bot.py` çalıştırman yeterli.

**S: Çok fazla bildirim geliyor / az geliyor.**  
`/tune` komutuyla eşiği değiştir veya `POLL_INTERVAL_SECONDS`, `MINUTE_WINDOW_*` değerlerini güncelle.

**S: Yalnızca Türkiye Süper Lig olsun.**  
`LEAGUE_FILTER="Turkey:Süper Lig"` gibi kullan.

**S: API ücreti olur mu?**  
RapidAPI'de ücretsiz katmanlar var; limitleri aşarsan ücretlendirme olabilir. Kullanımını kontrol et.

---

İyi maçlar! ⚽🔥
