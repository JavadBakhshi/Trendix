# CryptoAnalyzer

برنامهٔ تحت وب برای تحلیل بازار کریپتو، طلا، یورو/دلار و شاخص دلار. رابط فارسی و راست‌چین است؛ قیمت و کندل از صرافی‌ها گرفته می‌شود و روی همان داده تحلیل تکنیکال، چشم‌انداز و هشدار خرید/فروش ساخته می‌شود.

> این ابزار آموزشی است، نه توصیهٔ مالی. خروجی مدل تضمین سود نیست.

## امکانات

- داشبورد با نمودار کندل، اندیکاتورها و پیش‌بینی چندلایه
- بازارها، لیست پیگیری، اخبار و تنظیمات
- چشم‌انداز نوشتاری کوتاه / میان‌مدت / بلندمدت
- صفحهٔ هشدار معامله (بهترین خرید / فروش نسبی)
- دارایی‌های کلان: طلا (`XAUUSD`)، یورو/دلار (`EURUSD`)، شاخص دلار (`DXY`)
- بازه‌ها: ۵ دقیقه، ۱۵ دقیقه، ۳۰ دقیقه، ۱ ساعت، ۳ ساعت، ۱ روز، ۱ هفته
- داده: ابتدا Binance، در صورت خطا Bybit و OKX؛ طلا و فارکس در صورت نیاز از Yahoo

## اجرای محلی

پایتون ۳.۱۰ یا بالاتر لازم است.

```bash
git clone https://github.com/JavadBakhshi/Trendix.git
cd Trendix
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

سپس مرورگر را باز کنید: [http://127.0.0.1:8000](http://127.0.0.1:8000)

اگر پورت عوض شد:

```bash
PORT=8080 HOST=0.0.0.0 python run.py
```

این ماشین باید به Binance (یا Bybit/OKX) و برای DXY به Yahoo دسترسی داشته باشد.

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

## API

| مسیر | توضیح |
| --- | --- |
| `GET /` | رابط کاربری |
| `GET /api/health` | سلامت سرویس و منبع داده |
| `GET /api/coins` | فهرست نمادها |
| `GET /api/ticker?symbol=BTCUSDT` | قیمت لحظه‌ای |
| `GET /api/analysis?symbol=BTCUSDT&interval=1h` | تحلیل یک تایم‌فریم |
| `GET /api/predictions?symbol=BTCUSDT` | پیش‌بینی همهٔ تایم‌فریم‌ها + متن چشم‌انداز |
| `GET /api/alerts` | هشدار خرید/فروش |
| `GET /api/markets` | خلاصهٔ بازار |
| `GET /api/news` | اخبار |

## ساختار پروژه

```
app/
  main.py              مسیرهای FastAPI
  analysis/            اندیکاتور، ساختار بازار، مدل و ensemble
  data/                دریافت قیمت و لیست کوین‌ها
  static/              CSS، JS، آیکون
  templates/           صفحهٔ اصلی
Dockerfile
Procfile
run.py
```

## مجوز

استفادهٔ شخصی و آموزشی. برای تصمیم معامله مسئولیت با خودتان است.
