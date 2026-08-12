# Crypto Telegram Multi-Agent Analyst — V4

بوت Telegram لتحليل أسواق الكريبتو على OKX عبر 5m / 15m / 1h / 4h / 1d / 1w.

## ما الجديد في V4
- CVD proxy مبني على سجل الـTrade Flow اللحظي المخزن محلياً.
- Flow impulse لاكتشاف تسارع ضغط الشراء/البيع.
- Liquidation Pressure Proxy يربط OI المتناقص مع التدفق العدواني وحركة السعر. **هو مؤشر احتمالي وليس بيانات تصفيات مؤكدة من البورصة.**
- Backtest بمعايرة Calibration bins وECE بالإضافة إلى Accuracy وBrier-like score.
- Alert de-duplication: لا يعيد إرسال نفس الإشارة باستمرار؛ يعيد التنبيه عند تغير الاتجاه/الفريم/الجودة بشكل ملموس أو بعد cooldown.
- استمرار جميع V3 Agents: Trend/Dow, Momentum, Wyckoff, SMC, Volatility, Derivatives, OrderFlow.

## أوامر Telegram
- `/analyze BTC`
- `/analyze ETH`
- `/scan`
- `/live`
- `/backtest BTC 1h`

## تشغيل سريع
1. `pip install -r requirements.txt`
2. اضبط `TELEGRAM_BOT_TOKEN` في متغيرات البيئة.
3. `python run.py`

## إعدادات مهمة
- `WATCHLIST=BTC,ETH`
- `ALERT_THRESHOLD=75`
- `ADMIN_CHAT_ID=` لتلقي التنبيهات الدورية.
- `MARKET_DB_PATH=data/market.db`
- `SNAPSHOT_SECONDS=30`

## ملاحظة عن نسب الثقة
النسب داخل `/analyze` Scores تحليلية. أمر `/backtest` يعرض Calibration حتى نقيس لاحقاً هل مستوى ثقة 60/70/80% يطابق النتائج التاريخية فعلاً. لا ينبغي اعتبارها احتمالات إحصائية نهائية قبل جمع بيانات تاريخية كافية ومعايرتها خارج العينة.

## التحقق
- `python -m compileall -q .`
- `python tests_smoke.py`
- `python tests_v3.py`
- `python tests_v4.py`
