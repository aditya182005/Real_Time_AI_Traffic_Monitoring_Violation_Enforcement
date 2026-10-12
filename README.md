# 🚦 AI-Based Smart Traffic Monitoring and Automated Traffic Violation Enforcement System

An AI-powered **Smart Traffic Monitoring System** that acts as an intelligent traffic agent using **YOLOv8, ByteTrack, OpenCV, Streamlit, SQLite, and Twilio**.

The system is designed to monitor traffic in real time, track vehicles, identify traffic violations, prioritize emergency vehicles, detect possible collisions, and automatically send emergency alerts.

---

## 📌 Project Overview

The **AI-Based Smart Traffic Monitoring and Automated Traffic Violation Enforcement System** is an intelligent traffic-management solution designed to combine multiple traffic-monitoring functions into a single AI-driven pipeline.

The system processes traffic-camera video using **YOLOv8** for vehicle detection and **ByteTrack** for multi-object tracking.

The planned system provides five major capabilities:

* 🚗 Real-time vehicle detection and tracking
* 🚑 Emergency vehicle detection and signal prioritization
* 🚦 Traffic violation detection and fine-record generation
* 💥 Collision detection and emergency response
* 📊 Real-time traffic monitoring through a Streamlit dashboard

The project aims to improve **traffic flow, road safety, traffic-rule enforcement, and emergency response time** through an integrated system.

---

## ✨ What You Can Do With It

* **Upload your own footage.** Open **Analyze footage** and drop in traffic
  **photos** (JPG, PNG, BMP, WebP) or a **video** (MP4, AVI, MOV, MKV). Photos
  get vehicle counts and annotated downloads. Videos get the full pipeline, a
  live annotated preview, and an annotated video to play or download.
* **Place the lines on your own camera view.** Stop line, speed lines and the
  wrong-way lane are sliders in percent of the frame, drawn on the first
  frame, so they work at any resolution.
* **Checks you can switch on:** red light (against a simulated signal that is
  always red, always green, or cycles), speeding (two lines a known distance
  apart), wrong way, possible collisions (overlap **and** a sharp slowdown),
  and emergency-vehicle priority (turns the simulated signal green).
* **Everything is saved** to SQLite with annotated evidence and a cropped
  photo of the vehicle, and shown on the **Dashboard**, **Evidence** and
  **Alerts** pages: violations per hour, traffic density, violation types,
  filterable records, CSV export, and Twilio alert status.
* **Alerts are opt-in.** Collision SMS (and optional voice call) go out only
  when Twilio is configured **and** you turn alerts on for that run. They
  include the camera name and a UTC timestamp.

---

## 🎯 Project Goals

* Detect vehicles from traffic-camera video in real time.
* Track vehicles across multiple video frames using persistent IDs.
* Detect emergency vehicles such as ambulances, police vehicles, and fire trucks.
* Prioritize green signals when an emergency vehicle is detected.
* Detect red-light and speeding violations.
* Generate digital records for detected violations.
* Detect possible vehicle collisions.
* Automatically notify an ambulance/control room using Twilio.
* Provide traffic authorities with a real-time monitoring dashboard.
* Store violation and event information using SQLite.

---

## 🏗️ System Architecture

```text
                    Traffic Camera / Video
                            │
                            ▼
                     ┌─────────────┐
                     │   YOLOv8    │
                     │  Detection  │
                     └──────┬──────┘
                            │
                            ▼
                     ┌─────────────┐
                     │  ByteTrack  │
                     │   Tracking  │
                     └──────┬──────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
        Emergency       Violation      Collision
        Detection       Detection      Detection
              │             │             │
              ▼             ▼             ▼
       Signal Priority   Fine Record   Twilio Alert
              │             │             │
              └─────────────┼─────────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │    Streamlit    │
                   │    Dashboard    │
                   └─────────────────┘
```

---

## 🛠️ Technology Stack

| Technology               | Purpose                      |
| ------------------------ | ---------------------------- |
| Python                   | Core implementation          |
| YOLOv8                   | Real-time object detection   |
| ByteTrack                | Multi-object tracking        |
| OpenCV                   | Video processing             |
| Streamlit                | Monitoring dashboard         |
| SQLite                   | Violation and event storage  |
| Twilio                   | Automated call/SMS alerts    |
| Google Colab / Local GPU | Model training and inference |

---

## 📂 Project Structure

```text
Traffic-Agent/
│
├── app/
│   ├── main.py                    # Streamlit entry point (sidebar pages)
│   ├── video_processor.py         # unified per-frame pipeline for a video
│   ├── analysis.py                # image analysis + video settings
│   ├── media.py                   # upload validation, image decode, H.264 re-encode
│   ├── annotate.py                # drawing boxes, banners, calibration lines
│   │
│   ├── ui/                        # dashboard pages
│   │   ├── upload.py              # Analyze footage (images + video upload)
│   │   ├── dashboard.py           # KPIs and analytics charts
│   │   ├── evidence.py            # evidence gallery
│   │   ├── alerts.py              # collision alerts + Twilio status
│   │   ├── about.py, theme.py, analytics.py, data.py, helpers.py
│   │
│   ├── detection/
│   │   ├── detector.py            # YOLOv8 vehicle detection
│   │   └── emergency_detector.py  # custom emergency-vehicle model
│   ├── tracking/tracker.py        # ByteTrack tracking
│   │
│   ├── violation/
│   │   ├── red_light.py           # stop-line crossing
│   │   ├── signal.py              # simulated signal (fixed or cycle)
│   │   ├── speed_estimator.py     # two-line speed measurement
│   │   ├── wrong_way.py           # against-traffic movement
│   │   ├── collision_logic.py     # overlap + sharp-slowdown heuristic
│   │   ├── violation_logger.py    # SQLite tables, demo fines, migrations
│   │   ├── speed.py, collision.py # standalone scripts
│   │
│   ├── emergency/signal_priority.py   # standalone emergency-priority script
│   ├── alerts/twilio_alert.py         # SMS / voice alerts, status logging
│   └── database/database.py           # legacy tables
│
├── data/                          # sample video, images, emergency dataset
├── models/                        # put emergency_vehicle.pt here (git-ignored)
├── outputs/                       # generated evidence, videos, uploads (git-ignored)
├── tests/                         # pytest / unittest tests
├── .streamlit/config.toml         # theme and the 200 MB upload limit
│
├── run_video.py                   # command-line runner for the whole pipeline
├── init_database.py
├── train_emergency.py             # trains and installs the emergency model
├── check_setup.py                 # is this computer ready? (--full runs the models)
├── requirements.txt / requirements-dev.txt
├── .env.example                   # copy to .env for Twilio
└── README.md
```

---

## 📊 Current Status

All modules in the preparation plan have code, tests and a place in the
dashboard. What has **not** been done is validation on real footage: the
automated tests use stand-in detectors, so thresholds still need tuning on
your own videos.

| Area | State |
| ---- | ----- |
| Vehicle detection (YOLOv8) and tracking (ByteTrack) | ✅ Implemented |
| Red-light, speeding and wrong-way checks, fine records | ✅ Implemented |
| Collision heuristic (overlap + sharp slowdown, several frames) | ✅ Implemented |
| Twilio SMS / voice alerts with camera ID and timestamp | ✅ Implemented (needs your Twilio account to try) |
| Simulated signal and emergency-vehicle override | ✅ Implemented |
| Streamlit dashboard, evidence and alerts pages | ✅ Implemented |
| Upload of images and videos | ✅ Implemented |
| Emergency-vehicle **model weights** | ⏳ Train with `train_emergency.py` (not in git) |
| Accuracy evaluation (mAP, precision/recall on labelled clips) | ⏳ Not done |
| Report, slides, demo video | ⏳ Not done |

---

## 🖼️ Screenshots / Demo

### YOLOv8 + ByteTrack Detection

Add your working detection screenshot here:

<img width="1112" height="673" alt="image" src="https://github.com/user-attachments/assets/37183127-efcc-417e-a497-55eefcc53a59" />


Recommended screenshot:

* Traffic video frame
* Bounding boxes around vehicles
* Vehicle class names
* Persistent tracking IDs

Example:

```text
┌─────────────────────────────────────────┐
│                                         │
│     ┌─────────────┐                     │
│     │     CAR     │                     │
│     │    ID: 1    │                     │
│     └─────────────┘                     │
│                                         │
│                     ┌──────────────┐    │
│                     │    TRUCK     │    │
│                     │     ID: 2    │    │
│                     └──────────────┘    │
│                                         │
└─────────────────────────────────────────┘
```

### Streamlit Dashboard

Add the dashboard screenshot when the dashboard UI is further developed:


<img width="1116" height="500" alt="image" src="https://github.com/user-attachments/assets/717bb751-8b87-4add-88d9-cdfad24879ab" />


---

## 🗺️ Roadmap

- [x] Project setup
- [x] YOLOv8 vehicle detection
- [x] ByteTrack vehicle tracking
- [x] Red-light violation detection
- [x] Speed violation detection
- [x] Wrong-way detection
- [x] Fine record generation
- [x] Collision detection
- [x] SQLite event logging
- [x] Streamlit dashboard
- [x] Upload of images and videos
- [x] Twilio call/SMS alerts
- [x] Emergency signal prioritization (simulated)
- [ ] Train and add the emergency-vehicle model weights
- [ ] Performance testing on real footage
- [ ] Accuracy evaluation
- [ ] Final project report
- [ ] Project presentation
- [ ] Demo video

---

## 📅 Development Timeline

| Week    | Development Stage               | Status                          |
| ------- | ------------------------------- | ------------------------------- |
| Week 1  | Project setup and environment   | ✅ Complete                      |
| Week 2  | YOLOv8 + ByteTrack integration  | ✅ Complete                      |
| Week 3  | Emergency vehicle detection     | 🟡 Code ready, model to train    |
| Week 4  | Detection/tracking improvements | ✅ Complete                      |
| Week 5  | Red-light violation detection   | ✅ Complete                      |
| Week 6  | Speed violation + fine records  | ✅ Complete                      |
| Week 7  | Emergency signal prioritization | ✅ Complete (simulated)          |
| Week 8  | Collision detection + Twilio    | ✅ Complete                      |
| Week 9  | Streamlit dashboard             | ✅ Complete                      |
| Week 10 | End-to-end integration          | ✅ Complete (uploads, unified pipeline) |
| Week 11 | Testing and evaluation          | ⏳ Next: real-footage tuning, metrics |
| Week 12 | Report, PPT, demo and viva      | ⏳ Planned                       |

---

## ▶️ How to Run

### 1. Clone the repository

```bash
git clone https://github.com/aditya182005/Real_Time_AI_Traffic_Monitoring_Violation_Enforcement.git
cd Real_Time_AI_Traffic_Monitoring_Violation_Enforcement
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
```

Windows PowerShell: `venv\Scripts\activate` — macOS/Linux: `source venv/bin/activate`

### 3. Install dependencies

```bash
pip install -r requirements.txt        # add -r requirements-dev.txt for tests
```

`yolov8n.pt` is downloaded automatically by Ultralytics on first run.

### Check that everything works

```bash
python check_setup.py          # quick: packages, files, Twilio settings (seconds)
python check_setup.py --full   # also loads YOLO and runs it on data/images/test.jpg
```

Each line is `OK`, `WARN` (a feature is off, for example no emergency model or
no Twilio) or `FAIL` (the app will not run), with the command that fixes it.
`--full` is the real end-to-end test of detection and tracking. It downloads
`yolov8n.pt` the first time, so it needs internet. Run it before your first
demo.

### 4. (Optional) Twilio collision alerts

Without Twilio, collisions are still detected and logged; only the message is
skipped. To get a real SMS (and optionally a voice call):

1. Create a free account at [twilio.com](https://www.twilio.com) and, in the
   Console, get a **phone number** that can send SMS.
2. Copy the **Account SID** (starts with `AC`) and **Auth Token** from the
   Console home page.
3. **Trial accounts can only message numbers you have verified.** Add your
   own phone under *Phone Numbers → Verified Caller IDs* first.
4. Create your settings file and fill it in:

   ```bash
   cp .env.example .env
   ```

   | Setting | Value |
   | ------- | ----- |
   | `TWILIO_ACCOUNT_SID` | starts with `AC` |
   | `TWILIO_AUTH_TOKEN` | from the Console (keep it secret) |
   | `TWILIO_PHONE_NUMBER` | your Twilio number, like `+14155550123` |
   | `ALERT_TO_PHONE` | the phone to alert (verified, for trial accounts) |
   | `ALERT_VOICE_CALL` | `true` to also place a call (optional) |
   | `CAMERA_ID` | name used in alerts, e.g. `NH-4-Junction` (optional) |

   Numbers must be in international format (`+` and the country code). `.env`
   is git-ignored, so your secrets are not committed.
5. Check the setup. This never prints your secrets:

   ```bash
   python -m app.alerts.twilio_alert            # checks the settings
   python -m app.alerts.twilio_alert --send     # sends one real test SMS
   python -m app.alerts.twilio_alert --send --call   # SMS and a test call
   ```

   The **Alerts** page of the dashboard has the same check and a *Send a test
   message* button.

Alerts are **opt-in for every run**: tick *Send an SMS for each collision
found* on the Analyze page (or pass `--send-alerts --collisions` to
`run_video.py`). Each alert names the camera and gives a UTC time, and the
result (`sent`, `skipped` or `failed: …`) is saved on the collision record and
shown on the Alerts page. Common failures show a plain hint, for example Twilio
error 21608 means the number to alert is not verified on a trial account.
Trial messages carry a "Sent from your Twilio trial account" prefix, and
Twilio may bill per message once you upgrade.

The Alerts page also shows the two Twilio figures from the evaluation plan:
the **success rate** (sent out of sent plus failed; skipped alerts are not
counted) and the **typical delay** from the collision being detected to
Twilio's reply (median, sent alerts only). The delay is to Twilio accepting
the message, not to the phone receiving it.

> **Test safely.** While developing, set `ALERT_TO_PHONE` to **your own
> phone**, never to an ambulance, police or control-room number. Collision
> alerts come from a heuristic and need a person to verify them.

### 5. Start the dashboard

Run everything from the project root so relative paths resolve.

```bash
streamlit run app/main.py
```

Pages (sidebar):

* **Analyze footage** — upload photos or a video, place the lines, run the
  checks. Use **Try the sample video** to see it work with the bundled clip.
* **Dashboard** — KPIs, violations per hour, traffic density, filterable records.
* **Evidence** — annotated frames and vehicle crops for each event.
* **Alerts** — collision alerts, Twilio status and a test-message button.

For in-browser playback of the annotated video the app converts it to H.264
with **ffmpeg** (installed with `pip install -r requirements.txt` through
`imageio-ffmpeg`, or use a system ffmpeg). Without it you can still download
the result. Uploads are limited to 200 MB (`.streamlit/config.toml`).

### 6. Or run the pipeline from the command line

```bash
python run_video.py --no-display                        # red-light check only
python run_video.py --no-display --speed --distance-m 12 --speed-limit 50 \
                    --wrong-way --collisions --signal cycle
python run_video.py --input my_clip.mp4 --no-save       # try it without saving
python run_video.py --help                              # every option
```

Positions are percentages of the frame, so they work at any resolution. Tune
them with the **Analyze footage** page first, which draws them on your video.
The standalone `python -m app.violation.speed`, `app.violation.collision` and
`app.emergency.signal_priority` scripts still exist; their lines and zones are
hard-coded for the sample video.

### 7. Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests use stand-in detectors, so they do not need model weights or a GPU.

### Training the emergency-vehicle model

The weights are not stored in git, so train them once (the dataset in
`data/emergency_vehicle/` has ambulances, fire trucks and police cars):

```bash
python train_emergency.py                      # 30 epochs
python train_emergency.py --epochs 60 --device 0   # first GPU
```

On a CPU this takes hours; a free **Google Colab** GPU session is much faster
(upload the project, run the command, download `models/emergency_vehicle.pt`).
The script checks the dataset first, then copies the best weights to
`models/emergency_vehicle.pt` itself. Confirm with
`python check_setup.py --full`. The Analyze page's emergency option and
`run_video.py --emergency` turn on once that file exists.

---

## 📈 Evaluation Metrics

The project will evaluate:

* **Detection:** mAP@0.5
* **Tracking:** ID-switch rate / ID persistence
* **Violation detection:** Precision and Recall
* **Real-time performance:** FPS
* **Twilio:** Alert success rate and alert latency

---

## ⚠️ Project Limitations

* Traffic-signal hardware is simulated rather than physically controlled.
* Collision testing uses staged/simulated footage.
* Speed estimation depends on camera calibration.
* Emergency-vehicle detection requires a custom dataset.
* Twilio trial accounts may have testing limitations.

---

## 🔮 Future Scope

* Integration with real traffic-signal hardware.
* Larger emergency-vehicle dataset.
* Improved collision-detection models.
* Automatic license-plate recognition.
* Cloud-based traffic monitoring.
* Integration with real traffic-control centers.
* More advanced traffic-density and congestion analytics.

---

## 👨‍💻 Project Development

**Academic Final-Year / Capstone Project**

**Project:** AI-Based Smart Traffic Monitoring and Automated Traffic Violation Enforcement System

**Core Technologies:** YOLOv8 • ByteTrack • OpenCV • Streamlit • SQLite • Twilio

---

## ⭐ Project Status

**Current Stage: all plan modules implemented and tested with stand-in detectors. Next: train the emergency-vehicle model, tune on real footage, run the accuracy evaluation, and write the report.**
