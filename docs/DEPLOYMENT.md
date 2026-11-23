# Deploying Traffic Agent

This guide puts the dashboard on a server so others can open it in a browser.
It was written without being able to run Docker in the authoring environment:
the CI workflow (`.github/workflows/ci.yml`) builds the image and runs
`python scripts/check_setup.py --full` inside it, so a green CI run is the real proof.
Do the same check yourself on the first deploy (step 4).

## What you need

* A Linux server or VM with Docker and the Compose plugin. 2 CPUs and 4 GB of
  RAM is the practical minimum (PyTorch and YOLO need the memory).
* A domain name pointing at it, for HTTPS.
* The trained emergency-vehicle model is already in `models/` (see [TRAINING.md](TRAINING.md) to replace it with your own).

## Quick path (a Linux server with Docker)

```bash
git clone https://github.com/aditya182005/Real_Time_AI_Traffic_Monitoring_Violation_Enforcement.git
cd Real_Time_AI_Traffic_Monitoring_Violation_Enforcement
cp .env.example .env && nano .env        # at least DOMAIN, see step 1
docker compose --profile https up -d --build
docker compose exec traffic-agent python -m app.users add alice --role admin
docker compose exec traffic-agent python scripts/check_setup.py --full --production
```

Then open `https://your-domain`. That starts three containers: the dashboard,
**maintenance** (every 24 hours: integrity check, retention, backup) and
**caddy** (HTTPS with an automatic certificate). The trained emergency-vehicle
model (`models/emergency_vehicle.pt`) is in the repository, so emergency
detection works from the first start.

Without a domain (a campus LAN or a demo) leave `DOMAIN` empty, start with
`docker compose up -d --build`, and set `BIND_ADDRESS=0.0.0.0` to reach it from
other computers. That is plain HTTP: use individual accounts only on a network
you trust.

## 1. Configure

```bash
cp .env.example .env
```

Edit `.env`:

| Setting | Why |
|---|---|
| `DOMAIN` | The name that points at this server. With `--profile https` Caddy gets a certificate for it (ports 80 and 443 must be open). |
| Sign-in | **Required in production**: the app refuses to show anything without it. Pick one: individual accounts (`docker compose exec traffic-agent python -m app.users add alice --role admin`), `DASHBOARD_PASSWORD` (12+ characters), or `AUTH_MODE=proxy` (below). |
| `EVIDENCE_RETENTION_DAYS` | Days to keep evidence pictures and plates. The daily job enforces it. `0` keeps everything: choose a number your rules allow. |
| `FINES_FILE` | Your own fine amounts (copy `deploy/fines.example.json`). Without it the demo amounts are used. |
| `BACKUP_PATH`, `BACKUP_KEEP` | Where the daily backups go (a second disk or NAS, writable by uid 1000) and how many to keep (default 7). |
| `LIVE_CAMERAS` | Cameras people may start, as `Name=rtsp://...;Name2=...`. Contains passwords: keep `.env` private. |
| `LIVE_MAX_CAMERAS` | Cameras analyzed at once (default 1). Each one needs its own share of CPU/GPU. |
| `TWILIO_*`, `ALERT_TO_PHONE`, `TELEGRAM_*` | Optional alerts. Test first with `python -m app.alerts.twilio_alert --send` / `python -m app.alerts.telegram_alert --send`. |
| `CAMERA_ID` | Name stored with records and alerts. |
| `UPLOAD_RETENTION_DAYS` | Deletes upload-run folders older than this. `docker-compose.yml` sets 30. `0` keeps everything. Database rows are never deleted. |

Never commit `.env` (it is git-ignored).

## 2. Start

```bash
docker compose --profile https up -d --build     # or without --profile https
docker compose logs -f
```

The first build takes several minutes (it downloads PyTorch and the YOLO
weights). Port 8501 is published on `127.0.0.1` only unless you set
`BIND_ADDRESS`, so nothing is exposed except through Caddy.

## 3. HTTPS

The `https` profile runs Caddy using `deploy/Caddyfile.compose`. The domain must
already point at the server, otherwise the certificate request fails (check
`docker compose logs caddy`). If you use your own proxy instead (nginx, a cloud
load balancer), leave the profile off, keep `BIND_ADDRESS=127.0.0.1`, and
proxy to port 8501 with WebSocket support; `deploy/nginx.conf` and
`deploy/Caddyfile` are starting points. Never expose port 8501 directly with a
password: it would travel in clear text.

### Per-user sign-in

* **Accounts** (simplest): create them once with
  `docker compose exec traffic-agent python -m app.users add NAME --role admin`
  (roles: viewer, operator, admin). They live in `/data/users.json`, hashed.
* **Identity-aware proxy** (campus/company login): run oauth2-proxy or
  Cloudflare Access in front, set `AUTH_MODE=proxy`, `AUTH_PROXY_ADMINS`,
  `AUTH_PROXY_OPERATORS` (emails). Everyone else the proxy lets in is a viewer.
  See `deploy/oauth2-proxy.cfg`. **The app must be reachable only through the
  proxy** (bind it to `127.0.0.1` or a private network); otherwise anyone can
  send the identity header themselves.

### Rate limiting and monitoring

* The app locks a username (and a calling address) after repeated wrong
  passwords, for the whole server, for a growing time. The counts live in
  memory and reset on restart.
* Also limit at the proxy: `deploy/nginx.conf` and `deploy/Caddyfile` are
  working starting points. Make the proxy *overwrite* `X-Forwarded-For`, as
  they do, because the app uses it for the address limit.
* `deploy/fail2ban-traffic-agent.conf` bans addresses that keep failing, using
  the app's log.
* Logs: `docker compose logs -f`, and `/data/logs/traffic_agent.log` (rotated).
  The audit trail is on the Admin page.
* Uptime: monitor `https://your-domain/_stcore/health`. For deeper checks run
  `docker compose exec traffic-agent python -m app.health --json` from cron.

## 4. Verify the deployment

```bash
docker compose exec traffic-agent python scripts/check_setup.py --full --production
curl -I https://your-domain/_stcore/health     # 200 OK
```

`--production` turns a missing sign-in or `APP_ENV` into a failure and warns
about a missing domain, retention, fine table or backup folder. Then open the
site, sign in, press **Try the sample video** on *Analyze footage* and confirm
the Dashboard shows the new violations.

## Data and backups

Everything the app writes (the SQLite database, uploads, evidence images,
annotated videos) lives in the `traffic_data` Docker volume, mounted at
`/data`.

**Backups are automatic.** The `maintenance` container writes
`traffic-data-<time>.tgz` (a consistent copy of the database, the evidence and
output files and `users.json`) to `BACKUP_PATH` every 24 hours and keeps the
newest `BACKUP_KEEP`. Before each backup it checks the record chain and appends
the head hash to `integrity-heads.log` in the same folder. Read what it did:

```bash
docker compose logs maintenance
docker compose exec maintenance python -m app.maintenance --once   # run now
```

A backup on the same disk does not survive that disk failing: point
`BACKUP_PATH` at another disk, and copy the folder (with
`integrity-heads.log`) off the machine as well. To restore, stop the app,
extract the archive into the `traffic_data` volume and start it again:

```bash
docker compose down
docker run --rm -v traffic-agent_traffic_data:/data -v "$PWD/backup":/b alpine \
    tar xzf /b/traffic-data-YYYYMMDD-HHMMSS.tgz -C /data
docker compose --profile https up -d
```

(Volume names are `<project folder>_traffic_data`; `docker volume ls` shows
them.) Evidence images are only ever served from the project folder or the data
directory; paths outside are refused.

## Security notes

* Roles (viewer, operator, admin) are enforced in the app, but the checks are
  in the page code of a single-process Streamlit app: treat it as appropriate
  for a team or a college project, not for a hostile public audience.
* Uploads are restricted to known image and video types, renamed on disk, and
  size-limited (200 MB, `.streamlit/config.toml`).
* The container runs as a non-root user.
* Live camera addresses may contain passwords. They are kept out of the screen,
  the logs and the audit trail, but they are in `.env` in clear text.
* License plates are personal data. Set `UPLOAD_RETENTION_DAYS`, limit who
  signs in, and check the law that applies to you before storing them.
* One server process runs the cameras; a restart stops them (start them again
  from the Live camera page).
* This is a student demonstration system. The fines are demo values and the
  detections are not legal evidence.

## Resource notes

* CPU-only inference runs at a few frames per second; long videos take a while.
  For speed, build a CUDA image on a GPU host instead (replace the torch line
  in the `Dockerfile` and run with the NVIDIA container runtime).
* `mem_limit: 4g` in `docker-compose.yml`; raise it for large videos.

## Other hosts

* **Streamlit Community Cloud**: a poor fit. The PyTorch dependency is large
  for its memory limits, the disk is not persistent (the database would be
  lost on restart), and there is no place for the emergency weights.
* **Render / Railway / Fly.io**: work with the Dockerfile (it honours `$PORT`).
  Attach a persistent disk at `/data`, and set `DASHBOARD_PASSWORD`,
  `APP_ENV=production` and `TRAFFIC_AGENT_DATA_DIR=/data`.
