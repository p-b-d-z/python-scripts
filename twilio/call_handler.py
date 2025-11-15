from flask import Flask, request, session, Response, render_template_string
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
import requests
import hashlib
import logging
import os
import secrets

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
with open('sms_consent.html', 'r', encoding='utf-8') as file:
    html_consent_content = file.read()

# Opt-out management
OPT_OUT_FILE = 'data/opt_out_numbers.txt'
opt_out_cache = set()
file_hash_cache = None
# Defaults
ivr_voice = 'alice'
language = 'en-US'


def validate_phone_number(phone_number):
    """Validate and normalize phone number to E.164 format"""
    if not phone_number:
        return None
    # Remove all non-digit characters except +
    cleaned = ''.join(c for c in phone_number if c.isdigit() or c == '+')
    # Ensure it starts with + and has reasonable length
    if not cleaned.startswith('+') or len(cleaned) < 10 or len(cleaned) > 15:
        return None
    return cleaned

def load_opt_out_list():
    """Load opt-out numbers from file and cache them"""
    global opt_out_cache, file_hash_cache
    try:
        if os.path.exists(OPT_OUT_FILE):
            with open(OPT_OUT_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                # Calculate file hash
                current_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
                if current_hash != file_hash_cache:
                    # File has changed, reload cache
                    numbers = set()
                    for line in content.strip().split('\n'):
                        line = line.strip()
                        if line:
                            validated = validate_phone_number(line)
                            if validated:
                                numbers.add(validated)
                    opt_out_cache = numbers
                    file_hash_cache = current_hash
    except Exception as e:
        # Log error but don't crash - continue with empty cache
        print(f"Error loading opt-out list: {e}")
        opt_out_cache = set()
        file_hash_cache = None

def is_opted_out(phone_number):
    """Check if phone number is opted out"""
    validated = validate_phone_number(phone_number)
    if not validated:
        return False
    load_opt_out_list()  # Ensure cache is up to date
    return validated in opt_out_cache

def add_to_opt_out(phone_number):
    """Add phone number to opt-out list"""
    validated = validate_phone_number(phone_number)
    if not validated:
        return False
    try:
        # Append to file
        with open(OPT_OUT_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{validated}\n")
        # Update cache immediately
        opt_out_cache.add(validated)
        # Invalidate hash cache so it reloads next time
        global file_hash_cache
        file_hash_cache = None
        return True
    except Exception as e:
        print(f"Error adding to opt-out list: {e}")
        return False

def remove_from_opt_out(phone_number):
    """Remove phone number from opt-out list"""
    validated = validate_phone_number(phone_number)
    if not validated:
        return False
    try:
        # Read current file
        if os.path.exists(OPT_OUT_FILE):
            with open(OPT_OUT_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Filter out the number
            filtered_lines = [line for line in lines if validate_phone_number(line.strip()) != validated]

            # Write back to file
            with open(OPT_OUT_FILE, 'w', encoding='utf-8') as f:
                f.writelines(filtered_lines)

            # Update cache
            if validated in opt_out_cache:
                opt_out_cache.remove(validated)
            # Invalidate hash cache
            global file_hash_cache
            file_hash_cache = None
            return True
    except Exception as e:
        print(f"Error removing from opt-out list: {e}")
        return False

@app.route('/')
def home():
    return render_template_string(html_consent_content)

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
        response.dial('+14802020751')

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
def incoming_sms():
    message_sid = request.values.get('MessageSid', None)
    message_status = request.values.get('MessageStatus', None)
    logging.info(f'SID: {message_sid}, Status: {message_status}')

    return '', 204


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
