from flask import Flask, request, session, Response, render_template_string
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
import requests

app = Flask(__name__)
with open('sms_consent.html', 'r', encoding='utf-8') as file:
    html_consent_content = file.read()

@app.route('/')
def home():
    return render_template_string(html_consent_content)

@app.route('/voice/incoming', methods=['POST'])
def incoming_voice():
    response = VoiceResponse()
    digit = request.form.get('Digits', '')
    if digit == '1':
        response.say('Please leave your message after the beep. Press any key when you are done.')
        response.record(
            action='/recording/save',
            max_length=120,
            play_beep=True,
            finish_on_key='any'
        )
    else:
        response.say('Please hold while we connect you to an agent.')
        response.pause(length=5)
        response.dial('+14802020751')
    return Response(str(response), mimetype='text/xml')


@app.route('/recording/save', methods=['POST'])
def recording_complete():
    recording_url = request.form.get('RecordingUrl')
    recording_sid = request.form.get('RecordingSid')
    response = VoiceResponse()
    if recording_url and recording_sid:
        mp3_url = f'{recording_url}.mp3'
        local_filename = f'recordings/{recording_sid}.mp3'
        # Download recording to local file
        file_data = requests.get(mp3_url).content
        with open(local_filename, 'wb') as f:
            f.write(file_data)
        response.say('Thank you for your message. Goodbye!')
        response.hangup()
    else:
        response.say('No recording was received. Goodbye!')
        response.hangup()
    return Response(str(response), mimetype='text/xml')


@app.route('/incoming/sms', methods=['GET', 'POST'])
def incoming_sms():
    """Respond to incoming SMS with a 'Hello world' message"""
    user_response = request.form.get('Body', '').strip().lower()
    resp = MessagingResponse()
    if 'report' not in session:
        resp.message('Would you like to report an issue? Reply YES or NO.')
        session['report'] = True
    elif user_response == 'yes':
        resp.message('Please describe your issue. Send as much detail as possible.')
        session['awaiting_details'] = True
    elif session.get('awaiting_details'):
        report_details = user_response
        # Call your Freshdesk API function here with report_details
        # freshdesk_create_ticket(report_details)
        resp.message('Thank you! Your issue has been reported.')
        session.clear()
    else:
        resp.message('Let us know if you need help!')
        session.clear()

    return Response(str(resp), mimetype='text/xml')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
