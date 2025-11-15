from flask import Flask, request, session, Response, render_template_string
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
import requests
import logging
import os
import secrets
from cache import Cache

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# Initialize cache
valkey_url = os.getenv('VALKEY_URL', 'redis://localhost:6379')
cache = Cache(valkey_url)

# Load opt-out numbers from file on startup (migration/initialization)
cache.load_opt_out_from_file()

with open('sms_consent.html', 'r', encoding='utf-8') as file:
    html_consent_content = file.read()

# Configuration
ivr_voice = 'alice'
language = 'en-US'
fallback_numbers = os.getenv('FALLBACK_NUMBERS', '+14802020751').split(',')
agent_session_ttl = int(os.getenv('AGENT_SESSION_TTL', '28800'))  # 8 hours default


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
    validated = validate_phone_number(phone_number)
    if not validated:
        return False
    return cache.is_opted_out(validated)

def add_to_opt_out(phone_number):
    """Add phone number to opt-out list"""
    validated = validate_phone_number(phone_number)
    if not validated:
        return False
    return cache.add_opt_out_number(validated)

def remove_from_opt_out(phone_number):
    """Remove phone number from opt-out list"""
    validated = validate_phone_number(phone_number)
    if not validated:
        return False
    return cache.remove_opt_out_number(validated)

# Agent management functions
def get_active_agents():
    """Get list of active agent phone numbers"""
    return cache.get_active_agents()

def agent_login(phone_number):
    """Log in an agent"""
    validated = validate_phone_number(phone_number)
    if not validated:
        return False
    return cache.agent_login(validated, agent_session_ttl)

def agent_logout(phone_number):
    """Log out an agent"""
    validated = validate_phone_number(phone_number)
    if not validated:
        return False
    return cache.agent_logout(validated)

def is_agent_active(phone_number):
    """Check if agent is active"""
    validated = validate_phone_number(phone_number)
    if not validated:
        return False
    return cache.is_agent_active(validated)

@app.route('/')
def home():
    return render_template_string(html_consent_content)

@app.route('/auth/agent', methods=['GET', 'POST'])
def agent_auth():
    if request.method == 'POST':
        phone_number = request.form.get('phone_number', '').strip()

        if not phone_number:
            return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Agent Login - Error</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; }
                    .error { color: red; }
                    .form-group { margin: 10px 0; }
                    input { padding: 8px; width: 200px; }
                    button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
                    button:hover { background: #0056b3; }
                </style>
            </head>
            <body>
                <h1>Agent Login</h1>
                <p class="error">Please enter a valid phone number.</p>
                <form method="post">
                    <div class="form-group">
                        <label for="phone_number">Phone Number:</label><br>
                        <input type="tel" id="phone_number" name="phone_number" placeholder="+1234567890" required>
                    </div>
                    <button type="submit">Login as Agent</button>
                </form>
            </body>
            </html>
            """)

        # Validate and login agent
        if agent_login(phone_number):
            return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Agent Login - Success</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; }
                    .success { color: green; }
                </style>
            </head>
            <body>
                <h1>Agent Login Successful</h1>
                <p class="success">You are now logged in as an agent.</p>
                <p>You will receive calls when available.</p>
                <p><a href="/auth/agent/logout">Logout</a></p>
            </body>
            </html>
            """)
        else:
            return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Agent Login - Error</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; }
                    .error { color: red; }
                </style>
            </head>
            <body>
                <h1>Agent Login Failed</h1>
                <p class="error">Failed to log you in. Please try again.</p>
                <p><a href="/auth/agent">Try Again</a></p>
            </body>
            </html>
            """)

    # GET request - show login form
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Agent Login</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .form-group { margin: 10px 0; }
            input { padding: 8px; width: 200px; }
            button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
            button:hover { background: #0056b3; }
        </style>
    </head>
    <body>
        <h1>Agent Login</h1>
        <p>Enter your phone number to register as an available agent.</p>
        <form method="post">
            <div class="form-group">
                <label for="phone_number">Phone Number:</label><br>
                <input type="tel" id="phone_number" name="phone_number" placeholder="+1234567890" required>
            </div>
            <button type="submit">Login as Agent</button>
        </form>
    </body>
    </html>
    """)

@app.route('/auth/agent/logout', methods=['GET', 'POST'])
def agent_logout_route():
    if request.method == 'POST':
        phone_number = request.form.get('phone_number', '').strip()
    else:
        # For GET requests, we need a way to identify the agent
        # For now, show a form to enter phone number
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Agent Logout</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .form-group { margin: 10px 0; }
                input { padding: 8px; width: 200px; }
                button { padding: 10px 20px; background: #dc3545; color: white; border: none; cursor: pointer; }
                button:hover { background: #c82333; }
            </style>
        </head>
        <body>
            <h1>Agent Logout</h1>
            <p>Enter your phone number to log out.</p>
            <form method="post">
                <div class="form-group">
                    <label for="phone_number">Phone Number:</label><br>
                    <input type="tel" id="phone_number" name="phone_number" placeholder="+1234567890" required>
                </div>
                <button type="submit">Logout</button>
            </form>
            <p><a href="/auth/agent">Back to Login</a></p>
        </body>
        </html>
        """)

    if phone_number and agent_logout(phone_number):
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Agent Logout - Success</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .success { color: green; }
            </style>
        </head>
        <body>
            <h1>Agent Logout Successful</h1>
            <p class="success">You have been logged out.</p>
            <p><a href="/auth/agent">Login Again</a></p>
        </body>
        </html>
        """)
    else:
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Agent Logout - Error</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .error { color: red; }
            </style>
        </head>
        <body>
            <h1>Agent Logout Failed</h1>
            <p class="error">Failed to log you out. Please try again.</p>
            <p><a href="/auth/agent/logout">Try Again</a></p>
        </body>
        </html>
        """)

@app.route('/incoming/voice', methods=['POST'])
def incoming_voice():
    response = VoiceResponse()
    digit = request.form.get('Digits', '')
    logging.debug(f'/incoming/voice | form: {request.form}')
    call_to = request.form.get('Called', '')
    call_from = request.form.get('From', '')
    logging.info(f'/incoming/voice | From: {call_from} To: {call_to}')
    response.say('Thank you for contacting Tier 3 Consulting!', voice=ivr_voice)
    gather = Gather(num_digits=1, action='/incoming/voice/menu', method='POST')
    gather.say('Press 1 now to leave a message, or stay on the line and we will connect you with a support agent.', voice=ivr_voice)
    response.append(gather)
    response.say('I will now connect you to an agent, thank you for your patience!', voice=ivr_voice)
    response.dial('+14802020751')

    return Response(str(response), mimetype='text/xml')


@app.route('/incoming/voice/menu', methods=['POST'])
def incoming_voice_menu():
    digit = request.form.get('Digits', '')
    response = VoiceResponse()
    if digit == '1':
        response.say('Please leave your message after the beep. Press any key when you are done.', voice=ivr_voice)
        response.record(
            action='/recording/save',
            max_length=120,
            play_beep=True,
            finish_on_key='any'
        )
    else:
        response.say('I will now connect you to an agent, thank you for your patience!', voice=ivr_voice)

        # Try to connect to an active agent first
        active_agents = get_active_agents()
        if active_agents:
            # Use the first available agent (could implement round-robin later)
            agent_number = active_agents[0]
            logging.info(f'Connecting to active agent: {agent_number}')
            response.dial(agent_number)
        else:
            # Fall back to configured fallback numbers
            logging.info(f'No active agents, using fallback numbers: {fallback_numbers}')
            # Dial the first fallback number (could implement simultaneous dialing later)
            if fallback_numbers:
                response.dial(fallback_numbers[0].strip())

    return Response(str(response), mimetype='text/xml')


@app.route('/recording/save', methods=['POST'])
def recording_complete():
    recording_url = request.form.get('RecordingUrl')
    recording_sid = request.form.get('RecordingSid')
    response = VoiceResponse()
    if recording_url and recording_sid:
        mp3_url = f'{recording_url}.mp3'
        local_filename = f'data/{recording_sid}.mp3'
        # Download recording to local file
        file_data = requests.get(mp3_url).content
        with open(local_filename, 'wb') as f:
            f.write(file_data)

        response.say('Thank you for your message, we will get back to you shortly. Have a great day!', voice=ivr_voice)
        response.hangup()
    else:
        response.say('No recording was received. Goodbye!', voice=ivr_voice)
        response.hangup()
    return Response(str(response), mimetype='text/xml')


@app.route('/incoming/sms', methods=['GET', 'POST'])
def incoming_sms():
    from_number = request.form.get('From', '')
    user_response = request.form.get('Body', '').strip().lower()
    logging.info(f'/incoming/sms | {request.form}')
    logging.info(f'/incoming/sms | [{from_number}] {user_response}')
    resp = MessagingResponse()
    # OPT-IN via "START"
    if user_response == 'start':
        logging.info(f'/incoming/sms | [{from_number}] OPT-IN request')
        if remove_from_opt_out(from_number):
            resp.message('You have been opted back in. Reply STOP to opt out again.')
        else:
            resp.message('Sorry, there was an error processing your request.')

        return Response(str(resp), mimetype='text/xml')

    # OPT-OUT rejection
    if is_opted_out(from_number):
        logging.info(f'/incoming/sms | [{from_number}] Message from OPT-OUT number received.')
        resp.message('Your number has been opted out. Reply with START to opt back in.')

        return Response(str(resp), mimetype='text/xml')

    # OPT-OUT initiation
    if user_response == 'stop':
        logging.info(f'/incoming/sms | [{from_number}] OPT-OUT request')
        if add_to_opt_out(from_number):
            resp.message('You have been opted out. Reply START to opt back in.')
        else:
            resp.message('Sorry, there was an error processing your request.')

        return Response(str(resp), mimetype='text/xml')

    # Continue with existing logic
    logging.info(f'/incoming/sms | session: {session}')
    if 'report' not in session:
        msg = 'Would you like to report an issue? Reply YES or NO.'
        logging.info(f'/incoming/sms | OUTBOUND: {msg}')
        resp.message(msg)
        session['report'] = True
    elif user_response == 'yes':
        msg = 'Please describe your issue. Send as much detail as possible.'
        logging.info(f'/incoming/sms | OUTBOUND: {msg}')
        resp.message(msg)
        session['awaiting_details'] = True
    elif session.get('awaiting_details'):
        report_details = user_response
        # Call your Freshdesk API function here with report_details
        # freshdesk_create_ticket(report_details)
        msg = 'Thank you! Your issue has been reported.'
        logging.info(f'/incoming/sms | OUTBOUND: {msg}')
        resp.message(msg)
        session.clear()
    else:
        msg = 'Let us know if you need help!'
        logging.info(f'/incoming/sms | OUTBOUND: {msg}')
        resp.message(msg)
        session.clear()

    return Response(str(resp), mimetype='text/xml')


@app.route("/status/message", methods=['POST'])
def message_status():
    message_sid = request.values.get('MessageSid', None)
    message_status = request.values.get('MessageStatus', None)
    logging.info(f'SID: {message_sid}, Status: {message_status}')

    return '', 204


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
