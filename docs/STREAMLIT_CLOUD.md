# Deploy on Streamlit Community Cloud (free demo hosting)

Streamlit Community Cloud runs the dashboard straight from your GitHub
repository and gives you a public `https://....streamlit.app` link. It is good
for **showing the project**; it is not production hosting. Use
[DEPLOYMENT.md](DEPLOYMENT.md) (a server with Docker) for real use.

## What works and what does not

| | On Community Cloud |
|---|---|
| Upload photos or videos, sample video, all checks, e-challan PDFs, review | Works |
| Emergency-vehicle model | Works (it is in the repository) |
| Dashboard, Evidence, Alerts, roles | Works (one shared password; see below) |
| **Saved data** | **Temporary.** The disk is erased when the app restarts or sleeps after inactivity. Records, evidence and uploads are lost. |
| Live RTSP / webcam monitoring | **Not possible**: the cloud cannot reach cameras on your network |
| Daily backup / maintenance job, HTTPS config | Not needed or not available (HTTPS is provided) |
| Individual accounts (`users.json`) | They would be lost on restart: use one shared password |
| Plate reading | Off (EasyOCR is too large for the free tier) |
| Speed | Slow: shared CPU, no GPU. Use clips of 30 to 60 seconds |

The free tier has a modest memory limit (check the current numbers in the
Community Cloud documentation under "app resources and limits"). If the app
shows "gone over its resource limits", analyze shorter clips or reboot it.

## Steps

1. The repository must be on GitHub (it is). Merge this change into `main`.
2. Go to <https://share.streamlit.io>, sign in with GitHub and choose
   **Create app** -> **Deploy a public app from GitHub**.
3. Repository: `aditya182005/Real_Time_AI_Traffic_Monitoring_Violation_Enforcement`,
   branch `main`, **main file path `app/main.py`**.
4. Open **Advanced settings**:
   * **Python version: 3.11** (the project is tested on it; the newest default may
     not have wheels for every package yet).
   * **Secrets**: paste `deploy/streamlit_secrets.example.toml` and change
     `DASHBOARD_PASSWORD`.
5. **Deploy.** The first build takes several minutes: it installs CPU PyTorch
   and downloads the YOLO weights on the first analysis. Read the build log if
   it fails.
6. Open the link, sign in, go to **Analyze footage** and press **Try the sample
   video**.

Why it works: Community Cloud installs `app/requirements.txt` (next to the main
file, so it wins over the root `requirements.txt`), which uses CPU-only PyTorch
and headless OpenCV, and `packages.txt` (ffmpeg). The secrets become
environment variables, so `APP_ENV=production` plus `DASHBOARD_PASSWORD` keep
the app locked behind a password.

## Things to know

* **The link is public.** Anyone with it sees the sign-in page; only people with
  the password get in. Do not upload footage with faces or plates that you may
  not share, and do not use real camera addresses.
* The sidebar shows a warning that data is erased on restart (`DEMO_HOSTING=1`).
* The first deploy has not been tried from here (there is no access to
  Community Cloud). If the dependency install fails, the build log names the
  package; tell me and I will adjust `app/requirements.txt`.
