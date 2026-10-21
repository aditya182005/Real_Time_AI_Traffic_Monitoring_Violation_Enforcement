# Configuration

Settings are read from environment variables. Copy `.env.example` to `.env`
and edit it. `.env` is git-ignored; never commit it.

## Alerts

| Variable | Default | Meaning |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | empty | Account SID (starts with `AC`). Blank disables alerts. |
| `TWILIO_AUTH_TOKEN` | empty | Auth token. |
| `TWILIO_PHONE_NUMBER` | empty | Your Twilio number, international format. |
| `ALERT_TO_PHONE` | empty | Who to alert. Trial accounts: must be verified. |
| `ALERT_VOICE_CALL` | `false` | Also place a call for each collision. |
| `CAMERA_ID` | `CAM-01` | Camera name stored with records and alerts. |

## Deployment and storage

| Variable | Default | Meaning |
|---|---|---|
| `APP_ENV` | empty | `production` makes the app refuse to start without sign-in. |
| `TRAFFIC_AGENT_DATA_DIR` | project folder | Where the database, evidence and logs live (`/data` in Docker). |
| `UPLOAD_RETENTION_DAYS` | `0` | Delete upload-run folders older than this. `0` keeps all. Database rows are never deleted. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. Logs go to console and `logs/traffic_agent.log`. |

## Sign-in

| Variable | Default | Meaning |
|---|---|---|
| `AUTH_MODE` | auto | `users`, `password` or `proxy`. Blank: accounts if a users file exists, else the password. |
| `DASHBOARD_PASSWORD` | empty | One shared password. |
| `DASHBOARD_PASSWORD_ROLE` | `operator` | Role given for the shared password. |
| `USERS_FILE` | `users.json` in data folder | Where accounts are stored. |
| `AUTH_PROXY_HEADER` | `X-Forwarded-Email` | Header an identity-aware proxy sets (proxy mode). |
| `AUTH_PROXY_ADMINS`, `AUTH_PROXY_OPERATORS` | empty | Emails given those roles. |
| `AUTH_PROXY_DEFAULT_ROLE` | `viewer` | Role for everyone else. |

## Live cameras

| Variable | Default | Meaning |
|---|---|---|
| `LIVE_CAMERAS` | empty | `Name=address;Name2=address`. Addresses may hold passwords: keep `.env` private. |
| `LIVE_ALLOW_CUSTOM` | `false` | Allow typing any address on a production server. |
| `LIVE_MAX_CAMERAS` | `1` | Cameras analyzed at once. |

## License plates

| Variable | Default | Meaning |
|---|---|---|
| `PLATE_REGION` | `IN` | `IN` applies the Indian plate format when cleaning OCR text; `ANY` does not. |
| `PLATE_OCR` | empty | `off` disables plate reading even if EasyOCR is installed. |

Plate reading needs `pip install -r requirements/plates.txt` (large download).

See [DEPLOYMENT.md](DEPLOYMENT.md) for server settings.
