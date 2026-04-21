"""
Bill & Payment Image Detection Webhook App
Flask application with:
  - Telegram bot webhook (image detection + /register + /order)
  - Web dashboard with 2FA login (OTP via Telegram)
  - REST API for records & statistics
"""
import os
import uuid
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, send_from_directory, \
    session, redirect, url_for
from flask_cors import CORS
from dotenv import load_dotenv

from ocr_engine import extract_text, extract_text_with_confidence
from classifier import classify_image
from database import init_db, insert_record, get_records, get_statistics, \
    get_record_by_id, delete_record, update_record_note, add_note, \
    get_notes_for_record, get_orders_for_record
from auth import login_step1, login_step2, verify_session, logout
from telegram_bot import handle_update

load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-me')
CORS(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff'}


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ─── Auth Middleware ────────────────────────────────────────────────────────────

def login_required(f):
    """Decorator to require authentication for web routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = session.get('auth_token')
        if not token:
            # Check header token for API calls
            token = request.headers.get('Authorization', '').replace('Bearer ', '')

        if not token:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'status': 'error', 'error': 'Unauthorized'}), 401
            return redirect(url_for('login_page'))

        user = verify_session(token)
        if not user:
            session.pop('auth_token', None)
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'status': 'error', 'error': 'Invalid session'}), 401
            return redirect(url_for('login_page'))

        request.current_user = user
        return f(*args, **kwargs)
    return decorated


# ─── Auth Pages & API ──────────────────────────────────────────────────────────

@app.route('/login')
def login_page():
    """Render login page."""
    if session.get('auth_token') and verify_session(session['auth_token']):
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Step 1: Verify credentials and send OTP to Telegram."""
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'error': 'Invalid request'}), 400

    result = login_step1(data.get('username', ''), data.get('password', ''))

    if result['success']:
        return jsonify({
            'status': 'success',
            'message': result['message'],
            'requires_otp': True,
        })
    return jsonify({'status': 'error', 'error': result['message']}), 401


@app.route('/api/auth/verify', methods=['POST'])
def api_verify_otp():
    """Step 2: Verify OTP code and create session."""
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'error': 'Invalid request'}), 400

    result = login_step2(data.get('username', ''), data.get('otp', ''))

    if result['success']:
        session['auth_token'] = result['token']
        return jsonify({
            'status': 'success',
            'message': result['message'],
            'user': result['user'],
        })
    return jsonify({'status': 'error', 'error': result['message']}), 401


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """Logout and destroy session."""
    token = session.pop('auth_token', None)
    if token:
        logout(token)
    return jsonify({'status': 'success', 'message': 'Logged out'})


@app.route('/api/auth/me', methods=['GET'])
@login_required
def api_me():
    """Get current user info."""
    return jsonify({'status': 'success', 'user': request.current_user})


# ─── Dashboard (Protected) ─────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    """Render the statistics dashboard."""
    return render_template('dashboard.html')


@app.route('/reports')
@login_required
def reports_page():
    """Render the detailed reports page."""
    return render_template('reports.html')


# ─── Telegram Bot Webhook ──────────────────────────────────────────────────────

@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """
    Telegram Bot webhook endpoint.
    Set this URL in your bot via:
      https://api.telegram.org/bot<TOKEN>/setWebhook?url=<YOUR_DOMAIN>/telegram/webhook
    """
    update = request.get_json()
    if update:
        try:
            handle_update(update)
        except Exception as e:
            print(f"❌ Telegram webhook error: {e}")
    return jsonify({'ok': True})


# ─── Image Webhook (API) ───────────────────────────────────────────────────────

@app.route('/api/webhook', methods=['POST'])
def webhook():
    """
    Webhook endpoint to receive and classify images.

    Accepts:
        - multipart/form-data with 'image' file field
        - Optional 'note' text field
        - Optional 'save' field ('true' to save record immediately)

    Returns:
        JSON with classification results and extracted data
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided', 'status': 'error'}), 400

    file = request.files['image']
    if file.filename == '' or not file.filename:
        return jsonify({'error': 'No file selected', 'status': 'error'}), 400

    if not allowed_file(file.filename):
        return jsonify({
            'error': f'File type not allowed. Allowed: {", ".join(ALLOWED_EXTENSIONS)}',
            'status': 'error'
        }), 400

    # Save to temp file for OCR processing (not permanent)
    import tempfile
    ext = file.filename.rsplit('.', 1)[1].lower()
    tmp = tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False)
    file.save(tmp.name)
    tmp.close()

    try:
        # OCR + Classification
        ocr_result = extract_text_with_confidence(tmp.name)
        raw_text = ocr_result['text']
        ocr_confidence = ocr_result['confidence']

        classification = classify_image(raw_text)

        # Build record data
        extracted = classification['extracted_data']
        record_data = {
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
            'image_path': None,  # Don't save images
            'note': request.form.get('note', ''),
        }

        # Auto-save if requested
        saved = None
        if request.form.get('save', '').lower() == 'true':
            saved = insert_record(record_data)

        response = {
            'status': 'success',
            'classification': {
                'type': classification['image_type'],
                'confidence': classification['confidence'],
                'matched_keywords': classification['matched_keywords'],
            },
            'ocr': {
                'confidence': ocr_confidence,
                'word_count': ocr_result['word_count'],
                'text_preview': raw_text[:300],
            },
            'extracted_data': extracted,
            'record_data': record_data,
        }

        if saved:
            response['record'] = saved

        return jsonify(response)

    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500
    finally:
        # Always clean up temp file
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


@app.route('/api/webhook/confirm', methods=['POST'])
def webhook_confirm():
    """
    Confirm and save a previously analyzed record.
    Accepts JSON with the record_data from the webhook response.
    """
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'error': 'Invalid request'}), 400

    try:
        saved = insert_record(data)
        return jsonify({'status': 'success', 'record': saved})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ─── Records API (Protected) ──────────────────────────────────────────────────

@app.route('/api/records', methods=['GET'])
@login_required
def api_get_records():
    """Get records with optional filters."""
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    image_type = request.args.get('type', None)
    date_from = request.args.get('from', None)
    date_to = request.args.get('to', None)

    records = get_records(limit, offset, image_type, date_from, date_to)
    return jsonify({'status': 'success', 'records': records, 'count': len(records)})


@app.route('/api/records/<record_id>', methods=['GET'])
@login_required
def api_get_record(record_id):
    """Get a single record by ID with orders/shares."""
    record = get_record_by_id(record_id)
    if not record:
        return jsonify({'status': 'error', 'error': 'Record not found'}), 404

    notes = get_notes_for_record(record_id)
    orders = get_orders_for_record(record_id)
    return jsonify({
        'status': 'success',
        'record': record,
        'notes': notes,
        'orders': orders,
    })


@app.route('/api/records/<record_id>', methods=['DELETE'])
@login_required
def api_delete_record(record_id):
    """Delete a record."""
    success = delete_record(record_id)
    if success:
        return jsonify({'status': 'success', 'message': 'Record deleted'})
    return jsonify({'status': 'error', 'error': 'Record not found'}), 404


@app.route('/api/records/<record_id>/note', methods=['PUT'])
@login_required
def api_update_note(record_id):
    """Update a record's note."""
    data = request.get_json()
    note = data.get('note', '') if data else ''
    success = update_record_note(record_id, note)
    if success:
        return jsonify({'status': 'success', 'message': 'Note updated'})
    return jsonify({'status': 'error', 'error': 'Record not found'}), 404


@app.route('/api/records/<record_id>/notes', methods=['POST'])
@login_required
def api_add_note(record_id):
    """Add a note to a record."""
    data = request.get_json()
    content = data.get('content', '') if data else ''
    if not content:
        return jsonify({'status': 'error', 'error': 'Note content required'}), 400

    note = add_note(record_id, content)
    return jsonify({'status': 'success', 'note': note})


@app.route('/api/statistics', methods=['GET'])
@login_required
def api_get_statistics():
    """Get aggregate statistics."""
    stats = get_statistics()
    return jsonify({'status': 'success', 'statistics': stats})


@app.route('/api/upload-test', methods=['GET'])
@login_required
def upload_test_page():
    """Simple page to test image upload."""
    return render_template('upload_test.html')


# ─── Static Files ──────────────────────────────────────────────────────────────

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve uploaded images."""
    return send_from_directory(UPLOAD_FOLDER, filename)


# ─── Init & Run ────────────────────────────────────────────────────────────────

with app.app_context():
    init_db()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'true').lower() == 'true'
    print(f"\n🚀 MySpending running on http://localhost:{port}")
    print(f"📊 Dashboard: http://localhost:{port}/")
    print(f"🔐 Login: http://localhost:{port}/login")
    print(f"🤖 Telegram webhook: POST http://localhost:{port}/telegram/webhook")
    print(f"📤 API webhook: POST http://localhost:{port}/api/webhook\n")
    app.run(host='0.0.0.0', port=port, debug=debug)
