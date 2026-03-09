# Nginx Proxy Manager for Sub2API

This project runs a standalone Nginx Proxy Manager instance under `tools/nginx-proxy-manager/` and attaches it to the shared `sub2api-network` Docker network.

## Usage

1. Start Sub2API first from `deploy/` so the shared network exists.
2. If you want, edit the default passwords in `docker-compose.yml` before first start.
3. Start this project:

```bash
docker compose up -d
```

4. Open the admin UI:

```text
http://YOUR_SERVER_IP:81
```

## Proxy Host Settings for Sub2API

Create a new Proxy Host in the Nginx Proxy Manager UI with:

- Domain Names: your domain
- Scheme: `http`
- Forward Hostname / IP: `sub2api`
- Forward Port: `8080`

Then optionally enable SSL and request a Let's Encrypt certificate in the UI.
