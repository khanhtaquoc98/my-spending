# 1. Terminal 1 - Flask server
cd /Users/bo-khanh/Desktop/Src/out/bill
source venv/bin/activate
python app.py
# → http://localhost:5000

# 2. Terminal 2 - Ngrok tunnel  
ngrok http 5000
# → Copy URL https://xxxx.ngrok-free.app

# 3. Set Telegram webhook (1 lần)
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<NGROK_URL>/telegram/webhook"
