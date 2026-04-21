"""
Authentication module with Telegram 2FA.
- Register: username + password + telegramId
- Login: username/password -> send 6-digit code to Telegram -> verify code
"""
import os
import random
import string
import hashlib
import time
from typing import Optional, Dict
import requests
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')

_client: Optional[Client] = None

# In-memory OTP store: { username: { code, expires_at, telegram_id } }
_otp_store: Dict = {}
OTP_EXPIRY_SECONDS = 300  # 5 minutes


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def hash_password(password: str, salt: str = '') -> str:
    """Hash password with salt using SHA-256."""
    if not salt:
        salt = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
    hashed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash."""
    parts = stored_hash.split(':', 1)
    if len(parts) != 2:
        return False
    salt = parts[0]
    return hash_password(password, salt) == stored_hash


def register_user(username: str, password: str, telegram_id: str) -> dict:
    """
    Register a new user.
    Returns: { success: bool, message: str, user?: dict }
    """
    if not username or not password or not telegram_id:
        return {'success': False, 'message': 'Username, password và Telegram ID đều bắt buộc'}

    if len(username) < 3:
        return {'success': False, 'message': 'Username phải có ít nhất 3 ký tự'}

    if len(password) < 6:
        return {'success': False, 'message': 'Password phải có ít nhất 6 ký tự'}

    client = get_client()

    # Check if username exists
    existing = (
        client.table('users')
        .select('id')
        .eq('username', username)
        .execute()
    )
    if existing.data:
        return {'success': False, 'message': 'Username đã tồn tại'}

    # Check if telegram_id exists
    existing_tg = (
        client.table('users')
        .select('id')
        .eq('telegram_id', telegram_id)
        .execute()
    )
    if existing_tg.data:
        return {'success': False, 'message': 'Telegram ID đã được sử dụng'}

    # Create user
    password_hash = hash_password(password)
    result = client.table('users').insert({
        'username': username,
        'password_hash': password_hash,
        'telegram_id': telegram_id,
    }).execute()

    if result.data:
        user = result.data[0]
        # Send welcome message via Telegram
        send_telegram_message(
            telegram_id,
            f"✅ Đăng ký thành công!\n\n"
            f"👤 Username: {username}\n"
            f"🔗 Tài khoản đã được liên kết với Telegram của bạn.\n\n"
            f"Khi đăng nhập, mã OTP 6 số sẽ được gửi đến đây."
        )
        return {
            'success': True,
            'message': 'Đăng ký thành công',
            'user': {
                'id': user['id'],
                'username': user['username'],
                'telegram_id': user['telegram_id'],
            }
        }

    return {'success': False, 'message': 'Lỗi khi tạo tài khoản'}


def login_step1(username: str, password: str) -> dict:
    """
    Step 1: Verify username/password and send OTP to Telegram.
    Returns: { success: bool, message: str, requires_otp?: bool }
    """
    if not username or not password:
        return {'success': False, 'message': 'Username và password đều bắt buộc'}

    client = get_client()
    result = (
        client.table('users')
        .select('*')
        .eq('username', username)
        .execute()
    )

    if not result.data:
        return {'success': False, 'message': 'Username hoặc password không đúng'}

    user = result.data[0]

    if not verify_password(password, user['password_hash']):
        return {'success': False, 'message': 'Username hoặc password không đúng'}

    # Generate 6-digit OTP
    otp_code = ''.join(random.choices(string.digits, k=6))

    # Store OTP
    _otp_store[username] = {
        'code': otp_code,
        'expires_at': time.time() + OTP_EXPIRY_SECONDS,
        'telegram_id': user['telegram_id'],
        'user_id': user['id'],
    }

    # Send OTP via Telegram
    sent = send_telegram_message(
        user['telegram_id'],
        f"🔐 Mã đăng nhập MySpending\n\n"
        f"Mã OTP của bạn:\n`{otp_code}`\n\n"
        f"⏰ Mã có hiệu lực trong {OTP_EXPIRY_SECONDS // 60} phút.\n"
        f"⚠️ Không chia sẻ mã này với bất kỳ ai."
    )

    if not sent:
        return {
            'success': False,
            'message': 'Không thể gửi mã OTP qua Telegram. Kiểm tra Telegram Bot Token.'
        }

    return {
        'success': True,
        'message': 'Mã OTP đã được gửi đến Telegram của bạn',
        'requires_otp': True,
    }


def login_step2(username: str, otp_code: str) -> dict:
    """
    Step 2: Verify OTP code.
    Returns: { success: bool, message: str, token?: str, user?: dict }
    """
    if not username or not otp_code:
        return {'success': False, 'message': 'Username và mã OTP đều bắt buộc'}

    stored = _otp_store.get(username)
    if not stored:
        return {'success': False, 'message': 'Không có yêu cầu OTP nào. Vui lòng đăng nhập lại.'}

    # Check expiry
    if time.time() > stored['expires_at']:
        del _otp_store[username]
        return {'success': False, 'message': 'Mã OTP đã hết hạn. Vui lòng đăng nhập lại.'}

    # Verify code
    if otp_code != stored['code']:
        return {'success': False, 'message': 'Mã OTP không đúng'}

    # Generate session token
    token = hashlib.sha256(
        f"{username}:{time.time()}:{os.urandom(16).hex()}".encode()
    ).hexdigest()

    # Store session in Supabase
    client = get_client()
    client.table('sessions').insert({
        'user_id': stored['user_id'],
        'token': token,
        'username': username,
    }).execute()

    # Clean up OTP
    del _otp_store[username]

    # Notify on Telegram
    send_telegram_message(
        stored['telegram_id'],
        f"✅ Đăng nhập thành công!\n\n"
        f"👤 {username} vừa đăng nhập vào MySpending."
    )

    return {
        'success': True,
        'message': 'Đăng nhập thành công',
        'token': token,
        'user': {
            'id': stored['user_id'],
            'username': username,
        }
    }


def is_telegram_registered(telegram_id: str) -> bool:
    """Check if a telegram_id is linked to any user."""
    client = get_client()
    try:
        existing = client.table('users').select('id').eq('telegram_id', str(telegram_id)).execute()
        return len(existing.data) > 0
    except Exception:
        return False


def verify_session(token: str) -> Optional[dict]:
    """Verify a session token. Returns user info or None."""
    if not token:
        return None

    client = get_client()
    result = (
        client.table('sessions')
        .select('*')
        .eq('token', token)
        .execute()
    )

    if not result.data:
        return None

    session = result.data[0]
    return {
        'user_id': session['user_id'],
        'username': session['username'],
    }


def logout(token: str) -> bool:
    """Delete a session."""
    if not token:
        return False
    client = get_client()
    result = client.table('sessions').delete().eq('token', token).execute()
    return len(result.data or []) > 0


def send_telegram_message(chat_id: str, text: str) -> bool:
    """Send a message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        print(f"⚠️  TELEGRAM_BOT_TOKEN not set. OTP: {text}")
        return True  # Still return True in dev mode so flow continues

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown',
        }, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Telegram send error: {e}")
        return False
