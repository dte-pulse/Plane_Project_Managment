# Deploy Plane on a new EC2 instance

This runbook deploys the production Compose stack from this repository behind
host Nginx. Replace sample hosts, addresses, usernames, and paths with values
for the new instance.

> Use HTTPS for access over the public Internet. Plain HTTP exposes login
> credentials, session cookies, and invitation tokens. The IP-only example is
> suitable for a restricted LAN or VPN.

## 1. Prepare EC2 and network access

Use Ubuntu with enough CPU, memory, and disk for Plane, RabbitMQ, and Valkey.
Install Git, Docker Engine with the Compose plugin, Nginx, and OpenSSL using
their current official instructions.

Configure the EC2 security group and any upstream firewall/NAT:

| Traffic            | Allow from                                               | Purpose                                               |
| ------------------ | -------------------------------------------------------- | ----------------------------------------------------- |
| TCP 22             | Administrator IPs only                                   | SSH                                                   |
| TCP 80             | Office/VPN CIDR for HTTP, or internet only when required | Nginx HTTP and certificate validation                 |
| TCP 443            | Approved client CIDRs or Internet when using HTTPS       | Nginx HTTPS                                           |
| Outbound TCP 10644 | Aiven endpoint                                           | Example database port; use the provider's actual port |
| Outbound TCP 443   | AWS and image/package registries                         | S3 and downloads                                      |
| Outbound TCP 587   | Microsoft 365 SMTP                                       | STARTTLS email                                        |

Do not expose Plane container ports, RabbitMQ, or Valkey to the Internet. Plane
publishes only a loopback proxy port; Nginx owns host ports 80 and 443. Check
host listeners before choosing a private proxy port such as 8106:

```bash
sudo ss -ltnp
```

Also ensure the Docker bridge CIDR does not conflict with another host network.

## 2. Clone the repository

Give the deployment account read access to GitHub, preferably with a
repository-specific read-only deploy key. Clone the `main` branch:

```bash
sudo install -d -o <linux-user> -g <linux-group> -m 755 /var/www
sudo -u <linux-user> git clone --branch main <github-repository-url> /var/www/plane
cd /var/www/plane
```

Do not put a GitHub token in the URL or repository. The systemd user must own
the checkout and be able to access Docker. Membership in the `docker` group is
root-equivalent; restrict it to the deployment account.

## 3. Create private environment files

Create runtime copies outside Git and restrict their permissions:

```bash
sudo install -d -o <linux-user> -g <linux-group> -m 700 /etc/plane-pulsepharma
cd /var/www/plane
sudo install -o <linux-user> -g <linux-group> -m 600 deployments/plane/production.env.example /etc/plane-pulsepharma/compose.env
sudo install -o <linux-user> -g <linux-group> -m 600 deployments/plane/root.env.example /etc/plane-pulsepharma/root.env
sudo install -o <linux-user> -g <linux-group> -m 600 deployments/plane/api.env.example /etc/plane-pulsepharma/api.env
sudo install -o <linux-user> -g <linux-group> -m 600 deployments/plane/live.env.example /etc/plane-pulsepharma/live.env
sudo install -o <linux-user> -g <linux-group> -m 600 deployments/plane/Caddyfile.external /etc/plane-pulsepharma/Caddyfile.external
```

Edit these files with `sudoedit`. Do not paste values into shell history, commit
them, or send them in chat. `.gitignore` excludes private env files and
`/plane.env`; keep production secrets in `/etc/plane-pulsepharma`.

### `compose.env`

Set the exact browser-visible origin, private proxy port, file paths, S3 bucket,
and trusted proxy ranges:

```env
PLANE_PUBLIC_URL=https://plane.example.com
PLANE_PROXY_PORT=8106
PLANE_ROOT_ENV_FILE=/etc/plane-pulsepharma/root.env
PLANE_API_ENV_FILE=/etc/plane-pulsepharma/api.env
PLANE_LIVE_ENV_FILE=/etc/plane-pulsepharma/live.env
PLANE_PROXY_CONFIG=/etc/plane-pulsepharma/Caddyfile.external
AWS_S3_BUCKET_NAME=<bucket-name>
TRUSTED_PROXIES=<nginx-and-docker-proxy-cidrs>
```

`PLANE_PUBLIC_URL` is embedded into frontend images at build time and used as a
service origin. It must match what users enter, including any non-default
external port:

```text
Direct HTTP:      http://203.0.113.20
Forwarded HTTP:   http://203.0.113.20:51020
Direct HTTPS:     https://plane.example.com
Forwarded HTTPS:  https://plane.example.com:8443
```

Do not add a path or trailing slash. Use the same origin in API and live CORS
and base URL settings. `PLANE_PROXY_PORT` is a host loopback port, not a public
port. The bucket must match `AWS_S3_BUCKET_NAME` in `api.env`.

### `root.env`

This configures only the Compose RabbitMQ container:

```env
RABBITMQ_DEFAULT_USER=plane
RABBITMQ_DEFAULT_PASS=<new-long-random-rabbitmq-password>
RABBITMQ_DEFAULT_VHOST=plane
```

Set matching `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, and `RABBITMQ_VHOST` in
`api.env`. Use a unique password per environment. PostgreSQL is external Aiven;
do not configure a local PostgreSQL container for production.

### `api.env`

Set the following in the private API env file:

| Variables                                                                        | Required setting                                                                                                                                              |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`                                                                   | `postgresql://USER:URL_ENCODED_PASSWORD@HOST:PORT/DATABASE?sslmode=require`. URL-encode reserved password characters.                                         |
| `SECRET_KEY`                                                                     | Preserve the existing value when reusing the same Plane database; it decrypts stored instance settings. Generate a unique one only for a new, empty database. |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME` | Region, least-privilege IAM key, and existing bucket. Set `USE_MINIO=0`. For AWS S3, omit `AWS_S3_ENDPOINT_URL` entirely.                                     |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_URL`                                          | Internal Compose values: `plane-redis`, `6379`, `redis://plane-redis:6379/`.                                                                                  |
| `RABBITMQ_*`                                                                     | Host `plane-mq`, port `5672`, credentials matching `root.env`.                                                                                                |
| `CORS_ALLOWED_ORIGINS`                                                           | Exact public origin, including scheme and any external forwarded port.                                                                                        |
| `WEB_URL`, `APP_BASE_URL`, `ADMIN_BASE_URL`, `SPACE_BASE_URL`, `LIVE_BASE_URL`   | Same public origin. Keep path variables such as `/god-mode`, `/spaces`, and `/live`.                                                                          |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`                     | Microsoft 365: `smtp.office365.com`, `587`, `1`, `0` (STARTTLS).                                                                                              |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_FROM`, `ENABLE_SMTP`            | Mailbox/app-password credentials, sender address, and `ENABLE_SMTP=1`.                                                                                        |
| `LIVE_SERVER_SECRET_KEY`                                                         | Random value that exactly matches `live.env`.                                                                                                                 |

Generate secrets without placing them in shell history:

```bash
openssl rand -hex 32
```

Use an AWS IAM key restricted to the required bucket and region, not a root key.
Never put AWS keys in `compose.env` or frontend `VITE_*` variables. Keep the
bucket private; Plane serves files through its proxy.

### `live.env`

Set `API_BASE_URL=http://api:8000`, `REDIS_HOST=plane-redis`,
`REDIS_URL=redis://plane-redis:6379/`, and `REDIS_PORT=6379`. Set
`WEB_BASE_URL`, `LIVE_BASE_URL`, and `CORS_ALLOWED_ORIGINS` to the same public
origin as `PLANE_PUBLIC_URL`. Match `LIVE_SERVER_SECRET_KEY` exactly with
`api.env`.

### Credentials to rotate or preserve

- AWS, SMTP, and database credentials previously shared in the deployment
  conversation should be considered exposed. Rotate before reusing this setup.
  Prefer separate credentials per environment.
- Prefer a bucket-scoped IAM key, new SMTP app password, and dedicated Aiven
  database user/password if the provider setup allows it.
- When moving the existing Plane database, preserve its Django `SECRET_KEY`;
  rotate the database password separately. For a new database, generate a new
  Django key, RabbitMQ password, and live-service secret.
- Never use production credentials in local smoke-test env files.

## 4. Validate and start Compose

Validate configuration first; this does not print env values:

```bash
cd /var/www/plane
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml config --quiet
```

For an existing Plane database, take a backup and schedule the move so the old
instance is not writing to it while the new version migrates it. Do not run two
independent Plane versions against one live database.

Build images and start dependencies:

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml build
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml \
  up -d plane-redis plane-mq
```

Migrate, then start Plane:

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml run --rm migrator
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml \
  up -d web admin space api worker beat-worker live proxy
```

SMTP values are stored in the database. After the API starts, synchronize them
from private `api.env`:

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml \
  exec -T api python manage.py shell < deployments/plane/configure-smtp.py
```

The script encrypts the app password using `SECRET_KEY` and does not print it.
Check containers with:

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml ps
```

## 5. Configure Nginx

Nginx stays on host ports 80 and 443. Plane publishes its proxy only on
`127.0.0.1:8106` or the chosen `PLANE_PROXY_PORT`; it does not claim ports used
by other host applications.

| Listener                                                              | Bind scope           | Role                                                           |
| --------------------------------------------------------------------- | -------------------- | -------------------------------------------------------------- |
| Nginx 80/443                                                          | Host interfaces      | Public or LAN HTTP/HTTPS entry point; shared with Nginx vhosts |
| Plane proxy `PLANE_PROXY_PORT` → container 80                         | `127.0.0.1` only     | Nginx upstream                                                 |
| Web/admin/space 3000, API 8000, live 3000, RabbitMQ 5672, Valkey 6379 | Compose network only | Internal service traffic; no host port publication             |

Check that the selected loopback proxy port is free before starting Compose.

### HTTP by IP or forwarded port

Copy `nginx.plane-ip.conf.example` into `sites-available`. Change `server_name`
to the IP/domain in the browser Host header and adjust `allow` to the office/VPN
subnet. If a router maps external port `51020` to EC2 port 80, set
`PLANE_PUBLIC_URL=http://PUBLIC_IP:51020`; Nginx still listens on port 80.

```bash
sudo cp deployments/plane/nginx.plane-ip.conf.example /etc/nginx/sites-available/plane-ip
sudoedit /etc/nginx/sites-available/plane-ip
sudo ln -s /etc/nginx/sites-available/plane-ip /etc/nginx/sites-enabled/plane-ip
sudo nginx -t
sudo systemctl reload nginx
```

With other Nginx vhosts, confirm the Plane IP/domain selects this server block
and does not change their default vhost. Reload the existing Nginx service to
apply changes; do not start a second `nginx` master.

### HTTPS by domain

Point DNS at EC2, obtain a certificate for the domain, and adapt
`nginx.plane.conf.example` to the certificate paths. If the network forwards
standard public HTTPS port 443 to host port 443, use the domain without a port.
Set `PLANE_PUBLIC_URL` and all API/live origins to the final HTTPS origin,
including any non-default forwarded port. Rebuild web, admin, and space because
frontend origins are embedded at build time, then validate and reload Nginx.

## 6. Install systemd

Review `plane-pulsepharma.service.example`. It assumes checkout `/var/www/plane`,
env files `/etc/plane-pulsepharma`, and user/group `dte`. On a new EC2 instance,
replace `User=` and `Group=` with the deployment account. Confirm it can run
Docker and read the private env files.

```bash
sudo cp deployments/plane/plane-pulsepharma.service.example \
  /etc/systemd/system/plane-pulsepharma.service
sudoedit /etc/systemd/system/plane-pulsepharma.service
sudo systemctl daemon-reload
sudo systemctl enable --now plane-pulsepharma.service
sudo systemctl status plane-pulsepharma.service
```

This is a `Type=oneshot` unit with `RemainAfterExit=yes`; `active (exited)` is
normal. Docker's `unless-stopped` policy restarts containers after failure and
host boot. The unit only operates on Compose project `plane-pulsepharma`. Do
not remove its volumes during routine updates.

## 7. Verify and troubleshoot

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml ps
curl -I http://127.0.0.1:8106/
curl -I -H 'Host: plane.example.com' http://127.0.0.1/
sudo nginx -t
sudo systemctl is-active plane-pulsepharma.service
```

For the IP example, use the IP in `server_name`. Inspect logs without printing
env files:

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml \
  logs --tail=100 api worker beat-worker live proxy web admin
```

If office users sharing one NAT IP receive HTTP 429 for assets, confirm the
web/admin Caddy configs have this repository's higher static-file limit and
rebuild those images. This is separate from API authentication limits.

### GitHub Actions deployment

`.github/workflows/deploy-plane.yml` deploys on pushes to `main` and supports
manual runs from the Actions tab. Add these Actions repository secrets:

| Secret        | Value                                   |
| ------------- | --------------------------------------- |
| `EC2_HOST`    | Hostname or IP address used for SSH     |
| `EC2_USER`    | Linux deployment account, such as `dte` |
| `EC2_SSH_KEY` | Private SSH key for that account        |
| `EC2_PORT`    | SSH port, usually `22`                  |

The deployment account must be able to pull this repository, run Docker Compose,
read `/etc/plane-pulsepharma/compose.env` and its referenced private env files,
and run `sudo -n /usr/bin/systemctl reload plane-pulsepharma.service` without a
password. The job validates Compose, builds the stack, runs the migrator, then
reloads and checks only the Plane systemd service. It does not run `docker
compose down` or restart the other host applications. Back up the external
database before deploying application changes that include migrations.

## Routine code deployment

```bash
cd /var/www/plane
git pull --ff-only origin main
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml build
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml run --rm migrator
sudo systemctl reload plane-pulsepharma.service
```

Back up the database before migrations. The unit's `ExecReload` runs Compose
build/start and does not stop unrelated projects. Avoid `docker compose down -v`,
which removes Plane's local RabbitMQ and Valkey data.
