"""
Image Classification Engine.
Classifies detected text into image types based on keyword patterns.
Also extracts key data (amount, transaction ID, etc.) from the text.
"""
import re
from typing import Optional, Tuple


# ─── Classification Patterns ───────────────────────────────────────────────────

BANK_KEYWORDS = [
    # Bank names
    'vietcombank', 'vcb', 'techcombank', 'tcb', 'mbbank', 'mb bank',
    'bidv', 'vietinbank', 'acb', 'tpbank', 'vpbank', 'sacombank',
    'hdbank', 'shb', 'ocb', 'msb', 'eximbank', 'lienvietpostbank',
    'agribank', 'dongabank', 'namabank', 'baovietbank', 'kienlongbank',
    'pgbank', 'seabank', 'vibbank', 'vib', 'abbank',
    # Transaction keywords
    'chuyển khoản', 'chuyen khoan', 'giao dịch thành công',
    'giao dich thanh cong', 'chuyển tiền', 'chuyen tien',
    'số tài khoản', 'so tai khoan', 'stk', 'banking',
    'internet banking', 'mobile banking', 'biên lai', 'bien lai',
    'người nhận', 'nguoi nhan', 'người gửi', 'nguoi gui',
    'số tiền', 'so tien', 'nội dung chuyển', 'noi dung chuyen',
    'thành công', 'thanh cong', 'số giao dịch', 'so giao dich',
    'mã giao dịch', 'ma giao dich', 'transfer successful',
]

MOMO_KEYWORDS = [
    'momo', 'ví momo', 'vi momo', 'momo wallet',
    'chuyển tiền momo', 'nạp tiền momo', 'nap tien momo',
    'thanh toán momo', 'thanh toan momo', 'qr momo',
    'm-service', 'mservice', 'ví điện tử momo', 'vi dien tu momo',
    'mã giao dịch momo', 'nhận tiền momo', 'gửi tiền momo',
    'chia tiền', 'chia tien', 'thưởng xu', 'thuong xu',
    'quá trình giao dịch', 'qua trinh giao dich', 'ngân hàng liên kết',
]

SHOPEE_KEYWORDS = [
    'shopee', 'shopee.vn', 'shopee mall', 'shopee express',
    'spx express', 'spx', 'shopeepay', 'shopee pay',
    'đơn hàng shopee', 'don hang shopee', 'mã đơn hàng',
    'ma don hang', 'đang giao', 'dang giao', 'đã giao',
    'da giao', 'chờ xác nhận', 'cho xac nhan',
    'chờ lấy hàng', 'cho lay hang', 'đã hủy', 'da huy',
    'trả hàng', 'tra hang', 'hoàn tiền', 'hoan tien',
    'shopee guarantee', 'đảm bảo shopee',
]

TIKTOK_KEYWORDS = [
    'tiktok', 'tiktok shop', 'tiktokshop', 'tiktok.com',
    'đơn hàng tiktok', 'don hang tiktok', 'tt shop',
    'tiktok seller', 'tiktok express', 'đang vận chuyển tiktok',
    'giao hàng tiktok', 'giao hang tiktok',
]

BILL_KEYWORDS = [
    'hóa đơn', 'hoa don', 'invoice', 'bill', 'receipt',
    'phiếu thu', 'phieu thu', 'biên nhận', 'bien nhan',
    'tổng cộng', 'tong cong', 'total', 'subtotal',
    'thuế', 'thue', 'vat', 'tax', 'giảm giá', 'giam gia',
    'discount', 'thành tiền', 'thanh tien', 'đơn giá', 'don gia',
    'số lượng', 'so luong', 'quantity', 'unit price',
    'thanh toán', 'thanh toan', 'payment',
]

# Priority order for classification (more specific first)
CATEGORIES = [
    ('momo', MOMO_KEYWORDS),
    ('tiktok', TIKTOK_KEYWORDS),
    ('shopee', SHOPEE_KEYWORDS),
    ('bank_transfer', BANK_KEYWORDS),
    ('bill', BILL_KEYWORDS),
]


# ─── Classification ────────────────────────────────────────────────────────────

def classify_image(text: str) -> dict:
    """
    Classify an image based on its OCR text.

    Returns:
        dict with 'image_type', 'confidence', 'matched_keywords', and extracted data
    """
    if not text or not text.strip():
        return {
            'image_type': 'unknown',
            'confidence': 0,
            'matched_keywords': [],
            'extracted_data': {},
        }

    text_lower = text.lower()
    best_type = 'unknown'
    best_score = 0
    best_keywords = []

    for category, keywords in CATEGORIES:
        matched = []
        for kw in keywords:
            if kw in text_lower:
                matched.append(kw)

        # Weight by number of matched keywords relative to total
        if matched:
            score = len(matched) / len(keywords) * 100
            # Bonus for highly specific keywords
            if category == 'momo' and 'momo' in text_lower:
                score += 30
            elif category == 'tiktok' and 'tiktok' in text_lower:
                score += 30
            elif category == 'shopee' and 'shopee' in text_lower:
                score += 30

            if score > best_score:
                best_score = score
                best_type = category
                best_keywords = matched

    # Cap confidence at 100
    confidence = min(best_score, 100)

    # Extract data based on detected type
    extracted = extract_data(text, best_type)

    return {
        'image_type': best_type,
        'confidence': round(confidence, 2),
        'matched_keywords': best_keywords,
        'extracted_data': extracted,
    }


# ─── Data Extraction ───────────────────────────────────────────────────────────

def extract_amount(text: str, image_type: str = 'unknown') -> Optional[float]:
    """Extract monetary amount from text based on patterns and image type."""
    patterns = [
        # Priority 1: Labeled amounts (số tiền: xxx, chuyển tiền: xxx, thanh toán: xxx)
        r'(?:số tiền|so tien|amount|tổng cộng|tong cong|thanh toán|thanh toan|thành tiền|thanh tien|chuyển tiền|chuyen tien|chuyén tién)[:\s]*[-+]?\s*(\d[\d\s.,]*\d)\s*(?:đ|d|vn[dđpo]|dong|đồng)?',
        # Priority 2: Fallback labels with pure numbers (Thành công 1 000 000, Thành Công Ô 1000000)
        r'(?:thành công|thanh cong|tổng|total)[^\d]{0,10}[-+]?\s*(\d[\d\s.,]*\d|\d+)\s*(?:đ|d|vn[dđpo]|dong|đồng)?',
        # Priority 3: Vietnamese format with space separators: 1 000 000 đ, -24 000 đ
        r'[-+]?\s*(\d{1,3}(?:\s\d{3})+)\s*(?:đ|d|vn[dđpo]|dong|đồng)',
        # Priority 4: Vietnamese format with dot/comma: 1.000.000đ, 1,000,000đ, -24.000đ
        r'[-+]?\s*(\d{1,3}(?:[.,]\d{3})+)\s*(?:đ|d|vn[dđpo]|dong|đồng)',
        # Priority 5: space-separated numbers that look like thousands but MUST BE ON OWN LINE
        r'(?:\A|\n)\s*[-+]?\s*(\d{1,3}(?:\s\d{3}){1,})\s*(?:\n|\Z)'
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text.lower())
        if matches:
            amounts = []
            for m in matches:
                # Normalize: remove spaces, dots, commas
                num_str = m.replace(' ', '').replace('.', '').replace(',', '')
                try:
                    val = float(num_str)
                    if val >= 1000:  # Filter out small numbers that aren't amounts
                        amounts.append(val)
                except ValueError:
                    continue
            if amounts:
                if image_type in ('shopee', 'tiktok', 'bill'):
                    # For shopping/food bills, the final amount is usually at the end of the receipt 
                    # (after subtotal and discounts)
                    return amounts[-1]
                else:
                    # For bank transfers, usually the largest number is the transfer amount 
                    # (ignoring smaller fees)
                    return max(amounts)
    return None


def extract_transaction_id(text: str) -> Optional[str]:
    """Extract transaction/order ID from text."""
    patterns = [
        r'(?:mã giao dịch|ma giao dich|transaction)[:\s]*([A-Za-z0-9]+)',
        r'(?:mã đơn|ma don|order)[:\s]*([A-Za-z0-9]+)',
        r'(?:FT\d{10,})',
        r'(?:MGD|TXN)[:\s]*(\d+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1) if match.lastindex else match.group(0)

    return None


def extract_order_id(text: str) -> Optional[str]:
    """Extract order ID (Shopee/TikTok specific)."""
    patterns = [
        r'(?:mã đơn hàng|ma don hang|order id|đơn hàng)[:\s#]*([A-Za-z0-9]+)',
        r'(\d{12,20})',  # Long numeric IDs common in e-commerce
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1) if match.lastindex else match.group(0)

    return None


def extract_sender_receiver(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract sender and receiver names/accounts."""
    sender = None
    receiver = None

    sender_patterns = [
        r'(?:người gửi|nguoi gui|from|sender)[:\s]*(.+?)(?:\n|$)',
        r'(?:tài khoản gửi|tk gui)[:\s]*(.+?)(?:\n|$)',
    ]
    receiver_patterns = [
        r'(?:người nhận|nguoi nhan|to|receiver|beneficiary)[:\s]*(.+?)(?:\n|$)',
        r'(?:tài khoản nhận|tk nhan)[:\s]*(.+?)(?:\n|$)',
    ]

    for pattern in sender_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            sender = match.group(1).strip()
            break

    for pattern in receiver_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            receiver = match.group(1).strip()
            break

    return sender, receiver


def extract_data(text: str, image_type: str) -> dict:
    """Extract structured data based on image type."""
    data = {}

    # Amount extraction (common to all types)
    amount = extract_amount(text, image_type)
    if amount:
        data['amount'] = amount

    if image_type == 'bank_transfer':
        tid = extract_transaction_id(text)
        if tid:
            data['transaction_id'] = tid
        sender, receiver = extract_sender_receiver(text)
        if sender:
            data['sender'] = sender
        if receiver:
            data['receiver'] = receiver
        data['platform'] = 'bank'

    elif image_type == 'momo':
        tid = extract_transaction_id(text)
        if tid:
            data['transaction_id'] = tid
        sender, receiver = extract_sender_receiver(text)
        if sender:
            data['sender'] = sender
        if receiver:
            data['receiver'] = receiver
        data['platform'] = 'momo'

    elif image_type == 'shopee':
        oid = extract_order_id(text)
        if oid:
            data['order_id'] = oid
        data['platform'] = 'shopee'

    elif image_type == 'tiktok':
        oid = extract_order_id(text)
        if oid:
            data['order_id'] = oid
        data['platform'] = 'tiktok'

    elif image_type == 'bill':
        data['platform'] = 'bill'

    return data
