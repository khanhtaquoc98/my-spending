"""
OCR Engine module for extracting text from images.
Uses Pytesseract with support for Vietnamese language.
"""
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import os
import re
import signal


def preprocess_image(image: Image.Image) -> Image.Image:
    """
    Preprocess image for better OCR results.
    - Convert to grayscale
    - Enhance contrast
    - Apply sharpening
    - Resize if too small
    """
    # Convert to RGB if needed (handles RGBA, palette, etc.)
    if image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')

    # Force width to 800px max. Smaller size helps Tesseract read giant text (like VPBank amounts).
    width, height = image.size
    target_width = 800
    if width != target_width:
        ratio = target_width / width
        image = image.resize((target_width, int(height * ratio)), Image.LANCZOS)

    # Convert to grayscale
    gray = image.convert('L')

    # Enhance contrast
    enhancer = ImageEnhance.Contrast(gray)
    gray = enhancer.enhance(1.5)

    # Sharpen
    gray = gray.filter(ImageFilter.SHARPEN)

    return gray


def extract_text(image_path: str) -> str:
    """
    Extract text from an image using Tesseract OCR.
    Supports Vietnamese (vie) and English (eng) languages.

    Args:
        image_path: Path to the image file

    Returns:
        Extracted text string
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    image = Image.open(image_path)
    processed = preprocess_image(image)

    # Try with Vietnamese + English first
    try:
        text = pytesseract.image_to_string(
            processed,
            lang='vie+eng',
            config='--psm 4',
            timeout=30
        )
    except pytesseract.TesseractError:
        # Fallback to English only if Vietnamese lang pack not installed
        try:
            text = pytesseract.image_to_string(
                processed,
                lang='eng',
                config='--psm 4',
                timeout=30
            )
        except pytesseract.TesseractError:
            # Last resort - default settings
            text = pytesseract.image_to_string(processed)

    return clean_text(text)


def clean_text(text: str) -> str:
    """Clean and normalize OCR output text."""
    # Remove excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)

    # Strip each line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    return text.strip()


def extract_text_with_confidence(image_path: str) -> dict:
    """
    Extract text with confidence scores from an image.

    Returns:
        dict with 'text', 'confidence', and 'details'
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    image = Image.open(image_path)
    processed = preprocess_image(image)

    try:
        data = pytesseract.image_to_data(
            processed,
            lang='vie+eng',
            config='--psm 4',
            output_type=pytesseract.Output.DICT,
            timeout=30
        )
    except pytesseract.TesseractError:
        try:
            data = pytesseract.image_to_data(
                processed,
                lang='eng',
                config='--psm 4',
                output_type=pytesseract.Output.DICT,
                timeout=30
            )
        except pytesseract.TesseractError:
            data = pytesseract.image_to_data(
                processed,
                output_type=pytesseract.Output.DICT
            )

    # Calculate average confidence
    confidences = [
        int(c) for c in data['conf']
        if str(c).lstrip('-').isdigit() and int(c) > 0
    ]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0

    # Build full text
    words = [
        data['text'][i]
        for i in range(len(data['text']))
        if data['text'][i].strip()
    ]
    full_text = ' '.join(words)

    return {
        'text': clean_text(full_text),
        'confidence': round(avg_confidence, 2),
        'word_count': len(words),
    }
