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
│   ├── main.py
│   ├── video_processor.py
│   │
│   ├── detection/
│   │   └── detector.py
│   │
│   ├── tracking/
│   │   └── tracker.py
│   │
│   ├── violation/
│   │   └── violation_detector.py
│   │
│   ├── emergency/
│   │   └── signal_priority.py
│   │
│   ├── collision/
│   │   └── collision_detector.py
│   │
│   ├── alerts/
│   │   └── twilio_alert.py
│   │
│   └── database/
│       └── database.py
│
├── data/
│   ├── images/
│   ├── videos/
│   └── emergency_vehicle/
│
├── models/
├── outputs/
├── tests/
│
├── requirements.txt
├── .env
├── .gitignore
└── README.md
```

---

## 📊 Current Status

### Week 1 — ✅ Completed

* [x] Project structure created
* [x] Python virtual environment configured
* [x] Required dependencies installed
* [x] YOLOv8 tested
* [x] SQLite database initialized
* [x] Initial Streamlit application created

### Week 2 — ✅ Completed

* [x] YOLOv8 vehicle detection
* [x] Car detection
* [x] Truck detection
* [x] Bus detection
* [x] Motorcycle detection
* [x] ByteTrack integration
* [x] Persistent vehicle tracking IDs
* [x] Traffic video processing pipeline
* [x] Annotated output video generation
* [x] Initial Streamlit integration

### Current Development Status

**Detection and tracking modules are complete.**

The project is currently moving toward the **emergency-vehicle detection and downstream traffic-analysis modules**.

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

```markdown
## Roadmap

- [x] Project setup
- [x] YOLOv8 vehicle detection
- [x] ByteTrack vehicle tracking
- [ ] Custom emergency vehicle detection
- [ ] Emergency signal prioritization
- [ ] Red-light violation detection
- [ ] Speed violation detection
- [ ] Fine record generation
- [ ] Collision detection
- [ ] SQLite event logging
- [ ] Streamlit dashboard
- [ ] Twilio call/SMS alerts
- [ ] End-to-end integration
- [ ] Performance testing
- [ ] Accuracy evaluation
- [ ] Final project report
- [ ] Project presentation
- [ ] Demo video
```

---

## 📅 Development Timeline

| Week    | Development Stage               | Status     |
| ------- | ------------------------------- | ---------- |
| Week 1  | Project setup and environment   | ✅ Complete |
| Week 2  | YOLOv8 + ByteTrack integration  | ✅ Complete |
| Week 3  | Emergency vehicle detection     | ⏳ Next     |
| Week 4  | Detection/tracking improvements | ⏳ Planned  |
| Week 5  | Red-light violation detection   | ⏳ Planned  |
| Week 6  | Speed violation + fine records  | ⏳ Planned  |
| Week 7  | Emergency signal prioritization | ⏳ Planned  |
| Week 8  | Collision detection + Twilio    | ⏳ Planned  |
| Week 9  | Streamlit dashboard             | ⏳ Planned  |
| Week 10 | End-to-end integration          | ⏳ Planned  |
| Week 11 | Testing and evaluation          | ⏳ Planned  |
| Week 12 | Report, PPT, demo and viva      | ⏳ Planned  |

---

## ▶️ How to Run

### 1. Clone the repository

```bash
git clone YOUR_REPOSITORY_URL
cd Traffic-Agent
```

### 2. Create virtual environment

```bash
python -m venv venv
```

### 3. Activate environment

Windows PowerShell:

```powershell
venv\Scripts\activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Run traffic-video detection

```bash
python run_video.py
```

### 6. Run Streamlit

```bash
streamlit run app/main.py
```

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

**Current Stage: Week 2 Completed — YOLOv8 + ByteTrack Detection and Tracking Pipeline**

Development continues toward the complete intelligent traffic-agent system.
