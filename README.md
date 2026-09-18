# Trendix (CryptoAnalyzer)

برنامهٔ تحت وب برای تحلیل بازار کریپتو، طلا، یورو/دلار و شاخص دلار. رابط فارسی و راست‌چین است؛ قیمت و کندل از صرافی‌ها گرفته می‌شود و روی همان داده تحلیل تکنیکال، چشم‌انداز و هشدار معامله ساخته می‌شود.

> این ابزار آموزشی است، نه توصیهٔ مالی. خروجی مدل تضمین سود نیست.

## امکانات

- داشبورد با نمودار کندل، اندیکاتورها و پیش‌بینی چندلایه
- بازارها، لیست پیگیری، اخبار، بک‌تست و تنظیمات
- چشم‌انداز نوشتاری کوتاه / میان‌مدت / بلندمدت
- صفحهٔ **هشدار معامله**: اسکن چندتایم‌فریم، فیلتر حداقل احتمال موفقیت، بروزرسانی خودکار بدون رفرش صفحه، هشدار صوتی (بعد از فعال‌سازی دستی)
- دارایی‌های کلان: طلا (`XAUUSD`)، یورو/دلار (`EURUSD`)، شاخص دلار (`DXY`)
- بازه‌ها: ۵ دقیقه، ۱۵ دقیقه، ۳۰ دقیقه، ۱ ساعت، ۳ ساعت، ۱ روز، ۱ هفته
- داده: ابتدا Binance، در صورت خطا Bybit و OKX؛ طلا و فارکس در صورت نیاز از Yahoo

## اجرای محلی (سریع)

پایتون **۳.۱۰+** لازم است.

```bash
cd /path/to/Trendix
python3 -m venv .venv
source .venv/bin/activate          # ویندوز: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

مرورگر:

- پیش‌فرض: [http://127.0.0.1:8000](http://127.0.0.1:8000)

اگر پورت ۸۰۰۰ اشغال است (مثلاً روی این سرور معمولاً ۸۰۸۰):

```bash
PORT=8080 HOST=0.0.0.0 python run.py
```

یا مستقیم با uvicorn:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

برای توسعه با ری‌لود خودکار کد (وقتی با `127.0.0.1` اجرا می‌کنی پیش‌فرض روشن است):

```bash
HOST=127.0.0.1 PORT=8000 RELOAD=1 python run.py
```

اگر سرور را با `HOST=0.0.0.0` بالا آورده‌ای و کد عوض شده، **یک‌بار پروسس را بکش و دوباره `python run.py` بزن** تا تغییرات لود شود. بعد در مرورگر hard-refresh کن (`Ctrl+Shift+R`).

این ماشین باید به Binance (یا Bybit/OKX) و برای DXY به Yahoo دسترسی شبکه داشته باشد.

### توقف / ری‌استارت

```bash
# پیدا کردن پروسس
pgrep -af 'uvicorn app.main:app'

# توقف (PID را جایگزین کن)
kill <PID>

# دوباره بالا آوردن
cd /path/to/Trendix
source .venv/bin/activate
PORT=8080 HOST=0.0.0.0 python run.py
```

### Docker

```bash
docker build -t trendix .
docker run --rm -p 8080:8000 -e PORT=8000 trendix
```

سپس: [http://127.0.0.1:8080](http://127.0.0.1:8080)

## صفحهٔ هشدار معامله

1. از منو برو به **هشدار معامله**
2. فیلتر «پیشنهاد اگر احتمال از … بیشتر شد» را بگذار (مثلاً ۵۰٪)
3. برای صدا: دکمهٔ **فعال کردن هشدار صوتی** را بزن و تب را باز نگه دار
4. اسکن حدود هر ۲۰ ثانیه خودش تازه می‌شود؛ نیازی به رفرش صفحه نیست
5. اولین اسکن بعد از استارت ممکن است حدود یک دقیقه طول بکشد؛ اسکن‌های بعدی از کش می‌آیند و سریع‌اند

## استقرار رایگان

فایل‌های `Dockerfile` و `Procfile` داخل ریپو هستند.

### Hugging Face Spaces (پیشنهادی)

1. در [huggingface.co](https://huggingface.co) یک Space جدید بسازید
2. SDK را **Docker** بگذارید
3. این ریپو را وصل کنید یا فایل‌ها را آپلود کنید
4. بعد از بیلد، آدرس عمومی شبیه `https://USERNAME-trendix.hf.space` می‌آید

پلن رایگان ممکن است بعد از بی‌استفاده بودن بخوابد؛ اولین باز شدن کمی طول می‌کشد.

### Render

1. ریپو را به [render.com](https://render.com) وصل کنید
2. نوع سرویس: **Web Service**
3. Build: `pip install -r requirements.txt`
4. Start: `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`

## متغیرهای محیطی

| متغیر | پیش‌فرض | توضیح |
| --- | --- | --- |
| `PORT` | `8000` | پورت HTTP |
| `HOST` | `127.0.0.1` اگر `PORT` ست نشده؛ وگرنه `0.0.0.0` | آدرس bind |
| `RELOAD` | `1` روی localhost، وگرنه `0` | ری‌لود خودکار uvicorn |

## API

| مسیر | توضیح |
| --- | --- |
| `GET /` | رابط کاربری |
| `GET /api/health` | سلامت سرویس و منبع داده |
| `GET /api/coins` | فهرست نمادها |
| `GET /api/ticker?symbol=BTCUSDT` | قیمت لحظه‌ای |
| `GET /api/analysis?symbol=BTCUSDT&interval=1h` | تحلیل یک تایم‌فریم |
| `GET /api/predictions?symbol=BTCUSDT` | پیش‌بینی همهٔ تایم‌فریم‌ها + متن چشم‌انداز |
| `GET /api/alerts?min_odds=50&extra=` | اسکن هشدار؛ `min_odds` حداقل احتمال (۴۰–۷۸)، `extra` نمادهای اضافه با کاما |
| `GET /api/markets` | خلاصهٔ بازار |
| `GET /api/news` | اخبار |
| `GET /api/backtest?...` | بک‌تست |

سلامت سریع:

```bash
curl -s http://127.0.0.1:8080/api/health
```

## ساختار پروژه

```
app/
  main.py                 مسیرهای FastAPI
  config.py               تنظیمات تایم‌فریم و ثابت‌ها
  analysis/               اندیکاتور، evidence، ensemble، alerts، backtest
  data/                   قیمت، کندل، کوین و دارایی‌های کلان
  static/                 CSS، JS، آیکون
  templates/              صفحهٔ اصلی
Dockerfile
Procfile
run.py                    استارتر محلی / کلود
requirements.txt
```

## مجوز

استفادهٔ شخصی و آموزشی. برای تصمیم معامله مسئولیت با خودتان است.
