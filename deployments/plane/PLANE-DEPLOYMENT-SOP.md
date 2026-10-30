# Plane Project Management — Deployment SOP

**Document purpose:** reproducible production deployment and operations guide for the Plane instance hosted on `dte-apps`.

**Audience:** the `dte` Linux deployment account and repository maintainers.

**Production URL target:** `https://plane.pulsepharma.net:51026` over HTTPS.

> Keep credentials out of this document, Git, terminal history, and chat. The
> live server's private environment files are the source of truth for secrets.

## Application details

| Item                  | Value                                                                     |
| --------------------- | ------------------------------------------------------------------------- |
| Application           | Plane Project Management (Pulsepharma deployment)                         |
| VM hostname           | `dte-apps`                                                                |
| VM public IP          | `103.24.125.50` (confirm if the host IP changes)                          |
| VM user               | `dte`                                                                     |
| Application folder    | `/var/www/plane`                                                          |
| GitHub organization   | `dte-pulse`                                                               |
| GitHub repository     | `Plane_Project_Managment`                                                 |
| Repository URL        | `https://github.com/dte-pulse/Plane_Project_Managment`                    |
| Branch deployed       | `main`                                                                    |
| Runtime               | Docker Compose production stack                                           |
| Compose file          | `/var/www/plane/docker-compose.production.yml`                            |
| Compose project       | `plane-pulsepharma`                                                       |
| Private env directory | `/etc/plane-pulsepharma`                                                  |
| Systemd unit          | `plane-pulsepharma.service`                                               |
| Public hostname       | `plane.pulsepharma.net`                                                   |
| Public access         | HTTPS only; Sophos external port `51026` forwards to host port `443`      |
| TLS termination       | Host Nginx, with the existing certificate for `pulsepharma.net`           |
| Nginx upstream        | `127.0.0.1:8106` by default                                               |
| Database              | External PostgreSQL on Aiven                                              |
| Object storage        | AWS S3 bucket `hrappmodule` (confirm bucket and region in private config) |
| Email                 | Microsoft 365 SMTP, STARTTLS on port `587`                                |
| Deployment trigger    | GitHub Actions push to `main`, or manual workflow dispatch                |
| Actions workflow      | `.github/workflows/deploy-plane.yml`                                      |

## Service map

| Plane area             | Public path                               | Container/service         |
| ---------------------- | ----------------------------------------- | ------------------------- |
| Main web app           | `/`                                       | `web`                     |
| API and authentication | `/api`, `/auth`, `/static`                | `api`                     |
| Admin console          | `/god-mode`                               | `admin`                   |
| Workspace/project UI   | `/spaces`                                 | `space`                   |
| Live collaboration     | `/live`                                   | `live`                    |
| Reverse proxy          | Host loopback `8106`; container port `80` | `proxy`                   |
| Background jobs        | Internal only                             | `worker`, `beat-worker`   |
| Cache and queue        | Internal only                             | `plane-redis`, `plane-mq` |

Sophos reserves its own public port 443, so Plane uses dedicated external HTTPS
port `51026`, forwarded to host port `443`. The browser URL is therefore
`https://plane.pulsepharma.net:51026` unless the Sophos rule changes. The host
may keep port 80 for other apps, but Nginx and Sophos must not route Plane
traffic over HTTP. The Compose proxy binds only to loopback; its container port
80 is an internal upstream, not a public listener.

## 1. Prepare the host and network

This is a shared application host. Review existing listeners and services
before changing firewall rules, Nginx, Docker, or systemd:

```bash
hostname
id dte
sudo ss -lntp
sudo systemctl status nginx docker --no-pager
```

Network requirements:

| Traffic                  | Allow from                                                       | Purpose                                   |
| ------------------------ | ---------------------------------------------------------------- | ----------------------------------------- |
| External TCP 51022       | Administrator IPs or approved deployment source                  | Sophos SSH forward to host SSH            |
| TCP 443                  | Host interface                                                   | Plane HTTPS listener through Nginx        |
| External TCP 51026       | Approved client networks                                         | Sophos forwards to host TCP 443           |
| External TCP 51020       | Other apps only, if required                                     | Shared HTTP forward; must not route Plane |
| TCP 80                   | Do not route to Plane; retain only for other host apps if needed | Other vhosts or certificate validation    |
| Outbound TCP 443         | Required registries and AWS endpoints                            | Docker image/dependency downloads and S3  |
| Outbound TCP 587         | Microsoft 365 SMTP endpoint                                      | Email STARTTLS                            |
| Outbound PostgreSQL port | Aiven database endpoint; confirm provider port                   | Database traffic                          |

Do not expose Compose service ports such as API `8000`, web/admin/space `3000`,
RabbitMQ `5672`, or Valkey `6379`. The production Compose file exposes only the
proxy on `127.0.0.1:${PLANE_PROXY_PORT}`.

## 2. Confirm repository access and checkout

The host checkout must be owned by `dte`, and the host needs read access to the
private repository. Use the host's configured GitHub deploy key/SSH alias if
HTTPS authentication is unavailable. Do not put a personal access token in a
Git URL.

For a new host:

```bash
sudo install -d -o dte -g dte -m 755 /var/www
sudo -u dte git clone --branch main \
  https://github.com/dte-pulse/Plane_Project_Managment /var/www/plane
```

For the existing host:

```bash
cd /var/www/plane
git status --short --branch
git remote -v
git branch --show-current
```

Do not overwrite local files or reset the checkout if it contains uncommitted
work. The current deployment workflow expects `/var/www/plane` and branch
`main`.

## 3. Configure private runtime files

Production secrets belong outside the repository in `/etc/plane-pulsepharma`.
The expected files are:

| File                 | Purpose                                                                  |
| -------------------- | ------------------------------------------------------------------------ |
| `compose.env`        | Public URL, proxy port, env-file paths, S3 bucket, trusted proxy ranges  |
| `api.env`            | Aiven URL, Django key, AWS credentials, SMTP, service URLs, app settings |
| `live.env`           | Live collaboration service URLs and matching live secret                 |
| `root.env`           | RabbitMQ container credentials                                           |
| `Caddyfile.external` | Internal Plane proxy routing configuration                               |

For a new installation, create the directory and copy examples, then set
permissions and edit values locally on the host:

```bash
sudo install -d -o dte -g dte -m 700 /etc/plane-pulsepharma
cd /var/www/plane
sudo install -o dte -g dte -m 600 deployments/plane/production.env.example /etc/plane-pulsepharma/compose.env
sudo install -o dte -g dte -m 600 deployments/plane/api.env.example /etc/plane-pulsepharma/api.env
sudo install -o dte -g dte -m 600 deployments/plane/live.env.example /etc/plane-pulsepharma/live.env
sudo install -o dte -g dte -m 600 deployments/plane/root.env.example /etc/plane-pulsepharma/root.env
sudo install -o dte -g dte -m 600 deployments/plane/Caddyfile.external /etc/plane-pulsepharma/Caddyfile.external
```

When maintaining an existing deployment, edit the private files in place. Do
not copy example files over production files: that would replace credentials
and deployment-specific values.

### `compose.env`

Required target values:

```env
PLANE_PUBLIC_URL=https://plane.pulsepharma.net:51026
PLANE_PROXY_PORT=8106
PLANE_ROOT_ENV_FILE=/etc/plane-pulsepharma/root.env
PLANE_API_ENV_FILE=/etc/plane-pulsepharma/api.env
PLANE_LIVE_ENV_FILE=/etc/plane-pulsepharma/live.env
PLANE_PROXY_CONFIG=/etc/plane-pulsepharma/Caddyfile.external
AWS_S3_BUCKET_NAME=hrappmodule
TRUSTED_PROXIES=<nginx-and-docker-proxy-cidrs>
```

`PLANE_PUBLIC_URL` has no path or trailing slash. With the current Sophos
mapping, use `https://plane.pulsepharma.net:51026`; that external port forwards
to host port 443. The host proxy port is loopback-only and is not user-facing.

### Application secrets and service settings

Set production values in `api.env`, `live.env`, and `root.env`; do not copy the
placeholder values verbatim.

- **Aiven PostgreSQL:** use the provider URL and SSL mode required by the
  database. URL-encode reserved characters in the password.
- **Django `SECRET_KEY`:** preserve the currently deployed key when connecting
  to an existing Plane database. Plane uses it to decrypt saved integration
  values. Changing it can make stored encrypted values unreadable.
- **AWS S3:** use a least-privilege IAM credential scoped to the required
  bucket. Keep `USE_MINIO=0`; omit `AWS_S3_ENDPOINT_URL` for AWS S3.
- **Redis/Valkey:** `REDIS_HOST=plane-redis`, port `6379`, URL
  `redis://plane-redis:6379/`.
- **RabbitMQ:** host `plane-mq`, port `5672`, vhost `plane`; credentials in
  `api.env` must match `root.env`.
- **Service origins:** `CORS_ALLOWED_ORIGINS`, `WEB_URL`, `APP_BASE_URL`,
  `ADMIN_BASE_URL`, `SPACE_BASE_URL`, and `LIVE_BASE_URL` must use
  `https://plane.pulsepharma.net:51026`. Keep configured subpaths such as
  `/god-mode`, `/spaces`, and `/live` in their respective `*_BASE_PATH`
  settings.
- **Live secret:** `LIVE_SERVER_SECRET_KEY` must match exactly between
  `api.env` and `live.env`.
- **SMTP:** Microsoft 365 uses `smtp.office365.com`, port `587`, TLS enabled,
  SSL disabled. Keep the mailbox app password only in `api.env`.
- **S3 bucket consistency:** `AWS_S3_BUCKET_NAME` in `compose.env` and `api.env`
  must agree.

Generate random secrets on the host without entering them in shell history:

```bash
openssl rand -hex 32
```

Review permissions without displaying file contents:

```bash
sudo ls -ld /etc/plane-pulsepharma
sudo ls -l /etc/plane-pulsepharma
```

## 4. Validate and build the production stack

Run commands from the repository root, always using the deployment project
name and external env file:

```bash
cd /var/www/plane
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml config --quiet
```

Back up the Aiven database before migrations. Do not run two independent Plane
versions against the same live database. If local development services are
running against the production database, stop them before production
migrations. Build the images:

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml build
```

Start the internal data services, run migrations, then start Plane:

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml \
  up -d plane-redis plane-mq

docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml run --rm migrator

docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml \
  up -d web admin space api worker beat-worker live proxy
```

The application services are web, admin (`/god-mode`), space (`/spaces`), API,
worker, beat-worker, live collaboration, and the internal proxy. The database
is external; production Compose does not create a local PostgreSQL service.

### SMTP database synchronization

Plane stores SMTP configuration in the database. After API startup, apply the
private `api.env` SMTP values using the repository helper. It encrypts the
password with Django `SECRET_KEY` and does not print it:

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml \
  exec -T api python manage.py shell < deployments/plane/configure-smtp.py
```

## 5. Configure HTTPS-only Nginx

Create/verify the DNS A record `plane.pulsepharma.net` pointing to
`103.24.125.50`. The current Sophos routes use external SSH port `51022` and
shared HTTP port `51020`; Plane uses its own external HTTPS port `51026`, which
forwards to host Nginx port `443`. Sophos itself owns external port `443`. The
user-facing URL is `https://plane.pulsepharma.net:51026`.

Nginx terminates TLS on host port 443. Install the repository's HTTPS-only
example as a separate virtual host, then adapt the certificate paths if needed:

```bash
sudo cp /var/www/plane/deployments/plane/nginx.plane.conf.example \
  /etc/nginx/sites-available/plane.pulsepharma.net
sudoedit /etc/nginx/sites-available/plane.pulsepharma.net
sudo ln -s /etc/nginx/sites-available/plane.pulsepharma.net \
  /etc/nginx/sites-enabled/plane.pulsepharma.net
```

The server block must listen on `443 ssl`, use the valid wildcard certificate,
proxy to `http://127.0.0.1:8106`, and set `X-Forwarded-Proto https`. Do not
create or enable a Plane HTTP server block on port 80. On an existing server,
locate any old Plane HTTP site and remove/disable only that Plane site; preserve
other applications' Nginx virtual hosts.

Validate before applying Nginx changes:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl status nginx --no-pager
```

In Sophos/firewall/NAT, forward external TCP `51026` to this host's TCP `443`
and allow only approved client networks where applicable. Sophos reserves
external port 443. Do not forward HTTP port `51020` or host port 80 to Plane. If
another app requires HTTP on the shared host, its port 80 rule may remain, but
Plane must not answer or redirect from it.

## 6. Install the systemd unit

The repository unit is configured for user/group `dte`, working directory
`/var/www/plane`, and private `compose.env`:

```bash
sudo cp /var/www/plane/deployments/plane/plane-pulsepharma.service.example \
  /etc/systemd/system/plane-pulsepharma.service
sudo systemctl daemon-reload
sudo systemctl enable --now plane-pulsepharma.service
sudo systemctl status plane-pulsepharma.service --no-pager
```

The unit is `Type=oneshot` with `RemainAfterExit=yes`; `active (exited)` is
normal. Docker's `unless-stopped` policy keeps containers running and restarts
them after host boot. The unit is scoped to Compose project
`plane-pulsepharma`; do not use an unscoped `docker compose down` on this
shared host.

## 7. Configure GitHub Actions deployment

The workflow at `.github/workflows/deploy-plane.yml` runs on pushes to `main`
and also supports manual dispatch from GitHub Actions. Configure these
repository secrets under **Settings → Secrets and variables → Actions**:

| Secret        | Value                                                           |
| ------------- | --------------------------------------------------------------- |
| `EC2_HOST`    | SSH-reachable hostname or IP for `dte-apps`                     |
| `EC2_USER`    | `dte`                                                           |
| `EC2_PORT`    | `51022` for the current Sophos SSH forward (confirm if changed) |
| `EC2_SSH_KEY` | Private SSH key whose public key is authorized for `dte`        |

The Actions key is the VM-login key; it is separate from any GitHub deploy key
that the VM uses to pull the private repository. Restrict the key to this host
account. The deployment account must be able to pull `main`, run Docker Compose,
and read all private env files. The current workflow does not use `sudo`.

For each deploy, Actions:

1. SSHes to the host and enters `/var/www/plane`.
2. Pulls `origin main` with fast-forward only.
3. Validates production Compose without printing config values.
4. Builds production images.
5. Runs the database migrator.
6. Starts/recreates the Plane Compose services and reports `compose ps`.

The workflow serializes production deployments. It does not run
`docker compose down`, delete volumes, or reload Nginx. A push that changes
frontend origins requires the server's private `compose.env` to have the new
origin before the build so those values are embedded in the frontend images.

## 8. Verify the deployment

On the host, check service state and the private upstream:

```bash
cd /var/www/plane
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml ps
curl -I http://127.0.0.1:8106/
sudo nginx -t
sudo systemctl is-active plane-pulsepharma.service
```

From an approved client network:

```bash
curl -I https://plane.pulsepharma.net:51026/
```

The browser URL is `https://plane.pulsepharma.net:51026`. Confirm the TLS
certificate is valid and that login, workspace pages, admin, file uploads,
email, and live collaboration work.
Confirm Plane is not reachable over HTTP on port 80. Do not infer that from the
Compose port mapping alone; check the active Nginx site and upstream firewall.

## 9. Routine deployment and rollback

Normal releases go to `main`; GitHub Actions performs the deployment. If
deploying manually, use the same ordered steps: fast-forward pull, Compose
validation, build, database backup when applicable, migration, then `up -d` for
the application services. Avoid restarting unrelated host applications.

If a code release fails:

1. Read the failed Actions log and host container logs.
2. Identify the last known-good commit and check whether the failed release
   introduced database migrations.
3. Revert the code change with a new commit or deploy a known-good commit using
   the repository's approved release process.
4. Rebuild and start the services; do not delete Compose volumes.
5. Restore a database backup only when the migration/data change requires it
   and the restore plan has been reviewed. A code rollback alone may not reverse
   database migrations.

Never use `docker compose down -v` for routine deployment or rollback; it
deletes Plane's local RabbitMQ and Valkey data volumes.

## 10. Troubleshooting

| Symptom                            | Check                                                                                                                                                              |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Actions SSH connection refused     | Confirm `EC2_HOST`, `EC2_PORT`, firewall/NAT SSH forwarding, and host SSH service.                                                                                 |
| SSH authentication failure         | Confirm `EC2_SSH_KEY` matches the public key in `dte`'s `authorized_keys`.                                                                                         |
| `git pull` fails                   | Check the host deploy key/SSH alias and read access to the private repository.                                                                                     |
| Compose says a variable is missing | Check `compose.env` path and required `PLANE_*` values; keep private values out of logs.                                                                           |
| Image build fails                  | Inspect the first failing Docker build step; warnings about large bundles or slow registry requests are not necessarily fatal.                                     |
| Migration fails                    | Check Aiven reachability, database URL/SSL mode, permissions, and backup status before retrying.                                                                   |
| Site unavailable on HTTPS          | Check container health/logs, loopback proxy, active Nginx site, certificate paths, and firewall 443 forwarding.                                                    |
| Site still loads over HTTP         | Find and disable the Plane-specific Nginx port 80 site and remove any firewall/NAT route to Plane. Do not disable shared HTTP sites without checking their owners. |
| Email does not send                | Confirm private SMTP settings and rerun `configure-smtp.py` after API startup.                                                                                     |
| Collaboration disconnects          | Confirm `/live` routing, WebSocket headers, `LIVE_SERVER_SECRET_KEY` equality, and origins.                                                                        |
| S3 uploads fail                    | Verify bucket, region, IAM permissions, and matching bucket settings; never print AWS keys.                                                                        |

View logs without displaying environment files:

```bash
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f docker-compose.production.yml \
  logs --tail=100 api worker beat-worker live proxy web admin
sudo journalctl -u plane-pulsepharma.service -n 100 --no-pager
```

## 11. Operational safety and backups

- Back up the external Aiven PostgreSQL database before migrations and confirm
  the recovery procedure periodically.
- Keep separate least-privilege AWS and database credentials where possible.
- Rotate any credential that has been exposed and update the corresponding
  private env file; never commit secrets.
- Preserve Django `SECRET_KEY` when reusing the existing database.
- Preserve RabbitMQ and Valkey Compose volumes. Do not prune volumes as part of
  deploy cleanup.
- On this shared server, keep all Compose commands explicitly scoped with
  `-p plane-pulsepharma` and the production Compose file.
- Keep public access HTTPS-only. Sophos external port `51026` forwards to host
  port `443`; the internal proxy port 80 is loopback-only and not public.

## Quick reference

```bash
# Status
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f /var/www/plane/docker-compose.production.yml ps

# Logs
docker compose --env-file /etc/plane-pulsepharma/compose.env \
  -p plane-pulsepharma -f /var/www/plane/docker-compose.production.yml \
  logs --tail=100 api worker beat-worker live proxy

# Nginx validation/reload after a config change
sudo nginx -t && sudo systemctl reload nginx

# systemd status
sudo systemctl status plane-pulsepharma.service --no-pager
```
