import http.client
import json
import base64


def freshdesk_create_ticket(details):
    api_key = 'your_freshdesk_api_key'
    conn = http.client.HTTPSConnection('yourdomain.freshdesk.com')
    ticket_data = json.dumps(
        {
            'subject': 'IVR Issue Report',
            'description': details,
            'email': 'user@example.com',
            'priority': 1,
            'status': 2,
        }
    )
    headers = {
        'Authorization': 'Basic ' + base64.b64encode((api_key + ':X').encode()).decode(),
        'Content-Type': 'application/json',
    }
    conn.request('POST', '/api/v2/tickets', ticket_data, headers)
    response = conn.getresponse()
    return response.status, response.read()
