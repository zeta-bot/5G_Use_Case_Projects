# 5G Attendance System

An automated classroom attendance system powered by face recognition. The system uses **RetinaFace** for face detection and **ArcFace** (via DeepFace) for identity matching — designed as a 5G use-case demonstrating real-time, low-latency video analytics over high-bandwidth networks.

---

## Repository Structure

```
5G_Use_Case_Projects/
│
├── 5G Attendance System/           ← Attendance pipeline
│   ├── attendance_system.py        ← Main script (register + take attendance)
│   ├── face_db.pkl                 ← Auto-generated student face database
│   └── README_attendance.md        ← Module-level notes
│
└── capture_face_images/            ← Dataset collection tool
    └── capture_face_images.py      ← Webcam capture script for registration photos
```

> **Recommended workflow:** use `capture_face_images.py` to collect student photos first, then use `attendance_system.py` to register those photos and run attendance.

---

## How It Works

```
┌──────────────────┐     ┌───────────────────┐     ┌──────────────────────┐
│  capture_face_   │     │  attendance_      │     │  Output              │
│  images.py       │────▶│  system.py        │────▶│                      │
│                  │     │                   │     │  ✔ Annotated image / │
│  Webcam →        │     │  RetinaFace       │     │    video             │
│  RetinaFace →    │     │  detects faces    │     │  ✔ attendance CSV    │
│  Cropped JPEGs   │     │                   │     │  ✔ Live webcam HUD   │
└──────────────────┘     │  ArcFace embeds   │     └──────────────────────┘
                         │  + matches faces  │
                         │                   │
                         │  Temporal         │
                         │  smoothing        │
                         │  (majority vote)  │
                         └───────────────────┘
```

1. **Capture** — photograph each student with `capture_face_images.py`; RetinaFace auto-crops to the face region.
2. **Register** — `attendance_system.py register` runs ArcFace on each photo and stores a 512-dimensional embedding per student in `face_db.pkl`.
3. **Detect** — RetinaFace locates every face in a classroom photo, live webcam feed, or recorded video.
4. **Identify** — each detected face is embedded with ArcFace and compared to all stored embeddings using cosine distance. Distance < threshold → student marked **present**.
5. **Smooth** — for video/webcam, a 15-frame sliding-window majority vote eliminates flickering labels.
6. **Export** — a timestamped CSV is saved to the `attendance/` folder after every session.

---

## Requirements

Python 3.10+

```bash
pip install opencv-python retina-face deepface tf-keras pandas openpyxl
```

> **First run:** ArcFace weights (~500 MB) and RetinaFace weights (~1 MB) are downloaded automatically.

---

## Quick Start

### Step 1 — Collect student photos (optional but recommended)

```bash
python capture_face_images.py -n 50 -o photos/Alice --size 224 224
# Repeat for each student
```

This saves 50 face crops for Alice into `photos/Alice/`. See [Capture Script Options](#capture-script-options) for all flags.

### Step 2 — Register students

**From a folder of photos (recommended)**

Organise photos like this:
```
photos/
  Alice/
    face_0000.jpg
    face_0001.jpg
  Bob/
    face_0000.jpg
```

Then run:
```bash
python attendance_system.py register --dir photos/
```

**One photo at a time**
```bash
python attendance_system.py register --photo alice.jpg --name "Alice"
```

### Step 3 — Take attendance

| Mode | Command |
|------|---------|
| Classroom photo | `python attendance_system.py image --source classroom.jpg` |
| Live webcam | `python attendance_system.py webcam --source 0` |
| Recorded video | `python attendance_system.py video --source lecture.mp4` |
| List registered students | `python attendance_system.py list` |

**Webcam controls:** `Ctrl+C` = stop and save attendance

---

## Output

**Annotated image / video** → `output/attendance_<filename>`

| Box colour | Meaning |
|-----------|---------|
| 🟢 Green | Identified student (name + cosine distance) |
| 🔴 Red | Unknown face |

Face landmarks (eyes, nose, mouth corners) are drawn as cyan dots.

**Attendance CSV** → `attendance/attendance_<session>_<datetime>.csv`

```
name,distance,confidence,time
Alice,0.2341,0.9812,09:05:12
Bob,0.1987,0.9944,09:05:12
```

Auto-saves trigger every ~2 minutes during a webcam session; a final save runs on exit.

---

## Capture Script Options

`capture_face_images.py` — collects face crops from your webcam.

| Flag | Default | Description |
|------|---------|-------------|
| `-n`, `--num-images` | `150` | Number of face crops to save |
| `-d`, `--delay` | `0.2` | Minimum seconds between saves |
| `-o`, `--output-dir` | `face_crops_<timestamp>` | Output directory |
| `--no-preview` | off | Disable live preview window |
| `-c`, `--camera` | `0` | Camera device index |
| `--threshold` | `0.9` | RetinaFace confidence cutoff (0–1) |
| `--padding` | `0.25` | Fractional padding around the face box |
| `--size W H` | no resize | Resize crops to W×H (e.g. `224 224`) |

---

## Tuning the Threshold

The cosine distance threshold in `attendance_system.py` (default `0.8`) controls how strict matching is.

| `threshold` | Effect |
|-------------|--------|
| `0.30` | Very strict — fewest false positives, but may miss students |
| `0.40` | Strict |
| `0.80` | Default — balanced |
| `0.90`+ | Lenient — catches more faces but risks false matches |

Edit `CFG["threshold"]` at the top of `attendance_system.py` to change it.

---

## Tips for Better Accuracy

- Register **3–10 photos per student** from different angles and lighting conditions.
- Use `capture_face_images.py` at the same location and lighting as the actual classroom.
- For masked students, register photos both with and without masks.
- Avoid strong backlight (e.g. windows behind students).
- For large lecture halls, use a higher-resolution camera and reduce the threshold slightly.
- Lower the capture `--threshold` flag (e.g. `0.75`) in poor lighting.

---

## File Reference

```
attendance_system.py     ← Main pipeline (register / image / webcam / video / list)
face_db.pkl              ← Student face database — auto-created on first register
capture_face_images.py   ← Webcam tool for collecting registration photos
photos/                  ← Your student photo folders (you create this)
output/                  ← Annotated images and videos
attendance/              ← CSV attendance records
```

---

## 5G Relevance

This project is designed as a **5G use case** demonstrating:

- **High-bandwidth streaming** — HD/4K classroom video streamed from a camera unit to an edge server over 5G NR.
- **Ultra-low latency inference** — RetinaFace + ArcFace run at the 5G edge (MEC), returning results in near real-time.
- **Massive device connectivity (mMTC)** — scalable to multi-room or multi-campus deployments with many simultaneous camera feeds.
- **Reliable automated record-keeping** — attendance CSVs generated without any manual input, synced over the 5G core.
