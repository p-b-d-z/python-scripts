import os
import time
from datetime import datetime
from cache import Cache

# Initialize cache (will be set by call_handler.py)
cache = None
agent_session_ttl = None

def initialize_cache(valkey_url, session_ttl):
    """Initialize the cache instance"""
    global cache, agent_session_ttl
    cache = Cache(valkey_url)
    agent_session_ttl = session_ttl
    # Load opt-out numbers from file on startup (migration/initialization)
    cache.load_opt_out_from_file()

def obfuscate_email(email):
    """Obfuscate email by masking all but first two characters before @"""
    if not email or '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        return f'{local}@{domain}'
    return f'{local[:2]}{"*" * (len(local) - 2)}@{domain}'

def obfuscate_phone(phone):
    """Obfuscate phone by masking all but area code"""
    if not phone or len(phone) < 11:
        return phone
    # Assuming +1XXXXXXXXXX -> +1 (XXX) ***-****
    return f'{phone[:2]} ({phone[2:5]}) ***-****'

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

def is_opted_out(phone_number):
    """Check if phone number is opted out"""
    if not cache:
        return False

    validated = validate_phone_number(phone_number)
    if not validated:
        return False

    return cache.is_opted_out(validated)

def add_to_opt_out(phone_number):
    """Add phone number to opt-out list"""
    if not cache:
        return False

    validated = validate_phone_number(phone_number)
    if not validated:
        return False

    return cache.add_opt_out_number(validated)

def remove_from_opt_out(phone_number):
    """Remove phone number from opt-out list"""
    if not cache:
        return False

    validated = validate_phone_number(phone_number)
    if not validated:
        return False

    return cache.remove_opt_out_number(validated)

def get_active_agents():
    """Get list of active agent phone numbers"""
    if not cache:
        return []

    return cache.get_active_agents()

def agent_login(phone_number, email=None):
    """Log in an agent"""
    if not cache:
        return False

    validated = validate_phone_number(phone_number)
    if not validated:
        return False

    return cache.agent_login(validated, agent_session_ttl, email)

def agent_logout(phone_number):
    """Log out an agent"""
    if not cache:
        return False

    validated = validate_phone_number(phone_number)
    if not validated:
        return False

    return cache.agent_logout(validated)

def is_agent_active(phone_number):
    """Check if agent is active"""
    if not cache:
        return False

    validated = validate_phone_number(phone_number)
    if not validated:
        return False

    return cache.is_agent_active(validated)

def get_agent_status():
    """Get detailed status of all active agents"""
    if not cache:
        return []

    try:
        active_phones = cache.get_active_agents()
        if not active_phones:
            return []

        agents = []
        current_time = time.time()

        for index, phone in enumerate(active_phones, 1):
            agent_info = cache.get_agent_info(phone)
            if agent_info:
                # Calculate duration
                login_timestamp = agent_info.get('login_time', current_time)
                duration_seconds = int(current_time - login_timestamp)

                # Format duration
                if duration_seconds < 60:
                    duration = f"{duration_seconds} seconds"
                elif duration_seconds < 3600:
                    minutes = duration_seconds // 60
                    seconds = duration_seconds % 60
                    duration = f"{minutes} minute{'s' if minutes != 1 else ''}"
                    if seconds > 0:
                        duration += f" {seconds} second{'s' if seconds != 1 else ''}"
                else:
                    hours = duration_seconds // 3600
                    minutes = (duration_seconds % 3600) // 60
                    duration = f"{hours} hour{'s' if hours != 1 else ''}"
                    if minutes > 0:
                        duration += f" {minutes} minute{'s' if minutes != 1 else ''}"

                # Format login time
                login_datetime = datetime.fromtimestamp(login_timestamp)
                login_time = login_datetime.strftime('%Y-%m-%d %H:%M:%S')

                agents.append({
                    'index': index,
                    'name': obfuscate_email(agent_info.get('email', f'Agent {index}')),
                    'phone': obfuscate_phone(phone),
                    'login_time': login_time,
                    'duration': duration
                })

        return agents

    except Exception as e:
        print(f"Error getting agent status: {e}")
        return []

def is_email_logged_in(email):
    """Check if email is associated with an active agent"""
    if not cache or not email:
        return False

    try:
        active_phones = cache.get_active_agents()
        for phone in active_phones:
            agent_info = cache.get_agent_info(phone)
            if agent_info and agent_info.get('email') == email:
                return True
        return False
    except Exception as e:
        print(f"Error checking email login: {e}")
        return False

def get_phone_by_email(email):
    """Get phone number associated with email"""
    if not cache or not email:
        return None

    try:
        active_phones = cache.get_active_agents()
        for phone in active_phones:
            agent_info = cache.get_agent_info(phone)
            if agent_info and agent_info.get('email') == email:
                return phone
        return None
    except Exception as e:
        print(f"Error getting phone by email: {e}")
        return None