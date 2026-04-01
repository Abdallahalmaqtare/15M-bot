# 🤖 ABOOD القناص V3.0 - FREE Edition

## بوت تداول ذكي 100% مجاني - لا يحتاج مؤشرات مدفوعة!

### 🆓 ما الجديد في V3.0؟
- ❌ لا حاجة لـ GainzAlgo (مدفوع)
- ❌ لا حاجة لـ LuxAlgo SMC (مدفوع)
- ✅ مؤشر Pine Script مجاني بالكامل (Scoring + Order Blocks)
- ✅ ماسح داخلي كنسخة احتياطية
- ✅ يعمل مع TradingView Plus (اشتراكك الحالي)

### 🚀 النشر على Render.com

#### 1. رفع المشروع على GitHub
```bash
git init
git add .
git commit -m "ABOOD V3.0"
git remote add origin YOUR_REPO_URL
git push -u origin main
```

#### 2. إنشاء الخدمة على Render
1. [render.com](https://render.com) → New → Web Service
2. اربط GitHub repo
3. Start Command: `python bot.py`
4. أضف Environment Variables:
   - `TELEGRAM_BOT_TOKEN` = توكن من @BotFather
   - `TELEGRAM_CHAT_ID` = معرّف القناة
   - `WEBHOOK_SECRET` = `abood_v3_secret`

#### 3. إعداد TradingView
1. افتح TradingView → Pine Editor
2. الصق محتوى `tradingview_indicator.pine`
3. أضفه على شارت EURUSD (فريم 15 دقيقة)
4. أنشئ Alert → اختر "ABOOD القناص V3.0"
5. Webhook URL: `https://YOUR-APP.onrender.com/webhook`
6. كرر لـ GBPUSD و AUDUSD

### 📌 أوامر Telegram
| الأمر | الوصف |
|-------|-------|
| `/start` | تشغيل البوت |
| `/stats` | إحصائيات اليوم |
| `/weekly` | تقرير أسبوعي |
| `/monthly` | تقرير شهري |
| `/overall` | إحصائيات تراكمية |
| `/recent` | آخر 10 إشارات |
| `/pipeline` | الإشارات النشطة |
| `/health` | حالة النظام |
