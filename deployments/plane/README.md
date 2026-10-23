# Plane deployment

This deployment is isolated for the shared `dte-apps` server.

Public URL:

```text
https://plane.pulsepharma.net:51028
```

The existing host Nginx terminates TLS on port `443` and proxies to the Plane
proxy over a loopback port. The default loopback port in the deployment files is
`8106`; change it only if that port is already occupied.

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

## EC2 deployment

Create a private deployment directory:

```bash
sudo install -d -o dte -g dte -m 700 /etc/plane-pulsepharma
sudo install -d -o dte -g dte -m 755 /var/www/plane
```

Clone the repository into `/var/www/plane` using a read-only GitHub deploy key.
Then copy the example files into the private deployment directory:

```bash
cd /var/www/plane
cp deployments/plane/production.env.example /etc/plane-pulsepharma/compose.env
cp deployments/plane/root.env.example /etc/plane-pulsepharma/root.env
cp deployments/plane/api.env.example /etc/plane-pulsepharma/api.env
cp deployments/plane/live.env.example /etc/plane-pulsepharma/live.env
cp deployments/plane/Caddyfile.external /etc/plane-pulsepharma/Caddyfile.external
```

Edit the private files and replace every placeholder. Generate fresh secrets:

```bash
openssl rand -hex 32
```

The same `LIVE_SERVER_SECRET_KEY` must be used in both `api.env` and `live.env`.
The real Aiven URL and rotated AWS credentials belong only in
`/etc/plane-pulsepharma/api.env`; never commit them.

Set these public values in `compose.env`:

```env
PLANE_PUBLIC_URL=https://plane.pulsepharma.net:51028
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

## systemd on EC2

After the first manual deployment succeeds, install the provided unit:

```bash
sudo cp deployments/plane/plane-pulsepharma.service.example \
  /etc/systemd/system/plane-pulsepharma.service
sudo systemctl daemon-reload
sudo systemctl enable plane-pulsepharma.service
sudo systemctl start plane-pulsepharma.service
sudo systemctl status plane-pulsepharma.service
```

The unit manages only the Compose project named `plane-pulsepharma`; it does not
stop or restart the other applications on the shared server.

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

## Nginx

Copy `nginx.plane.conf.example` to the host Nginx sites directory, verify that
the existing wildcard certificate covers `plane.pulsepharma.net`, then enable it:

```bash
sudo ln -s /etc/nginx/sites-available/plane.pulsepharma.net \
  /etc/nginx/sites-enabled/plane.pulsepharma.net
sudo nginx -t
sudo systemctl reload nginx
```

The Nginx configuration forwards:

```text
https://plane.pulsepharma.net:51028 -> http://127.0.0.1:8106
```

The `/live/` route includes WebSocket upgrade headers and a long read timeout.

## Post-deploy checks

```bash
docker compose \
  --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma \
  -f docker-compose.production.yml \
  ps

curl -I http://127.0.0.1:8106/
curl -k -H 'Host: plane.pulsepharma.net' https://127.0.0.1/
curl -k https://plane.pulsepharma.net:51028/
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
