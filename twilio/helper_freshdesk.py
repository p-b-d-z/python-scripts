#!/usr/bin/python3
import http.client
import json
import base64
import os
import redis
import logging

api_key = os.environ.get('FRESHDESK_API_KEY')
domain = os.environ.get('FRESHDESK_DOMAIN', 'tier3.freshdesk.com')
if not api_key:
    raise ValueError('FRESHDESK_API_KEY environment variable is required')

conn = http.client.HTTPSConnection(domain)
logging.basicConfig(level=logging.DEBUG)
# Valkey client for caching
valkey_url = os.environ.get('VALKEY_URL', 'redis://localhost:6379')
redis_client = redis.from_url(valkey_url, decode_responses=True)


def filter_dict(d, fields):
    return {k: v for k, v in d.items() if k in fields}


def reformat_phones(data):
    for item in data:
        # For contacts: direct phone and mobile
        if 'phone' in item and item['phone']:
            item['phone'] = validate_phone_number(item['phone']) or item['phone']
        if 'mobile' in item and item['mobile']:
            item['mobile'] = validate_phone_number(item['mobile']) or item['mobile']
        # For agents: under contact
        if 'contact' in item and isinstance(item['contact'], dict):
            contact = item['contact']
            if 'phone' in contact and contact['phone']:
                contact['phone'] = validate_phone_number(contact['phone']) or contact['phone']
            if 'mobile' in contact and contact['mobile']:
                contact['mobile'] = validate_phone_number(contact['mobile']) or contact['mobile']


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


def freshdesk_create_ticket(details, email='user@example.com'):
    ticket_data = json.dumps(
        {
            'subject': 'IVR Issue Report',
            'description': details,
            'email': email,
            'priority': 1,
            'status': 2,
        }
    )
    headers = {
        'Authorization': 'Basic ' + base64.b64encode((api_key + ':').encode()).decode(),
        'Content-Type': 'application/json',
    }
    conn.request('POST', '/api/v2/tickets', ticket_data, headers)
    response = conn.getresponse()
    return response.status, response.read()


def list_agents():
    headers = {
        'Authorization': 'Basic ' + base64.b64encode((api_key + ':').encode()).decode(),
    }
    conn.request('GET', '/api/v2/agents', headers=headers)
    response = conn.getresponse()
    data = response.read().decode('utf-8')
    fields = [
        'id',  # int
        'available',  # bool
        'last_active_at',  # datetime i.e., 2025-11-13T15:16:36Z
        'contact',  # dict containing active, email, job_title, last_login_at, mobile, name, phone
        'deactivated',  # bool
        'type',  # str
        'freshcaller_agent',  # bool
        'focus_mode',  # bool
    ]
    parsed = json.loads(data) if data else []
    parsed = [filter_dict(item, fields) for item in parsed]
    reformat_phones(parsed)
    return response.status, parsed


def list_companies():
    headers = {
        'Authorization': 'Basic ' + base64.b64encode((api_key + ':').encode()).decode(),
    }
    conn.request('GET', '/api/v2/companies', headers=headers)
    response = conn.getresponse()
    data = response.read().decode('utf-8')
    fields = [
        'id',  # int
        'name',  # str
        'domains',  # list of str
    ]
    parsed = json.loads(data) if data else []
    parsed = [filter_dict(item, fields) for item in parsed]
    reformat_phones(parsed)
    return response.status, parsed


def list_contacts():
    headers = {
        'Authorization': 'Basic ' + base64.b64encode((api_key + ':').encode()).decode(),
    }
    conn.request('GET', '/api/v2/contacts', headers=headers)
    response = conn.getresponse()
    data = response.read().decode('utf-8')
    fields = [
        'id',  # int
        'email',  # str
        'phone',  # str | null
        'name',  # str
        'mobile',  # str | null
    ]
    parsed = json.loads(data) if data else []
    parsed = [filter_dict(item, fields) for item in parsed]
    reformat_phones(parsed)
    return response.status, parsed


def get_contact_metadata(phone):
    """Get metadata for a phone number from cached Freshdesk data"""
    normalized = validate_phone_number(phone)
    if not normalized:
        return {'phone': phone, 'matches': []}

    try:
        agents_data = redis_client.get('freshdesk_agents')
        contacts_data = redis_client.get('freshdesk_contacts')
        agents = json.loads(agents_data) if agents_data else []
        contacts = json.loads(contacts_data) if contacts_data else []
    except Exception as e:
        logging.error(f'Failed to load cached Freshdesk data: {e}')
        return {'phone': normalized, 'matches': []}

    matches = []
    # Check agents
    for agent in agents:
        contact = agent.get('contact', {})
        if contact.get('phone') == normalized or contact.get('mobile') == normalized:
            matches.append(
                {
                    'type': 'agent',
                    'id': agent.get('id'),
                    'name': contact.get('name'),
                    'email': contact.get('email'),
                    'available': agent.get('available'),
                }
            )
    # Check contacts
    for contact in contacts:
        if contact.get('phone') == normalized or contact.get('mobile') == normalized:
            matches.append(
                {
                    'type': 'contact',
                    'id': contact.get('id'),
                    'name': contact.get('name'),
                    'email': contact.get('email'),
                }
            )
    return {'phone': normalized, 'matches': matches}


if __name__ == '__main__':
    print(f'Using domain: {domain}')
    print(f'API key set: {bool(api_key)}')
    print('Listing agents:')
    status, agent_data = list_agents()
    print(f'Status: {status}')
    if isinstance(agent_data, list) and agent_data:
        print(f'Agents found: {len(agent_data)}')
        print('First agent:', agent_data[0])
    else:
        print('No agents or error')

    print('\nListing companies:')
    status, company_data = list_companies()
    print(f'Status: {status}')
    if isinstance(company_data, list) and company_data:
        print(f'Companies found: {len(company_data)}')
        print('First company:', company_data[0])
    else:
        print('No companies or error')

    print('\nListing contacts:')
    status, contact_data = list_contacts()
    print(f'Status: {status}')
    if isinstance(contact_data, list) and contact_data:
        print(f'Contacts found: {len(contact_data)}')
        print('First contact:', contact_data[0])
        for contact in contact_data:
            contact_name = contact['name']
            if contact.get('mobile'):
                print(f'Contact mobile: {contact["mobile"]}')
            if contact.get('phone'):
                print(f'Contact phone: {contact["phone"]}')

    else:
        print('No contacts or error')
