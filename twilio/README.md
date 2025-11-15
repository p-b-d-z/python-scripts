# Developing locally
Build and start the container. Repeat when making changes and docker compose will automatically recreate the flask container.

```bash
docker build . -t ivr:local
docker compose up -d
```
