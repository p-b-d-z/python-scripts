# Developing locally
Build and start the container. Repeat when making changes and docker compose will automatically recreate the flask container.

```bash
docker build . -t ivr:local
docker compose up -d
```

## Setting up the environment
Create a `.env` file with the following credentials
```bash
CLOUDFLARE_TOKEN=""
SLACK_APP_TOKEN=""
SLACK_BOT_TOKEN=""
SLACK_CHANNEL_ID=""
TWILIO_SID=""
TWILIO_TOKEN=""
```

# Accessing Valkey
While the containers are running, exec into the container.
```bash
docker exec -it ivr_valkey valkey-cli
```
