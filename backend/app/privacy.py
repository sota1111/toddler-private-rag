import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def redact_pii(text: Optional[str]) -> str:
    """
    OCRテキスト中のPIIらしきパターンをマスクする（ベストエフォート）。
    """
    if not text:
        return ""

    # 1. Email
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    text = re.sub(email_pattern, '[REDACTED_EMAIL]', text)

    # 2. My Number (12 digits, optional hyphens)
    # 4-4-4 or 12 digits
    # Use lookarounds instead of \b for Japanese text compatibility
    my_number_pattern = r'(?<!\d)(?:\d{4}-\d{4}-\d{4}|\d{12})(?!\d)'
    text = re.sub(my_number_pattern, '[REDACTED_ID]', text)

    # 3. Phone Number (Japan)
    # Fixed: 0X-XXXX-XXXX, 0XX-XXX-XXXX, 0XXX-XX-XXXX, 0XXXX-X-XXXX
    # Mobile: 070/080/090-XXXX-XXXX
    # Free Dial: 0120-XXX-XXX (3 or 4 digits at end)
    phone_patterns = [
        r'(?<!\d)0\d{1,4}-\d{1,4}-\d{3,4}(?!\d)',   # Hyphenated (3-4 at end)
        r'(?<!\d)0[789]0\d{8}(?!\d)',               # Mobile no hyphen
        r'(?<!\d)0[1-9]\d{8,9}(?!\d)',              # Fixed/Other no hyphen
    ]
    for pattern in phone_patterns:
        text = re.sub(pattern, '[REDACTED_PHONE]', text)

    # 4. Bank Account Number (7-8 digits)
    # Search for "口座" nearby (within 10 chars) + 7-8 digits
    def bank_near_keyword_replacer(match):
        # match.group(0) is the whole thing (keyword + number)
        # match.group(1) is the number
        full = match.group(0)
        num = match.group(1)
        return full.replace(num, '[REDACTED_ACCOUNT]')
    
    bank_pattern_near_keyword = r'口座[^\d]{0,10}(\d{7,8})(?!\d)'
    text = re.sub(bank_pattern_near_keyword, bank_near_keyword_replacer, text)
    
    # Standalone 7-8 digits
    standalone_bank_pattern = r'(?<!\d)\d{7,8}(?!\d)'
    def bank_replacer(match):
        val = match.group(0)
        # Avoid redacting things that look like years (20XX, 19XX)
        if len(val) == 8 and (val.startswith('20') or val.startswith('19')):
            return val
        return '[REDACTED_ACCOUNT]'
    
    text = re.sub(standalone_bank_pattern, bank_replacer, text)

    return text
