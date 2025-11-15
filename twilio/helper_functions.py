import time
import logging
from datetime import datetime, timezone, timedelta
from cache import Cache
from helper_slack import post_agent_login, post_agent_logout

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


def format_datetime(timestamp):
    """Format timestamp to 'Nov 25 10:12am' in AZ MST"""
    if timestamp <= 0:
        return 'Never'
    # Convert to AZ MST (UTC-7)
    dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    dt_mst = dt_utc.astimezone(timezone(timedelta(hours=-7)))
    formatted = dt_mst.strftime('%b %d %I:%M%p')
    # Remove leading zero from hour
    parts = formatted.split()
    hour_min = parts[2].split(':')
    hour = hour_min[0].lstrip('0') or '12'
    minute_ampm = hour_min[1]
    minute = minute_ampm[:-2]
    ampm = minute_ampm[-2:]
    parts[2] = f'{hour}:{minute}{ampm}'
    formatted = ' '.join(parts)
    return formatted.replace('AM', 'am').replace('PM', 'pm')


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

    success = cache.agent_login(validated, agent_session_ttl, email)
    if success:
        post_agent_login(validated, email)
    return success


def agent_logout(phone_number):
    """Log out an agent"""
    if not cache:
        return False

    validated = validate_phone_number(phone_number)
    if not validated:
        return False

    # Get email before logout
    agent_info = cache.get_agent_info(validated)
    email = agent_info.get('email') if agent_info else None

    success = cache.agent_logout(validated)
    if success:
        post_agent_logout(validated, email)
    return success


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
                    duration = f'{duration_seconds} seconds'
                elif duration_seconds < 3600:
                    minutes = duration_seconds // 60
                    seconds = duration_seconds % 60
                    duration = f'{minutes} minute{"s" if minutes != 1 else ""}'
                    if seconds > 0:
                        duration += f' {seconds} second{"s" if seconds != 1 else ""}'
                else:
                    hours = duration_seconds // 3600
                    minutes = (duration_seconds % 3600) // 60
                    duration = f'{hours} hour{"s" if hours != 1 else ""}'
                    if minutes > 0:
                        duration += f' {minutes} minute{"s" if minutes != 1 else ""}'

                # Format login time
                login_time = format_datetime(login_timestamp)

                agents.append(
                    {
                        'index': index,
                        'name': obfuscate_email(agent_info.get('email', f'Agent {index}')),
                        'phone': obfuscate_phone(phone),
                        'real_phone': phone,
                        'login_time': login_time,
                        'duration': duration,
                    }
                )

        return agents

    except Exception as e:
        logging.error(f'Error getting agent status: {e}')
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
        logging.error(f'Error checking email login: {e}')
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
        logging.error(f'Error getting phone by email: {e}')
        return None


def select_agent():
    """Select the best agent based on metrics"""
    if not cache:
        return None

    try:
        active_phones = cache.get_active_agents()
        if not active_phones:
            return None

        # Get metrics for each agent
        agent_scores = []
        for phone in active_phones:
            # Ensure metrics exist for existing agents
            cache.init_agent_metrics(phone, 28800)
            metrics = cache.get_agent_metrics(phone)
            if metrics:
                calls = metrics.get('calls_count', 0)
                last_time = metrics.get('last_call_time', 0)
            else:
                # Fallback, though init should have created
                calls = 0
                last_time = 0
            agent_scores.append((phone, calls, last_time))

        # Sort by calls (asc), then last_time (asc)
        agent_scores.sort(key=lambda x: (x[1], x[2]))

        selected_phone = agent_scores[0][0]
        logging.info(f'Selected agent {selected_phone} with {agent_scores[0][1]} calls')
        return selected_phone
    except Exception as e:
        logging.error(f'Error selecting agent: {e}')
        return None


def record_agent_call(phone):
    """Record a call to an agent"""
    if not cache:
        return False
    return cache.record_agent_call(phone)


def get_agent_stats_full():
    """Get full agent stats with metrics for authenticated view"""
    if not cache:
        return []

    try:
        active_phones = cache.get_active_agents()
        if not active_phones:
            return []

        agents = []
        current_time = time.time()
        metrics = cache.get_all_agent_metrics()

        for index, phone in enumerate(active_phones, 1):
            agent_info = cache.get_agent_info(phone)
            if agent_info:
                # Calculate duration
                login_timestamp = agent_info.get('login_time', current_time)
                duration_seconds = int(current_time - login_timestamp)

                # Format duration
                if duration_seconds < 60:
                    duration = f'{duration_seconds} seconds'
                elif duration_seconds < 3600:
                    minutes = duration_seconds // 60
                    seconds = duration_seconds % 60
                    duration = f'{minutes} minute{"s" if minutes != 1 else ""}'
                    if seconds > 0:
                        duration += f' {seconds} second{"s" if seconds != 1 else ""}'
                else:
                    hours = duration_seconds // 3600
                    minutes = (duration_seconds % 3600) // 60
                    duration = f'{hours} hour{"s" if hours != 1 else ""}'
                    if minutes > 0:
                        duration += f' {minutes} minute{"s" if minutes != 1 else ""}'

                # Format login time
                login_time = format_datetime(login_timestamp)

                # Get metrics
                agent_metrics = metrics.get(phone, {})
                calls_count = agent_metrics.get('calls_count', 0)
                last_call_timestamp = agent_metrics.get('last_call_time', 0)
                if last_call_timestamp > 0:
                    last_call_time = format_datetime(last_call_timestamp)
                else:
                    last_call_time = 'Never'

                agents.append(
                    {
                        'index': index,
                        'name': agent_info.get('email', f'Agent {index}'),
                        'phone': phone,
                        'login_time': login_time,
                        'duration': duration,
                        'calls_count': calls_count,
                        'last_call_time': last_call_time,
                    }
                )

        return agents

    except Exception as e:
        logging.error(f'Error getting full agent stats: {e}')
        return []
