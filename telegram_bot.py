"""
Telegram Bot handler.
Handles:
  - /register: multi-step registration (username -> password -> save with chat_id)
  - /order {bill_id} {amount_expr}: share bill splitting
  - Image messages: OCR + classify + confirm (OK / Retry) inline keyboard
  - Callback queries for OK/Retry buttons
"""
import os
import json
import tempfile
from typing import Optional, Dict
import requests
from dotenv import load_dotenv

from ocr_engine import extract_text_with_confidence
from classifier import classify_image
from database import insert_record, get_record_by_id, insert_order
from auth import register_user, is_telegram_registered

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# In-memory conversation state for multi-step flows
# { chat_id: { step: str, data: dict } }
_conv_state: dict = {}

# Pending OCR results awaiting confirmation
# { "confirm_{chat_id}_{msg_id}": { classification_data } }
_pending_results: dict = {}


# ─── Telegram API Helpers ───────────────────────────────────────────────────────

def send_message(chat_id, text, reply_markup=None, parse_mode='Markdown', reply_to_message_id=None):
    """Send a text message and return response JSON."""
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id
    try:
        res = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
        return res.json()
    except Exception as e:
        print(f"❌ Telegram send error: {e}")
        return None


def answer_callback(callback_query_id, text=''):
    """Answer a callback query (dismiss loading on button)."""
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={
            'callback_query_id': callback_query_id,
            'text': text,
        }, timeout=5)
    except Exception:
        pass


def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode='Markdown'):
    """Edit an existing message."""
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': parse_mode,
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Telegram edit error: {e}")


def download_file(file_id: str) -> Optional[str]:
    """Download a file from Telegram, return local temp path."""
    try:
        # Get file path
        res = requests.get(f"{TELEGRAM_API}/getFile", params={'file_id': file_id}, timeout=10)
        data = res.json()
        if not data.get('ok'):
            return None

        file_path = data['result']['file_path']
        url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

        # Download to temp file
        ext = file_path.rsplit('.', 1)[-1] if '.' in file_path else 'jpg'
        tmp = tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False)
        r = requests.get(url, timeout=30)
        tmp.write(r.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        print(f"❌ Download file error: {e}")
        return None


# ─── Format Helpers ─────────────────────────────────────────────────────────────

TYPE_LABELS = {
    'bank_transfer': '🏦 CKTT (Chuyển khoản / Thanh toán)',
    'momo': '💜 MoMo',
    'shopee': '🟠 Shopee',
    'tiktok': '🎵 TikTok',
    'bill': '🧾 Bill/Hóa đơn',
    'unknown': '❓ Không xác định',
}


def format_amount(amount):
    if not amount:
        return 'N/A'
    return f"{int(amount):,}đ".replace(',', '.')


def format_result(classification: dict, ocr_conf: float) -> str:
    """Format classification result for Telegram message."""
    ctype = classification['image_type']
    label = TYPE_LABELS.get(ctype, ctype)
    conf = classification['confidence']
    ext = classification.get('extracted_data', {})

    lines = [
        f"📸 *Kết quả phân tích*\n",
        f"📋 *Loại:* {label}",
        f"📊 *Độ tin cậy:* {conf:.0f}%",
        f"🔍 *OCR:* {ocr_conf:.0f}%",
    ]

    # Always show amount, format_amount will handle None -> 'N/A'
    lines.append(f"💰 *Số tiền:* {format_amount(ext.get('amount'))}")
    
    if ext.get('sender'):
        lines.append(f"👤 *Người gửi:* {ext['sender']}")
    if ext.get('receiver'):
        lines.append(f"👤 *Người nhận:* {ext['receiver']}")
    if ext.get('transaction_id'):
        lines.append(f"🔖 *Mã GD:* `{ext['transaction_id']}`")
    if ext.get('order_id'):
        lines.append(f"📦 *Mã đơn:* `{ext['order_id']}`")

    if classification.get('matched_keywords'):
        kws = ', '.join(classification['matched_keywords'][:5])
        lines.append(f"\n🏷 *Keywords:* {kws}")

    return '\n'.join(lines)


# ─── Webhook Handler ───────────────────────────────────────────────────────────

def handle_update(update: dict):
    """Main entry point for processing Telegram updates."""
    if 'callback_query' in update:
        handle_callback(update['callback_query'])
        return

    message = update.get('message', {})
    if not message:
        return

    chat_id = message['chat']['id']
    text = message.get('text', '').strip()

    # Check if in conversation flow (registration)
    if chat_id in _conv_state:
        handle_conversation(chat_id, message)
        return

    # Commands
    if text.startswith('/start'):
        handle_start(chat_id)
    elif text.startswith('/register'):
        handle_register_start(chat_id)
    elif text.startswith('/bill'):
        handle_manual_bill(chat_id)
    elif text.startswith('/edit'):
        handle_edit(chat_id, text)
    elif text.startswith('/help'):
        handle_help(chat_id)
    elif text.startswith('/stats'):
        handle_stats(chat_id)
    elif message.get('photo'):
        handle_photo(chat_id, message)
    elif message.get('document') and message['document'].get('mime_type', '').startswith('image/'):
        handle_photo_document(chat_id, message)
    else:
        send_message(chat_id,
            "📸 Gửi hình ảnh để phân tích, hoặc dùng /help để xem các lệnh."
        )


# ─── Command Handlers ──────────────────────────────────────────────────────────

def handle_start(chat_id):
    send_message(chat_id,
        "👋 *Chào mừng đến MySpending!*\n\n"
        "Tôi giúp bạn phân loại hình ảnh bill, chuyển khoản, MoMo, Shopee, TikTok.\n\n"
        "📸 *Gửi hình ảnh* để bắt đầu phân tích\n"
        "📝 `/register` - Đăng ký tài khoản\n"
        "✍️ `/bill` - Ghi chú thủ công\n"
        "📦 `/edit` - Cập nhật/chia bill bằng ID\n"
        "📊 `/stats` - Xem thống kê\n"
        "❓ `/help` - Trợ giúp"
    )


def handle_help(chat_id):
    send_message(chat_id,
        "📖 *Hướng dẫn sử dụng*\n\n"
        "📸 *Gửi hình ảnh* - Phân tích & phân loại ảnh\n\n"
        "📝 `/register` - Đăng ký tài khoản web\n\n"
        "✍️ `/bill` - Tạo dòng phân tích mới thủ công tự gõ số\n\n"
        "📦 `/edit {id} {số tiền/x}` - Chỉnh sửa / Chia bill\n"
        "   VD: `/edit abcdef 500000/3` (chia 500k cho 3)\n"
        "   VD: `/edit abcdef 150000` (phần của tôi 150k)\n\n"
        "📊 `/stats` - Xem thống kê nhanh\n"
    )


# ─── Manual Bill Flow ────────────────────────────────────────────────────────
def handle_manual_bill(chat_id):
    """Start manual bill entry utilizing the existing edit workflow."""
    if not is_telegram_registered(chat_id):
        send_message(chat_id, "🔒 *Chưa đăng ký*\n\nBạn cần đăng ký tài khoản trước.\n\nGõ lệnh `/register [username] [password]` để đăng ký.")
        return

    pending_key = f"confirm_{chat_id}"
    _pending_results[pending_key] = {
        'image_type': 'unknown',
        'amount': 0,
        'currency': 'VND',
        'confidence': 100, 
        'chat_id': str(chat_id),
        'raw_text': 'Manual Input'
    }

    markup = {
        'inline_keyboard': [
            [{'text': '🏦 CKTT (Chuyển khoản / Thanh toán)', 'callback_data': 'edit_type_bank_transfer'}],
            [{'text': '💜 MoMo', 'callback_data': 'edit_type_momo'}],
            [{'text': '🟠 Shopee', 'callback_data': 'edit_type_shopee'}, {'text': '🎵 TikTok', 'callback_data': 'edit_type_tiktok'}],
            [{'text': '🧾 Bill/Hóa đơn', 'callback_data': 'edit_type_bill'}],
            [{'text': '❌ Hủy', 'callback_data': 'edit_cancel'}]
        ]
    }
    res = send_message(chat_id, "✍️ *Tạo thủ công (Bước 1/3)*\n\nChọn phân loại giao dịch:", reply_markup=markup)
    msg_id = res.get('result', {}).get('message_id') if res else None
    
    _conv_state[chat_id] = {'step': 'edit_type', 'data': {'msg_id': msg_id}}


# ─── Registration Flow ─────────────────────────────────────────────────────────

def handle_register_start(chat_id):
    _conv_state[chat_id] = {'step': 'username', 'data': {'telegram_id': str(chat_id)}}
    send_message(chat_id,
        "📝 *Đăng ký tài khoản*\n\n"
        "Bước 1/2: Nhập *username* (ít nhất 3 ký tự):"
    )


def handle_conversation(chat_id, message):
    """Handle multi-step conversation flows."""
    state = _conv_state[chat_id]
    text = message.get('text', '').strip()

    if text.startswith('/cancel'):
        del _conv_state[chat_id]
        send_message(chat_id, "❌ Đã hủy.")
        return

    if state['step'] == 'username':
        if len(text) < 3:
            send_message(chat_id, "⚠️ Username quá ngắn. Nhập lại (ít nhất 3 ký tự):")
            return
        state['data']['username'] = text
        state['step'] = 'password'
        send_message(chat_id,
            f"✅ Username: *{text}*\n\n"
            f"Bước 2/2: Nhập *password* (ít nhất 6 ký tự):"
        )

    elif state['step'] == 'password':
        if len(text) < 6:
            send_message(chat_id, "⚠️ Password quá ngắn. Nhập lại (ít nhất 6 ký tự):")
            return

        state['data']['password'] = text
        result = register_user(
            state['data']['username'],
            state['data']['password'],
            state['data']['telegram_id'],
        )

        del _conv_state[chat_id]

        if result['success']:
            send_message(chat_id,
                f"🎉 *Đăng ký thành công!*\n\n"
                f"👤 Username: `{state['data']['username']}`\n"
                f"🔗 Telegram ID: `{chat_id}`\n\n"
                f"Bạn có thể đăng nhập web bằng username/password.\n"
                f"Mã OTP 6 số sẽ được gửi đến đây khi đăng nhập."
            )
        else:
            send_message(chat_id, f"❌ Lỗi: {result['message']}")

    elif state['step'] == 'edit_amount':
        text_clean = text.replace('.', '').replace(',', '').strip().lower()
        multiplier = 1
        if text_clean.endswith('k'):
            text_clean = text_clean[:-1]
            multiplier = 1000
        elif text_clean.endswith('m'):
            text_clean = text_clean[:-1]
            multiplier = 1000000
            
        try:
            amount = float(text_clean) * multiplier
        except ValueError:
            send_message(chat_id, "⚠️ Số tiền không hợp lệ. Vui lòng nhập số (VD: 50000, 50k, 1m).")
            return
            
        state['data']['amount'] = amount
        state['step'] = 'edit_note'
        
        msg_id = state['data']['msg_id']
        markup = {
            'inline_keyboard': [
                [{'text': '⏭ Bỏ qua', 'callback_data': 'edit_note_skip'}],
                [{'text': '❌ Hủy', 'callback_data': 'edit_cancel'}]
            ]
        }
        edit_message(chat_id, msg_id, f"✍️ *Chỉnh sửa (3/3)*\n\nPhân loại: {TYPE_LABELS.get(state['data']['type'], state['data']['type'])}\nSố tiền: {format_amount(amount)}\n\nHãy reply hoặc nhập **ghi chú** (hoặc nhấn Bỏ qua):", reply_markup=markup)

    elif state['step'] == 'edit_note':
        finalize_edit(chat_id, text)

def finalize_edit(chat_id, note):
    state = _conv_state.get(chat_id)
    if not state: return
    
    pending_key = f"confirm_{chat_id}"
    if pending_key not in _pending_results:
        send_message(chat_id, "⚠️ Dữ liệu đã hết hạn. Vui lòng gửi lại ảnh.")
        del _conv_state[chat_id]
        return
        
    data = state['data']
    _pending_results[pending_key]['image_type'] = data['type']
    _pending_results[pending_key]['amount'] = data['amount']
    _pending_results[pending_key]['note'] = note
    
    msg_id = data['msg_id']
    del _conv_state[chat_id]
    
    classification = {
        'image_type': data['type'],
        'confidence': 100,
        'extracted_data': {
            'amount': data['amount'],
            'note': note
        }
    }
    result_text = format_result(classification, 100)
    if note:
        result_text += f"\n📝 *Ghi chú:* {note}"
    result_text += "\n\n(Đã chỉnh sửa thủ công)"

    confirm_markup = {
        'inline_keyboard': [
            [{'text': '✅ OK - Lưu lại', 'callback_data': f'confirm_ok_{chat_id}'}],
            [{'text': '✏️ Chỉnh sửa lại', 'callback_data': f'confirm_edit_{chat_id}'}],
            [{'text': '❌ Hủy', 'callback_data': f'confirm_retry_{chat_id}'}]
        ]
    }
    edit_message(chat_id, msg_id, result_text, reply_markup=confirm_markup)


# ─── Image Handling ─────────────────────────────────────────────────────────────

def handle_photo(chat_id, message):
    """Handle photo messages."""
    # Get highest resolution photo
    photos = message['photo']
    file_id = photos[-1]['file_id']
    process_image(chat_id, file_id, message.get('message_id'))


def handle_photo_document(chat_id, message):
    """Handle image sent as document."""
    file_id = message['document']['file_id']
    process_image(chat_id, file_id, message.get('message_id'))


def process_image(chat_id, file_id, reply_to_msg_id=None):
    """Download, OCR, classify, and send result with confirm buttons."""
    # Enforce registration
    if not is_telegram_registered(chat_id):
        send_message(chat_id, "🔒 *Chưa đăng ký*\n\nBạn cần đăng ký tài khoản trước khi sử dụng bot.\n\nGõ lệnh `/register [username] [password]` để đăng ký.", reply_to_message_id=reply_to_msg_id)
        return

    # Send loading message as reply
    loading_resp = send_message(chat_id, "⏳ Đang phân tích hình ảnh...", reply_to_message_id=reply_to_msg_id)
    loading_msg_id = loading_resp.get('result', {}).get('message_id') if loading_resp else None

    # Download image
    print(f"📥 Downloading image for chat {chat_id}...")
    tmp_path = download_file(file_id)
    if not tmp_path:
        send_message(chat_id, "❌ Không thể tải hình ảnh. Vui lòng thử lại.")
        return

    try:
        # OCR
        print(f"🔍 Running OCR on {tmp_path}...")
        ocr_result = extract_text_with_confidence(tmp_path)
        raw_text = ocr_result['text']
        ocr_conf = ocr_result['confidence']
        print(f"✅ OCR done: {len(raw_text)} chars, {ocr_conf:.0f}% confidence")

        # Classify
        print(f"📊 Classifying...")
        classification = classify_image(raw_text)
        print(f"✅ Type: {classification['image_type']}, Amount: {classification.get('extracted_data', {}).get('amount')}")

        # Format result
        result_text = format_result(classification, ocr_conf)

        # Store pending result for confirmation
        pending_key = f"confirm_{chat_id}"
        extracted = classification.get('extracted_data', {})
        _pending_results[pending_key] = {
            'image_type': classification['image_type'],
            'amount': extracted.get('amount'),
            'currency': 'VND',
            'sender': extracted.get('sender'),
            'receiver': extracted.get('receiver'),
            'transaction_id': extracted.get('transaction_id'),
            'order_id': extracted.get('order_id'),
            'platform': extracted.get('platform'),
            'raw_text': raw_text,
            'confidence': classification['confidence'],
            'chat_id': str(chat_id),
        }

        # Send with confirm buttons
        confirm_markup = {
            'inline_keyboard': [
                [
                    {'text': '✅ OK - Lưu lại', 'callback_data': f'confirm_ok_{chat_id}'},
                ],
                [
                    {'text': '✏️ Chỉnh sửa', 'callback_data': f'confirm_edit_{chat_id}'},
                    {'text': '❌ Hủy', 'callback_data': f'confirm_retry_{chat_id}'},
                ]
            ]
        }

        # Edit the loading message with result, or send new if edit fails
        if loading_msg_id:
            edit_message(chat_id, loading_msg_id, result_text, reply_markup=confirm_markup)
        else:
            send_message(chat_id, result_text, reply_markup=confirm_markup, reply_to_message_id=reply_to_msg_id)
        print(f"✅ Result sent to chat {chat_id}")

    except Exception as e:
        print(f"❌ Error processing image: {e}")
        if loading_msg_id:
            edit_message(chat_id, loading_msg_id, f"❌ Lỗi phân tích: {str(e)}")
        else:
            send_message(chat_id, f"❌ Lỗi phân tích: {str(e)}", reply_to_message_id=reply_to_msg_id)
    finally:
        # Always clean up temp file - don't save image
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ─── Callback Handlers ─────────────────────────────────────────────────────────

def handle_callback(callback_query):
    """Handle inline keyboard button presses."""
    data = callback_query.get('data', '')
    chat_id = callback_query['message']['chat']['id']
    message_id = callback_query['message']['message_id']
    callback_id = callback_query['id']

    if data.startswith('confirm_ok_'):
        handle_confirm_ok(chat_id, message_id, callback_id)
    elif data.startswith('confirm_retry_'):
        handle_confirm_retry(chat_id, message_id, callback_id)
    elif data.startswith('confirm_edit_'):
        handle_confirm_edit(chat_id, message_id, callback_id)
    elif data.startswith('edit_type_'):
        handle_edit_type(chat_id, message_id, callback_id, data)
    elif data == 'edit_note_skip':
        handle_edit_note_skip(chat_id, message_id, callback_id)
    elif data == 'edit_cancel':
        handle_edit_cancel(chat_id, message_id, callback_id)
    else:
        answer_callback(callback_id, 'Unknown action')


def handle_confirm_ok(chat_id, message_id, callback_id):
    """User confirmed the OCR result - save to database."""
    pending_key = f"confirm_{chat_id}"
    pending = _pending_results.pop(pending_key, None)

    if not pending:
        answer_callback(callback_id, '⚠️ Dữ liệu đã hết hạn')
        return

    answer_callback(callback_id, '✅ Đang lưu...')

    try:
        record = insert_record(pending)
        record_id = record.get('id', '?')
        label = TYPE_LABELS.get(pending['image_type'], pending['image_type'])

        edit_message(chat_id, message_id,
            f"✅ *Đã lưu thành công!*\n\n"
            f"🆔 Record: `#{record_id}`\n"
            f"📋 Loại: {label}\n"
            f"💰 Số tiền: {format_amount(pending.get('amount'))}\n\n"
            f"Dùng `/edit {record_id} {{số tiền}}` để chia bill."
        )
    except Exception as e:
        edit_message(chat_id, message_id, f"❌ Lỗi lưu: {str(e)}")


def handle_confirm_retry(chat_id, message_id, callback_id):
    """User wants to cancel - remove pending and ask for new image."""
    pending_key = f"confirm_{chat_id}"
    _pending_results.pop(pending_key, None)

    answer_callback(callback_id, '❌ Hủy')
    edit_message(chat_id, message_id,
        "❌ *Đã hủy kết quả.*\n\n"
        "📸 Bạn có thể gửi ảnh khác để phân tích."
    )


def handle_confirm_edit(chat_id, message_id, callback_id):
    """User wants to manually edit the values: Step 1 Choose Type."""
    pending_key = f"confirm_{chat_id}"
    if pending_key not in _pending_results:
        answer_callback(callback_id, '⚠️ Dữ liệu đã hết hạn')
        return

    # Enter edit state
    _conv_state[chat_id] = {'step': 'edit_type', 'data': {'msg_id': message_id}}
    
    answer_callback(callback_id, '✏️ Chỉnh sửa')
    markup = {
        'inline_keyboard': [
            [{'text': '🏦 CKTT (Chuyển khoản / Thanh toán)', 'callback_data': 'edit_type_bank_transfer'}],
            [{'text': '💜 MoMo', 'callback_data': 'edit_type_momo'}],
            [{'text': '🟠 Shopee', 'callback_data': 'edit_type_shopee'}, {'text': '🎵 TikTok', 'callback_data': 'edit_type_tiktok'}],
            [{'text': '🧾 Bill/Hóa đơn', 'callback_data': 'edit_type_bill'}],
            [{'text': '❌ Hủy', 'callback_data': 'edit_cancel'}]
        ]
    }
    edit_message(chat_id, message_id, "✍️ *Chỉnh sửa (Bước 1/3)*\n\nChọn phân loại giao dịch:", reply_markup=markup)

def handle_edit_type(chat_id, message_id, callback_id, data):
    if chat_id not in _conv_state or _conv_state[chat_id].get('step') != 'edit_type':
        answer_callback(callback_id, '⚠️ Hết hạn')
        return
        
    image_type = data.replace('edit_type_', '')
    _conv_state[chat_id]['data']['type'] = image_type
    _conv_state[chat_id]['step'] = 'edit_amount'
    
    answer_callback(callback_id, TYPE_LABELS.get(image_type, image_type))
    markup = {
        'inline_keyboard': [[{'text': '❌ Hủy', 'callback_data': 'edit_cancel'}]]
    }
    edit_message(chat_id, message_id, f"✍️ *Chỉnh sửa (Bước 2/3)*\n\nPhân loại: {TYPE_LABELS.get(image_type, image_type)}\n\nHãy nhập **số tiền** (VD: 50000):", reply_markup=markup)

def handle_edit_note_skip(chat_id, message_id, callback_id):
    if chat_id not in _conv_state or _conv_state[chat_id].get('step') != 'edit_note':
        answer_callback(callback_id, '⚠️ Hết hạn')
        return
    answer_callback(callback_id, 'Bỏ qua')
    finalize_edit(chat_id, "")

def handle_edit_cancel(chat_id, message_id, callback_id):
    if chat_id in _conv_state:
        del _conv_state[chat_id]
        
    pending_key = f"confirm_{chat_id}"
    _pending_results.pop(pending_key, None)
    
    answer_callback(callback_id, 'Đã hủy')
    edit_message(chat_id, message_id, "❌ *Đã hủy quá trình thao tác.*")


# ─── Order / Share Bill (now /edit) ─────────────────────────────────────────────────────────

def handle_edit(chat_id, text: str):
    """
    Handle /edit command for bill splitting/updating.
    Formats:
      /edit {bill_id} {total/x}    - split total by x people
      /edit {bill_id} {my_amount}  - direct amount
    """
    parts = text.split()
    if len(parts) < 3:
        send_message(chat_id,
            "📦 *Cách dùng /edit:*\n\n"
            "Chia bill:\n"
            "`/edit {id_bill} {tổng tiền/số người}`\n"
            "VD: `/edit abcdef 600000/3` → 200.000đ\n\n"
            "Số tiền cố định:\n"
            "`/edit {id_bill} {số tiền}`\n"
            "VD: `/edit abcdef 150000` → 150.000đ"
        )
        return

    bill_id_str = parts[1]
    amount_expr = parts[2]

    # bill_id is now uuid short (string)
    bill_id = bill_id_str


    # Check bill exists
    record = get_record_by_id(bill_id)
    if not record:
        send_message(chat_id, f"❌ Không tìm thấy bill #{bill_id}")
        return

    # Parse amount expression
    my_amount = 0
    description = ''

    if '/' in amount_expr:
        # Split format: total/people
        try:
            parts_expr = amount_expr.split('/')
            total = float(parts_expr[0])
            divisor = float(parts_expr[1])
            if divisor == 0:
                send_message(chat_id, "❌ Không thể chia cho 0!")
                return
            my_amount = total / divisor
            description = f"{format_amount(total)} ÷ {int(divisor)} người"
        except (ValueError, IndexError):
            send_message(chat_id, "❌ Định dạng không hợp lệ. VD: `500000/3`")
            return
    else:
        # Direct amount
        try:
            my_amount = float(amount_expr)
            description = f"Số tiền cố định"
        except ValueError:
            send_message(chat_id, "❌ Số tiền không hợp lệ. VD: `150000`")
            return

    # Save order
    bill_label = TYPE_LABELS.get(record.get('image_type', ''), record.get('image_type', ''))

    try:
        order = insert_order({
            'record_id': bill_id,
            'telegram_id': str(chat_id),
            'amount': round(my_amount),
            'description': description,
        })

        send_message(chat_id,
            f"✅ *Đã ghi nhận share bill!*\n\n"
            f"🆔 Bill: `#{bill_id}` ({bill_label})\n"
            f"💰 Phần của bạn: *{format_amount(round(my_amount))}*\n"
            f"📝 {description}\n"
        )
    except Exception as e:
        send_message(chat_id, f"❌ Lỗi: {str(e)}")


# ─── Stats ──────────────────────────────────────────────────────────────────────

def handle_stats(chat_id):
    """Send quick statistics."""
    from database import get_statistics

    try:
        stats = get_statistics()
        lines = [
            f"📊 *Thống kê MySpending*\n",
            f"📦 Tổng records: *{stats['total_records']}*",
            f"📅 Hôm nay: *{stats['today_count']}*",
            f"📆 Tuần này: *{stats['week_count']}*",
        ]

        if stats.get('by_type'):
            lines.append("\n📋 *Theo loại:*")
            for t in stats['by_type']:
                label = TYPE_LABELS.get(t['image_type'], t['image_type'])
                lines.append(f"  {label}: {t['count']} ({format_amount(t.get('total_amount', 0))})")

        send_message(chat_id, '\n'.join(lines))
    except Exception as e:
        send_message(chat_id, f"❌ Lỗi: {str(e)}")
