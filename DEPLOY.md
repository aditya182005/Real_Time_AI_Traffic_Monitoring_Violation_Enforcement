# Deploying Traffic Agent

This guide puts the dashboard on a server so others can open it in a browser.
It was written without being able to run Docker in the authoring environment:
the CI workflow (`.github/workflows/ci.yml`) builds the image and runs
`python check_setup.py --full` inside it, so a green CI run is the real proof.
Do the same check yourself on the first deploy (step 4).

## What you need

* A Linux server or VM with Docker and the Compose plugin. 2 CPUs and 4 GB of
  RAM is the practical minimum (PyTorch and YOLO need the memory).
* A domain name pointing at it, for HTTPS.
* Optional: `models/emergency_vehicle.pt` (see the README, "Training the
  emergency-vehicle model").

## 1. Configure

```bash
cp .env.example .env
```

Edit `.env`:

| Setting | Why |
|---|---|
| `DASHBOARD_PASSWORD` | **Required in production.** With `APP_ENV=production` the app refuses to start without it. |
| `TWILIO_*`, `ALERT_TO_PHONE` | Optional SMS/voice alerts. Test first with `python -m app.alerts.twilio_alert --send` (see the README). |
| `CAMERA_ID` | Name stored with records and alerts. |
| `UPLOAD_RETENTION_DAYS` | Deletes upload-run folders older than this. `docker-compose.yml` sets 30. `0` keeps everything. Database rows are never deleted. |

Never commit `.env` (it is git-ignored).

## 2. Start

```bash
docker compose up -d --build
docker compose logs -f
```

The first build takes several minutes (it downloads PyTorch and the YOLO
weights). The app listens on port 8501.

## 3. HTTPS

Do not expose port 8501 directly: the password would travel in clear text.
Put a reverse proxy in front. With Caddy (automatic certificates), a
`Caddyfile`:

```
traffic.example.com {
    reverse_proxy localhost:8501
}
```

Streamlit needs WebSocket support, which Caddy and nginx (with the usual
`Upgrade` headers) both provide. Then close port 8501 to the outside in the
firewall, or change the compose port mapping to `127.0.0.1:8501:8501`.

## 4. Verify the deployment

```bash
docker compose exec traffic-agent python check_setup.py --full
curl -I https://traffic.example.com/_stcore/health     # 200 OK
```

Then open the site, log in, press **Try the sample video** on *Analyze
footage*, and confirm the Dashboard page shows the new violation.

## Data and backups

Everything the app writes (the SQLite database, uploads, evidence images,
annotated videos) lives in the `traffic_data` Docker volume, mounted at
`/data`. Back it up regularly:

```bash
docker run --rm -v traffic_agent_traffic_data:/data -v "$PWD":/backup alpine \
    tar czf /backup/traffic-data-$(date +%F).tgz -C /data .
```

(The volume name is `<project folder>_traffic_data`; `docker volume ls` shows
it.) Evidence images are only ever served from the project folder or the data
directory; paths outside are refused.

## Security notes

* One shared password protects the dashboard. There are no separate users or
  roles. For several people with different rights, put an identity-aware proxy
  (for example oauth2-proxy or Cloudflare Access) in front instead.
* Failed logins are slowed down, but there is no account lockout or IP rate
  limit; the reverse proxy is the place to add one.
* Uploads are restricted to known image and video types, renamed on disk, and
  size-limited (200 MB, `.streamlit/config.toml`).
* The container runs as a non-root user.
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
