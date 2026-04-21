"""
Database module using Supabase for storing detected image records and statistics.
"""
import os
import uuid
from typing import Optional
from datetime import datetime, timedelta
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')

_client: Optional[Client] = None


def get_client() -> Client:
    """Get or create Supabase client singleton."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment variables. "
                "Copy .env.example to .env and fill in your Supabase credentials."
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def init_db():
    """
    Verify Supabase connection. Tables should be created via Supabase dashboard
    or migrations. This function just validates connectivity.
    """
    try:
        client = get_client()
        # Simple connectivity check
        client.table('records').select('id').limit(1).execute()
        print("✅ Supabase connection successful")
    except Exception as e:
        print(f"⚠️  Supabase connection check: {e}")
        print("📋 Please create the required tables. See README.md for SQL schema.")


def insert_record(data: dict) -> dict:
    """Insert a new detection record. Returns the new record."""
    client = get_client()
    record = {
        'image_type': data.get('image_type', 'unknown'),
        'amount': data.get('amount'),
        'currency': data.get('currency', 'VND'),
        'sender': data.get('sender'),
        'receiver': data.get('receiver'),
        'transaction_id': data.get('transaction_id'),
        'order_id': data.get('order_id'),
        'platform': data.get('platform'),
        'raw_text': data.get('raw_text'),
        'confidence': data.get('confidence', 0),
        'image_path': data.get('image_path'),
        'note': data.get('note'),
        'id': uuid.uuid4().hex[:6]  # UUID short (6 characters)
    }
    result = client.table('records').insert(record).execute()
    return result.data[0] if result.data else {}


def add_note(record_id: str, content: str) -> dict:
    """Add a note to a record."""
    client = get_client()
    note = {
        'record_id': record_id,
        'content': content,
    }
    result = client.table('notes').insert(note).execute()
    return result.data[0] if result.data else {}


def get_records(limit=50, offset=0, image_type=None, date_from=None, date_to=None):
    """Get detection records with optional filters."""
    client = get_client()
    query = client.table('records').select('*')

    if image_type and image_type != 'all':
        query = query.eq('image_type', image_type)
    if date_from:
        query = query.gte('created_at', date_from)
    if date_to:
        query = query.lte('created_at', date_to)

    query = query.order('created_at', desc=True).range(offset, offset + limit - 1)
    result = query.execute()
    return result.data or []


def get_record_by_id(record_id: str):
    """Get a single record by ID (short UUID string)."""
    client = get_client()
    result = client.table('records').select('*').eq('id', str(record_id)).single().execute()
    return result.data


def get_notes_for_record(record_id: str):
    """Get all notes for a record."""
    client = get_client()
    result = (
        client.table('notes')
        .select('*')
        .eq('record_id', record_id)
        .order('created_at', desc=True)
        .execute()
    )
    return result.data or []


def get_statistics():
    """Get aggregate statistics."""
    client = get_client()
    stats = {}

    # All records
    all_records = client.table('records').select('*').execute()
    records = all_records.data or []

    stats['total_records'] = len(records)

    # Records by type
    type_counts = {}
    type_amounts = {}
    for r in records:
        t = r.get('image_type', 'unknown')
        type_counts[t] = type_counts.get(t, 0) + 1
        amt = r.get('amount') or 0
        type_amounts[t] = type_amounts.get(t, 0) + amt

    stats['by_type'] = [
        {'image_type': k, 'count': v, 'total_amount': type_amounts.get(k, 0)}
        for k, v in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    # Today's records
    today = datetime.now().strftime('%Y-%m-%d')
    stats['today_count'] = sum(
        1 for r in records
        if r.get('created_at', '').startswith(today)
    )

    # This week's records
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    stats['week_count'] = sum(
        1 for r in records
        if r.get('created_at', '') >= week_ago
    )

    # Amount by type
    stats['amount_by_type'] = [
        {'image_type': k, 'total': v}
        for k, v in type_amounts.items() if v > 0
    ]

    # Daily trend (last 30 days)
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    daily = {}
    for r in records:
        date_str = r.get('created_at', '')[:10]
        if date_str >= thirty_days_ago:
            t = r.get('image_type', 'unknown')
            key = (date_str, t)
            daily[key] = daily.get(key, 0) + 1

    stats['daily_trend'] = [
        {'date': k[0], 'image_type': k[1], 'count': v}
        for k, v in sorted(daily.items())
    ]

    return stats


def delete_record(record_id: int) -> bool:
    """Delete a record by ID."""
    client = get_client()
    client.table('notes').delete().eq('record_id', record_id).execute()
    result = client.table('records').delete().eq('id', record_id).execute()
    return len(result.data or []) > 0


def update_record_note(record_id: int, note: str) -> bool:
    """Update a record's note."""
    client = get_client()
    result = (
        client.table('records')
        .update({'note': note})
        .eq('id', record_id)
        .execute()
    )
    return len(result.data or []) > 0


# ─── Orders / Share Bill ────────────────────────────────────────────────────────

def insert_order(data: dict) -> dict:
    """Insert a share-bill order. Returns the new order."""
    client = get_client()
    order = {
        'record_id': data.get('record_id'),
        'telegram_id': data.get('telegram_id'),
        'amount': data.get('amount', 0),
        'description': data.get('description', ''),
    }
    result = client.table('orders').insert(order).execute()
    return result.data[0] if result.data else {}


def get_orders_for_record(record_id: int):
    """Get all share-bill orders for a record/bill."""
    client = get_client()
    result = (
        client.table('orders')
        .select('*')
        .eq('record_id', record_id)
        .order('created_at', desc=True)
        .execute()
    )
    return result.data or []


def get_my_orders(telegram_id: str, limit=20):
    """Get a user's share-bill orders by telegram ID."""
    client = get_client()
    result = (
        client.table('orders')
        .select('*')
        .eq('telegram_id', telegram_id)
        .order('created_at', desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []
