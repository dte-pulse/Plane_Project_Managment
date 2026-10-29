# Plane deployment

This deployment is isolated for the shared `dte-apps` server.

For a fresh EC2 instance, see the step-by-step
[EC2 deployment runbook](EC2-DEPLOYMENT.md), including credential rotation,
environment-file setup, Nginx, systemd, and verification.

Initial office-network URL:

```text
http://192.168.0.113
```

The host Nginx already listens on port `80`. Plane gets a separate virtual host
matching the server IP and proxies to the production Compose proxy on
`127.0.0.1:8106`. Plane does not bind host ports `80`, `443`, `8000`, or
`3000`-`3100`. This initial HTTP setup is for the office network or VPN only.
After validation, switch to `plane.pulsepharma.net` with HTTPS at the existing
external URL `https://plane.pulsepharma.net:51028`.

## Local production-like smoke test

The local test uses only disposable local services:

- PostgreSQL
- Valkey
- RabbitMQ
- Silo/MinIO-compatible object storage

It does not use the production Aiven database or AWS credentials.

From the repository root, the local files are already prepared in this checkout. If
you clone fresh, create them from the examples first:

```bash
cp deployments/plane/local-root.env.example deployments/plane/local-root.env
cp deployments/plane/local-api.env.example deployments/plane/local-api.env
cp deployments/plane/local-live.env.example deployments/plane/local-live.env
cp deployments/plane/local-compose.env.example deployments/plane/local-compose.env

docker compose \
  --env-file deployments/plane/local-compose.env \
  -p plane-local \
  -f docker-compose.production.yml \
  -f docker-compose.local-full.yml \
  config --quiet
```

Build the images:

```bash
docker compose \
  --env-file deployments/plane/local-compose.env \
  -p plane-local \
  -f docker-compose.production.yml \
  -f docker-compose.local-full.yml \
  build
```

Start only the local dependencies first:

```bash
docker compose \
  --env-file deployments/plane/local-compose.env \
  -p plane-local \
  -f docker-compose.production.yml \
  -f docker-compose.local-full.yml \
  up -d plane-db plane-redis plane-mq plane-minio
```

Run migrations:

```bash
docker compose \
  --env-file deployments/plane/local-compose.env \
  -p plane-local \
  -f docker-compose.production.yml \
  -f docker-compose.local-full.yml \
  run --rm migrator
```

Start the application services:

```bash
docker compose \
  --env-file deployments/plane/local-compose.env \
  -p plane-local \
  -f docker-compose.production.yml \
  -f docker-compose.local-full.yml \
  up -d web admin space api worker beat-worker live proxy
```

Inspect the stack:

```bash
docker compose \
  --env-file deployments/plane/local-compose.env \
  -p plane-local \
  -f docker-compose.production.yml \
  -f docker-compose.local-full.yml \
  ps
```

Open:

```text
http://localhost:8080/
http://localhost:8080/god-mode/
http://localhost:8080/spaces/
```

Stop the disposable local stack and remove its volumes after testing:

```bash
docker compose \
  --env-file deployments/plane/local-compose.env \
  -p plane-local \
  -f docker-compose.production.yml \
  -f docker-compose.local-full.yml \
  down -v
```

The local `.env` files are ignored by Git. Do not replace them with production
credentials.

## Shared server deployment

Create a private deployment directory:

```bash
sudo install -d -o dte -g dte -m 700 /etc/plane-pulsepharma
sudo install -d -o dte -g dte -m 755 /var/www/plane
```

Keep the repository at `/var/www/plane`. Copy the example files into the
private deployment directory:

```bash
cd /var/www/plane
cp deployments/plane/production.env.example /etc/plane-pulsepharma/compose.env
cp deployments/plane/root.env.example /etc/plane-pulsepharma/root.env
cp deployments/plane/api.env.example /etc/plane-pulsepharma/api.env
cp deployments/plane/live.env.example /etc/plane-pulsepharma/live.env
cp deployments/plane/Caddyfile.external /etc/plane-pulsepharma/Caddyfile.external
```

Edit the private files with the existing Aiven, AWS, and SMTP credentials. Keep
`SECRET_KEY` identical to the one already used with this Aiven database; Plane
uses it to decrypt stored integration settings. Generate a fresh live-service
secret and RabbitMQ password, and put the same live-service secret in both
`api.env` and `live.env`.

```bash
openssl rand -hex 32
```

The Aiven URL, AWS keys, SMTP app password, and Django secret belong only in the
private files under `/etc/plane-pulsepharma`; never commit them.

Set these values in `compose.env`:

```env
PLANE_PUBLIC_URL=http://192.168.0.113
PLANE_PROXY_PORT=8106
```

Validate and build Plane with a unique Compose project name:

```bash
cd /var/www/plane
docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  config --quiet

docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  build

# Stop the interactive development apps and local Compose stack before running
# migrations or starting production services; both configurations use the same
# Aiven database. Press Ctrl-C in the terminal running `pnpm dev`, then run:
docker compose -p plane -f docker-compose-local.yml down

docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  up -d plane-redis plane-mq

docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  run --rm migrator

docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  up -d web admin space api worker beat-worker live proxy
```

The SMTP configuration is stored in the Aiven database and may already contain
values created by the earlier development startup. After the production API is
up, sync the private environment values (the script encrypts the app password
with the existing Django `SECRET_KEY` and never prints it):

```bash
docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  exec -T api python manage.py shell < deployments/plane/configure-smtp.py
```

## systemd on EC2

After the production stack starts successfully, install the provided unit:

```bash
sudo cp deployments/plane/plane-pulsepharma.service.example \
  /etc/systemd/system/plane-pulsepharma.service
sudo systemctl daemon-reload
sudo systemctl enable plane-pulsepharma.service
sudo systemctl start plane-pulsepharma.service
sudo systemctl status plane-pulsepharma.service
```

The unit starts only the Compose project named `plane-pulsepharma`; it does not
stop or restart the other applications on the shared server. Docker's
`unless-stopped` restart policy recovers individual Plane containers after a
failure. The unit starts the project on boot.

For a new deployment, run the migration once before starting the unit. For later
code deployments:

```bash
cd /var/www/plane
docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  build
docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  run --rm migrator
sudo systemctl reload plane-pulsepharma.service
```

The only host port published by Plane is the loopback proxy port:

```text
127.0.0.1:8106 -> Plane proxy :80
```

Plane does not publish ports `80`, `443`, `8000`, `3000`, `3001`, `3002`, or
`3100` on the host.

## Nginx HTTP access

Copy `nginx.plane-ip.conf.example` to the host Nginx sites directory and enable
it as a separate site. It matches only `192.168.0.113`, so the existing Nginx
sites continue to handle their own hostnames:

```bash
sudo cp deployments/plane/nginx.plane-ip.conf.example \
  /etc/nginx/sites-available/plane-ip
sudo ln -s /etc/nginx/sites-available/plane-ip /etc/nginx/sites-enabled/plane-ip
sudo nginx -t
sudo systemctl reload nginx
```

The route is:

```text
http://192.168.0.113 -> http://127.0.0.1:8106
```

The proxy forwards WebSocket upgrades for live collaboration and allows Plane's
configured upload size. The example permits the current `192.168.0.0/24` LAN
and localhost only; adjust the allowed subnet if the office/VPN clients use a
different CIDR.

## Later HTTPS setup

After the domain points to this server, change `PLANE_PUBLIC_URL` and the API
and live origins to `https://plane.pulsepharma.net:51028`, verify the existing
certificate covers that hostname, then replace the IP site with
`nginx.plane.conf.example`. That site redirects HTTP to HTTPS.

## Post-deploy checks

```bash
docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  ps

curl -I http://127.0.0.1:8106/
curl -I -H 'Host: 192.168.0.113' http://127.0.0.1/
curl -I http://192.168.0.113/
```

Inspect failures without printing the environment files:

```bash
docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  logs --tail=100 api worker beat-worker live proxy
```

Do not run `docker compose down` without the `-p plane-pulsepharma` project
scope on the shared server.
