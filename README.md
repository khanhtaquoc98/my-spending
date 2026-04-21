# 📸 MySpending - Bill & Payment Image Detection Webhook

Webhook app Python + Telegram Bot phân loại hình ảnh bill, chuyển khoản ngân hàng, MoMo, Shopee, TikTok Shop với OCR và dashboard thống kê.

## 🚀 Tính năng

### Telegram Bot
- 📸 **Gửi hình ảnh** → OCR + phân loại → Confirm (OK/Thử lại)
- 📝 `/register` → Đăng ký tài khoản (username + password)
- 📦 `/order {id} {tổng/x}` → Chia bill
- 📊 `/stats` → Xem thống kê nhanh

### Web Dashboard
- 🔐 **Login 2FA** - Username/Password + OTP 6 số qua Telegram
- 📊 Charts thống kê theo loại, theo ngày
- 📋 Danh sách records với filter
- 📤 Upload ảnh test trên web

### Phân loại tự động
- 🏦 Chuyển khoản ngân hàng (VCB, TCB, MBBank, BIDV, ...)
- 💜 MoMo
- 🟠 Shopee
- 🎵 TikTok Shop
- 🧾 Bill / Hóa đơn

## 📋 Yêu cầu

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- Supabase account
- Telegram Bot (tạo qua [@BotFather](https://t.me/BotFather))

### Cài Tesseract (macOS)

```bash
brew install tesseract tesseract-lang
```

## 🗃 Supabase Setup

### 1. Tạo bảng trong Supabase SQL Editor

```sql
-- ─── Users ──────────────────────────────────────────
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    telegram_id TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Sessions ───────────────────────────────────────
CREATE TABLE sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    token TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Records (detected images) ─────────────────────
CREATE TABLE records (
    id BIGSERIAL PRIMARY KEY,
    image_type TEXT NOT NULL DEFAULT 'unknown',
    amount DOUBLE PRECISION,
    currency TEXT DEFAULT 'VND',
    sender TEXT,
    receiver TEXT,
    transaction_id TEXT,
    order_id TEXT,
    platform TEXT,
    raw_text TEXT,
    confidence DOUBLE PRECISION DEFAULT 0,
    image_path TEXT,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Notes ──────────────────────────────────────────
CREATE TABLE notes (
    id BIGSERIAL PRIMARY KEY,
    record_id BIGINT REFERENCES records(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Orders (share bill) ───────────────────────────
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    record_id BIGINT REFERENCES records(id) ON DELETE CASCADE,
    telegram_id TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Indexes ────────────────────────────────────────
CREATE INDEX idx_records_type ON records(image_type);
CREATE INDEX idx_records_created ON records(created_at DESC);
CREATE INDEX idx_notes_record ON notes(record_id);
CREATE INDEX idx_orders_record ON orders(record_id);
CREATE INDEX idx_orders_telegram ON orders(telegram_id);
CREATE INDEX idx_sessions_token ON sessions(token);
CREATE INDEX idx_users_username ON users(username);

-- ─── RLS Policies (simple allow-all for service key) ─
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all" ON users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON sessions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON records FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON notes FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON orders FOR ALL USING (true) WITH CHECK (true);
```

### 2. Config biến môi trường

```bash
cp .env.example .env
```

Sửa file `.env`:
```
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-service-role-key
FLASK_SECRET_KEY=random-secret-string
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

### 3. Setup Telegram Bot Webhook

```bash
# Thay <TOKEN> và <YOUR_DOMAIN>
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<YOUR_DOMAIN>/telegram/webhook"
```

## 🛠 Cài đặt & Chạy

```bash
# Tạo virtual environment
python3 -m venv venv
source venv/bin/activate

# Cài dependencies
pip install -r requirements.txt

# Chạy app
python app.py
```

App chạy tại: `http://localhost:5000`

## 🔗 API Endpoints

| Method | Endpoint | Auth | Mô tả |
|--------|----------|------|--------|
| `GET` | `/login` | ❌ | Trang đăng nhập |
| `POST` | `/api/auth/login` | ❌ | Step 1: verify credentials, gửi OTP |
| `POST` | `/api/auth/verify` | ❌ | Step 2: verify OTP, tạo session |
| `POST` | `/api/auth/logout` | ❌ | Đăng xuất |
| `GET` | `/` | ✅ | Dashboard thống kê |
| `POST` | `/api/webhook` | ❌ | Upload ảnh phân loại (API) |
| `POST` | `/api/webhook/confirm` | ❌ | Confirm & lưu record |
| `GET` | `/api/records` | ✅ | Danh sách records |
| `GET` | `/api/records/:id` | ✅ | Chi tiết record + orders |
| `DELETE` | `/api/records/:id` | ✅ | Xóa record |
| `PUT` | `/api/records/:id/note` | ✅ | Cập nhật ghi chú |
| `GET` | `/api/statistics` | ✅ | Thống kê tổng hợp |
| `POST` | `/telegram/webhook` | ❌ | Telegram Bot webhook |

## 📦 Telegram Commands

| Command | Mô tả |
|---------|--------|
| `/start` | Giới thiệu bot |
| `/register` | Đăng ký tài khoản (username → password) |
| `/order {id} {amount}` | Ghi nhận phần tiền của bạn cho bill |
| `/order {id} {total/x}` | Chia bill cho x người |
| `/stats` | Xem thống kê nhanh |
| `/help` | Hướng dẫn sử dụng |
| *Gửi ảnh* | OCR + phân loại → OK/Thử lại |

## 📊 Flow

```
Telegram:                              Web:
┌─────────────┐                   ┌──────────────┐
│ Gửi ảnh     │                   │ Login        │
│     ↓       │                   │ user/pass    │
│ OCR + Phân  │                   │     ↓        │
│ loại        │                   │ OTP 6 số     │
│     ↓       │                   │ (Telegram)   │
│ OK / Thử lại│                   │     ↓        │
│     ↓       │                   │ Dashboard    │
│ Lưu Supabase│◄────────────────►│ Thống kê     │
└─────────────┘                   └──────────────┘
```
