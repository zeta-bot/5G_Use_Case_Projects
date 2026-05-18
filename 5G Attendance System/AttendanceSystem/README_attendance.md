# Classroom Attendance System — RetinaFace + ArcFace

Automatically identifies students and marks attendance using face recognition.

---

## How it works

1. **Register** — photograph each student, extract a 512-dimensional face "fingerprint" (ArcFace embedding), store it
2. **Detect** — RetinaFace finds every face in the classroom photo/video
3. **Identify** — each detected face is compared to all stored fingerprints using cosine distance
4. **Mark** — if distance < 0.40 → present; otherwise → unknown/absent
5. **Export** — saves a timestamped CSV to the `attendance/` folder

---

## Install

```bash
pip install retina-face deepface opencv-python pandas openpyxl
```

First run downloads ArcFace weights (~500 MB) and RetinaFace weights (~1 GB) automatically.

---

## Step 1 — Register your students

### Option A: Folder of photos (recommended)
Organise student photos like this:
```
photos/
  Alice/
    photo1.jpg
    photo2.jpg
    photo3.jpg
  Bob/
    photo1.jpg
    photo2.jpg
```

Then run:
```bash
python attendance_system.py register --dir photos/
```

### Option B: One photo at a time
```bash
python attendance_system.py register --photo alice.jpg --name "Alice"
python attendance_system.py register --photo bob.jpg   --name "Bob"
```

---

## Step 2 — Take attendance

### From a classroom photo
```bash
python attendance_system.py image --source classroom.jpg
```

### Live webcam (real-time)
```bash
python attendance_system.py webcam --source 0
```
Controls: `s` = save attendance now | `r` = reload student DB | `q` = quit

### From a recorded video
```bash
python attendance_system.py video --source lecture.mp4
```

### List registered students
```bash
python attendance_system.py list
```

---

## Output

**Annotated image/video** → `output/attendance_<filename>`
- Green box = identified student (name + distance shown)
- Red box = unknown face

**Attendance CSV** → `attendance/attendance_<date>.csv`
```
name,distance,confidence,time
Alice,0.2341,0.9812,09:05:12
Bob,0.1987,0.9944,09:05:12
```

---

## Tuning the threshold

| `threshold` | Effect |
|-------------|--------|
| `0.30` | Stricter — fewer false positives, may miss some students |
| `0.40` | Default — good balance |
| `0.50` | Lenient — catches more faces but more false matches |

Edit `CFG["threshold"]` in the script to change it.

---

## Tips for better accuracy

- Use **3–5 photos per student** from different angles and lighting
- Avoid blurry or low-resolution registration photos
- For masked students, register photos with and without masks
- Use good classroom lighting — avoid strong backlight from windows
- For a large lecture hall, use a higher-resolution camera

---

## File structure

```
attendance_system.py     ← main script
face_db.pkl              ← student face database (auto-created)
photos/                  ← your student registration photos
output/                  ← annotated images/videos
attendance/              ← CSV attendance records
```
