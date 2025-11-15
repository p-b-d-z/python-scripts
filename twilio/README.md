# Developing locally
Build and start the container. Repeat when making changes and docker compose will automatically recreate the flask container.

```bash
docker build . -t ivr:local
docker compose up -d
```

# Accessing Valkey
While the containers are running, exec into the container.
```bash
docker exec -it ivr_valkey valkey-cli
```
