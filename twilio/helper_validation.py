
def validate_phone_number(phone_number):
    """Validate and normalize US phone number to E.164 format (+1XXXXXXXXXX)"""
    if not phone_number:
        return None

    # Check for invalid characters (only digits, spaces, dashes, dots, parentheses, and + allowed)
    allowed_chars = set('0123456789 +-().')
    if not all(c in allowed_chars for c in phone_number):
        return None

    # Remove all non-digit characters except +
    cleaned = ''.join(c for c in phone_number if c.isdigit() or c == '+')

    # Handle different input formats
    if cleaned.startswith('+1'):
        # Already in E.164 format
        if len(cleaned) != 12:  # +1 + 10 digits
            return None
        digits_only = cleaned[2:]
    elif len(cleaned) == 10:
        # 10-digit US number without country code, add +1
        cleaned = '+1' + cleaned
        digits_only = cleaned[2:]
    elif len(cleaned) == 11 and cleaned.startswith('1'):
        # 11-digit number starting with 1, add +
        cleaned = '+' + cleaned
        digits_only = cleaned[2:]
    else:
        return None

    # Ensure all characters are digits
    if not all(c.isdigit() for c in digits_only):
        return None

    # Validate area code (first 3 digits): cannot start with 0 or 1
    if digits_only[0] in ('0', '1'):
        return None

    # Validate exchange code (digits 4-6): cannot start with 0 or 1
    if digits_only[3] in ('0', '1'):
        return None

    return cleaned