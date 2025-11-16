import os
import logging
from datetime import datetime
from slack_sdk import WebClient
import redis
from helper_functions import validate_phone_number

logging.basicConfig(level=logging.DEBUG)


def get_channel_id(client, channel_input):
    """Convert channel name to ID if needed"""
    logging.info(f'Resolving channel {channel_input} to ID')
    if not channel_input:
        logging.error('Channel input is empty')
        return None
    if not channel_input.startswith('#'):
        logging.info(f'Assuming {channel_input} is already an ID')
        return channel_input  # Assume it's already an ID
    channel_name = channel_input[1:]
    try:
        response = client.conversations_list(types='public_channel,private_channel')
        logging.info(f'Conversations list response: {len(response.get("channels", []))} channels found')
        for channel in response.get('channels', []):
            if channel.get('name') == channel_name:
                logging.info(f'Resolved {channel_input} to ID {channel["id"]}')
                return channel['id']
        logging.error(f'Channel {channel_name} not found in conversations list')
    except Exception as e:
        logging.error(f'Failed to resolve channel ID for {channel_input}: {e}')
    return None


# Initialize Slack client if tokens are available
slack_bot_token = os.getenv('SLACK_BOT_TOKEN')
slack_channel_id_input = os.getenv('SLACK_CHANNEL_ID')
client = WebClient(token=slack_bot_token) if slack_bot_token else None
slack_channel_id = None
if client and slack_channel_id_input:
    slack_channel_id = get_channel_id(client, slack_channel_id_input)
    logging.info(f'Slack channel ID resolved to: {slack_channel_id}')

# Initialize Valkey client for caching
valkey_url = os.getenv('VALKEY_URL', 'redis://localhost:6379')
redis_client = redis.from_url(valkey_url, decode_responses=True)


def post_agent_login(phone: str, email: str = None):
    """Post agent login notification to Slack"""
    if not client or not slack_channel_id:
        logging.debug('Slack not configured, skipping login notification')
        return

    try:
        display_name = get_display_name(phone, email)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S MST')
        message = f'IVR Agent {display_name} ({phone}) logged in at {timestamp}'
        client.chat_postMessage(channel=slack_channel_id, text=message)
        logging.info(f'Posted agent login to Slack: {message}')
    except Exception as e:
        logging.error(f'Failed to post agent login to Slack: {e}')


def post_agent_logout(phone: str, email: str = None):
    """Post agent logout notification to Slack"""
    if not client or not slack_channel_id:
        logging.debug('Slack not configured, skipping logout notification')
        return

    try:
        display_name = get_display_name(phone, email)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S MST')
        message = f'IVR Agent {display_name} ({phone}) logged out at {timestamp}'
        client.chat_postMessage(channel=slack_channel_id, text=message)
        logging.info(f'Posted agent logout to Slack: {message}')
    except Exception as e:
        logging.error(f'Failed to post agent logout to Slack: {e}')


def load_slack_users():
    """Load Slack users into Valkey cache"""
    if not client:
        logging.debug('Slack client not configured, skipping user loading')
        return

    try:
        response = client.users_list()
        users = response.get('members', [])
        ttl = 86400  # 24 hours
        for user in users:
            if user.get('deleted', False):
                continue

            profile = user.get('profile', {})
            display_name = profile.get('real_name', '').strip()
            email = profile.get('email', '').strip()
            phone = profile.get('phone', '').strip()
            normalized_phone = validate_phone_number(phone) if phone else None
            if display_name:
                if normalized_phone:
                    redis_client.setex(f'slack_user_phone:{normalized_phone}', ttl, display_name)
                if email:
                    redis_client.setex(f'slack_user_email:{email}', ttl, display_name)

        logging.info(f'Loaded {len([u for u in users if not u.get("deleted")])} Slack users into cache')
    except Exception as e:
        logging.error(f'Failed to load Slack users: {e}')


def get_display_name(phone: str, email: str = None):
    """Get display name from Valkey cache by phone or email"""
    try:
        if phone:
            display_name = redis_client.get(f'slack_user_phone:{phone}')
            if display_name:
                return display_name

        if email:
            display_name = redis_client.get(f'slack_user_email:{email}')
            if display_name:
                return display_name

    except Exception as e:
        logging.error(f'Failed to get display name from cache: {e}')

    return email if email else 'Unknown Agent'


def upload_voicemail(file_path: str, call_from: str, call_to: str, timestamp: float):
    """Upload voicemail MP3 to Slack with metadata"""
    if not client or not slack_channel_id:
        logging.debug('Slack not configured, skipping voicemail upload')
        return

    logging.info(f'Uploading voicemail to channel {slack_channel_id}')
    try:
        dt = datetime.fromtimestamp(timestamp)
        formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S MST')
        initial_comment = f'Voicemail from {call_from} to {call_to} at {formatted_time}'
        with open(file_path, 'rb') as file:
            client.files_upload_v2(
                channel=slack_channel_id,
                file=file,
                title=f'Voicemail from {call_from}',
                initial_comment=initial_comment,
            )
        logging.info(f'Uploaded voicemail to Slack: {initial_comment}')
    except Exception as e:
        logging.error(f'Failed to upload voicemail to Slack: {e}')
