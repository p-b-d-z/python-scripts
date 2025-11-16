import requests
import logging
import os
import secrets
import time
import json
import redis
from flask import Flask, request, session, Response, render_template_string, redirect
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
from helper_functions import (
    initialize_cache,
    is_opted_out,
    add_to_opt_out,
    remove_from_opt_out,
    agent_login,
    agent_logout,
    get_agent_status,
    is_email_logged_in,
    get_phone_by_email,
    select_agent,
    record_agent_call,
    get_agent_stats_full,
    format_datetime,
)
from helper_cloudflare import get_cloudflare_user
from helper_slack import upload_voicemail
from helper_freshdesk import get_contact_metadata

logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.static_folder = 'static'

# Initialize cache
valkey_url = os.getenv('VALKEY_URL', 'redis://localhost:6379')
agent_session_ttl = int(os.getenv('AGENT_SESSION_TTL', '28800'))  # 8 hours default
redis_client = redis.from_url(valkey_url, decode_responses=True)
initialize_cache(valkey_url, agent_session_ttl)

# Load Slack users into cache
from helper_slack import load_slack_users

load_slack_users()

# Cache Freshdesk data if API key is set
if os.getenv('FRESHDESK_API_KEY'):
    from helper_freshdesk import list_agents, list_contacts

    try:
        status, agents = list_agents()
        if status == 200:
            redis_client.setex('freshdesk_agents', 86400, json.dumps(agents))
        status, contacts = list_contacts()
        if status == 200:
            redis_client.setex('freshdesk_contacts', 86400, json.dumps(contacts))
        logging.info('Freshdesk data cached successfully')
    except Exception as e:
        logging.error(f'Failed to cache Freshdesk data: {e}')


# Load HTML templates
def load_template(filename):
    """Load HTML template from file"""
    try:
        with open(f'templates/{filename}', 'r', encoding='utf-8') as html_file:
            return html_file.read()

    except Exception as err:
        logging.error(f'Error loading template {filename}: {err}')
        return '<html><body>Error loading template</body></html>'


# Load SMS consent from root directory (existing file)
try:
    with open('sms_consent.html', 'r', encoding='utf-8') as file:
        html_consent_content = file.read()
except Exception as e:
    logging.error(f'Error loading sms_consent.html: {e}')
    html_consent_content = '<html><body>Error loading consent page</body></html>'

agent_login_template = load_template('agent_login.html')
agent_login_error_template = load_template('agent_login_error.html')
agent_login_success_template = load_template('agent_login_success.html')
agent_logout_template = load_template('agent_logout.html')
agent_logout_success_template = load_template('agent_logout_success.html')
agent_error_template = load_template('agent_error.html')
agent_status_template = load_template('agent_status.html')
agent_stats_template = load_template('agent_stats.html')
privacy_policy_template = load_template('privacy_policy.html')

# Configuration
ivr_voice = 'alice'
language = 'en-US'
fallback_numbers = os.getenv('FALLBACK_NUMBERS', '+14802020751').split(',')


@app.route('/')
def home():
    return redirect('/status/agents')


@app.route('/consent')
def consent():
    return render_template_string(html_consent_content)


@app.route('/privacy-policy')
def privacy_policy():
    return render_template_string(privacy_policy_template)


@app.route('/auth/agent', methods=['GET', 'POST'])
def agent_auth():
    whoami = get_cloudflare_user(request)
    logging.info(f'Cloudflare user: {whoami}')
    user_email = whoami.get('email') if whoami else None

    if request.method == 'POST':
        phone_number = request.form.get('phone_number', '').strip()

        if not phone_number:
            return render_template_string(agent_login_error_template)

        # Validate and login agent
        if agent_login(phone_number, user_email):
            return render_template_string(agent_login_success_template)
        else:
            return render_template_string(
                agent_error_template.replace('{{ title }}', 'Agent Login Failed')
                .replace('{{ message }}', 'Failed to log you in. Please try again.')
                .replace('{{ link_url }}', '/auth/agent')
                .replace('{{ link_text }}', 'Try Again')
            )

    # GET request - check if already logged in
    already_logged_in = user_email and is_email_logged_in(user_email)

    # Show login form with conditional content
    return render_template_string(agent_login_template, already_logged_in=already_logged_in, user_email=user_email)


@app.route('/auth/agent/logout', methods=['GET', 'POST'])
def agent_logout_route():
    whoami = get_cloudflare_user(request)
    user_email = whoami.get('email') if whoami else None

    if request.method == 'POST':
        phone_number = request.form.get('phone_number', '').strip()
        # If no phone provided but email, find associated phone
        if not phone_number and user_email:
            phone_number = get_phone_by_email(user_email)
    else:
        # For GET requests, show logout form
        return render_template_string(agent_logout_template)

    if phone_number and agent_logout(phone_number):
        return render_template_string(agent_logout_success_template)
    else:
        return render_template_string(
            agent_error_template.replace('{{ title }}', 'Agent Logout Failed')
            .replace('{{ message }}', 'Failed to log you out. Please try again.')
            .replace('{{ link_url }}', '/auth/agent/logout')
            .replace('{{ link_text }}', 'Try Again')
        )


@app.route('/status')
def status_redirect():
    return redirect('/status/agents')


@app.route('/status/agent')
def status_agent_redirect():
    return redirect('/status/agents')


@app.route('/status/agents')
def agent_status():
    """Display status of all active agents"""
    agents = get_agent_status()
    current_time = format_datetime(time.time())

    # Determine next agent
    next_agent_phone = select_agent()
    next_agent = 'None'
    if next_agent_phone:
        for agent in agents:
            if agent['real_phone'] == next_agent_phone:
                next_agent = agent['name']
                break

    # Render template with agent data
    return render_template_string(
        agent_status_template,
        agents=agents,
        agent_count=len(agents),
        current_time=current_time,
        next_agent=next_agent,
    )


@app.route('/auth/agent/stats')
def agent_stats():
    """Display detailed agent stats for authenticated users"""
    agents = get_agent_stats_full()
    current_time = format_datetime(time.time())

    # Render template with agent data
    return render_template_string(
        agent_stats_template,
        agents=agents,
        agent_count=len(agents),
        current_time=current_time,
    )


@app.route('/incoming/voice', methods=['POST'])
def incoming_voice():
    response = VoiceResponse()
    logging.debug(f'/incoming/voice | form: {request.form}')
    call_sid = request.form.get('CallSid', '')
    call_to = request.form.get('Called', '')
    call_from = request.form.get('From', '')
    logging.info(f'/incoming/voice | CallSid: {call_sid} From: {call_from} To: {call_to}')
    metadata = get_contact_metadata(call_from)
    logging.info(f'Caller metadata: {json.dumps(metadata)}')
    response.say('Thank you for contacting Tier 3 Consulting!', voice=ivr_voice)
    gather = Gather(num_digits=1, action='/incoming/voice/menu', method='POST')
    gather.say(
        'Press 1 now to leave a message, or stay on the line and we will connect you with a support agent.',
        voice=ivr_voice,
    )
    response.append(gather)
    response.say(
        'I will now connect you to an agent, thank you for your patience!',
        voice=ivr_voice,
    )

    # Try to connect to an active agent first
    agent_number = select_agent()
    if agent_number:
        # Record the call
        record_agent_call(agent_number)
        logging.info(f'CallSid: {call_sid} | Connecting to selected agent: {agent_number}')
        response.dial(agent_number)
    else:
        # Fall back to configured fallback numbers
        logging.info(f'CallSid: {call_sid} | No active agents, using fallback numbers: {fallback_numbers}')
        # Dial the first fallback number (could implement simultaneous dialing later)
        if fallback_numbers:
            fallback_number = fallback_numbers[0].strip()
            logging.info(f'CallSid: {call_sid} | Dialing fallback number: {fallback_number}')
            response.dial(fallback_number)

    return Response(str(response), mimetype='text/xml')


@app.route('/incoming/voice/menu', methods=['POST'])
def incoming_voice_menu():
    call_sid = request.form.get('CallSid', '')
    digit = request.form.get('Digits', '')
    response = VoiceResponse()
    if digit == '1':
        logging.info(f'CallSid: {call_sid} | User selected to leave a message')
        response.say(
            'Please leave your message after the beep. Press any key when you are done.',
            voice=ivr_voice,
        )
        response.record(
            action='/recording/save',
            max_length=120,
            play_beep=True,
            finish_on_key='any',
        )
    else:
        logging.info(f'CallSid: {call_sid} | Connecting to agent (no digit pressed)')
        response.say(
            'I will now connect you to an agent, thank you for your patience!',
            voice=ivr_voice,
        )

        # Try to connect to an active agent first
        agent_number = select_agent()
        if agent_number:
            # Record the call
            record_agent_call(agent_number)
            logging.info(f'CallSid: {call_sid} | Connecting to selected agent: {agent_number}')
            response.dial(agent_number)
        else:
            # Fall back to configured fallback numbers
            logging.info(f'CallSid: {call_sid} | No active agents, using fallback numbers: {fallback_numbers}')
            # Dial the first fallback number (could implement simultaneous dialing later)
            if fallback_numbers:
                fallback_number = fallback_numbers[0].strip()
                logging.info(f'CallSid: {call_sid} | Dialing fallback number: {fallback_number}')
                response.dial(fallback_number)

    return Response(str(response), mimetype='text/xml')


@app.route('/recording/save', methods=['POST'])
def recording_complete():
    recording_url = request.form.get('RecordingUrl')
    recording_sid = request.form.get('RecordingSid')
    call_from = request.form.get('From', '')
    call_to = request.form.get('To', '') or request.form.get('Called', '')
    response = VoiceResponse()
    if recording_url and recording_sid:
        mp3_url = f'{recording_url}.mp3'
        local_filename = f'data/recordings/{recording_sid}.mp3'
        # Download recording to local file
        twilio_sid = os.getenv('TWILIO_SID', None)
        twilio_token = os.getenv('TWILIO_TOKEN', None)
        file_data = requests.get(mp3_url, auth=(twilio_sid, twilio_token))
        logging.info(f'Content-Type received: {file_data.headers.get("Content-Type")}')
        with open(local_filename, 'wb') as f:
            f.write(file_data.content)

        # Set ownership if specified
        recording_uid = int(os.getenv('RECORDING_UID', '1000'))
        recording_gid = int(os.getenv('RECORDING_GID', '1000'))
        os.chown(local_filename, recording_uid, recording_gid)
        # Upload to Slack
        logging.info(f'Recording saved to {local_filename}, sending to Slack.')
        upload_voicemail(local_filename, call_from, call_to, time.time())
        response.say(
            'Thank you for your message, we will get back to you shortly. Have a great day!',
            voice=ivr_voice,
        )
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
    metadata = get_contact_metadata(from_number)
    logging.info(f'SMS sender metadata: {json.dumps(metadata)}')
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


@app.route('/status/message', methods=['POST'])
def message_status():
    message_sid = request.values.get('MessageSid', None)
    message_status = request.values.get('MessageStatus', None)
    logging.info(f'SID: {message_sid}, Status: {message_status}')

    return '', 204


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
