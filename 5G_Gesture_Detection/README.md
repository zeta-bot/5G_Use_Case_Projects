# Real-Time Hand Gesture To Voice App

Production-oriented, low-latency Python app:

`Webcam -> MediaPipe Hands -> Gesture Classifier -> Debounced Text Buffer -> Async TTS -> Audio`
This repository is cleaned for GitHub: no training images or personal photos are included.

## Performance metrics

These numbers help set expectations for latency and throughput. End-to-end camera FPS depends on hardware, exposure, and `cv2.imshow` overhead; the in-app **FPS** readout is an exponentially smoothed estimate of the main loop.

### Vision and inference (current MLP build)

| Metric | Value | Notes |
|--------|-------|--------|
| Default capture size | 960×540 | `--width` / `--height` |
| Landmark feature size | 63 floats | 21 landmarks × (x, y, z), wrist-centered and scale-normalized |
| Hand tracking + classify (representative) | ~15.7 ms / frame (~64 FPS) | 300 synthetic frames on **Apple M1 Pro**, macOS, Python 3.9, MediaPipe Hands + sklearn MLP; measures `InferencePipeline.run_frame` only (no camera read, no UI) |
| TTS | Non-blocking | Synthesis runs on a worker thread so the vision loop is not held on speak |

### Gesture model (holdout from `models/training_report.txt`)

| Metric                      | Value                           |
| --------------------------- | ------------------------------- |
| Overall accuracy (weighted) | **97.6%** (mini 5-class model)  |
| Macro F1                    | **0.9733** (mini 5-class model) |
| Evaluation support          | 332 rows in the reported split  |

Re-train or re-export `models/training_report.txt` after new data; metrics above describe the **current** checked-in model only.

### Stability timing (defaults)

| Setting | Default | Effect |
|---------|---------|--------|
| `--infer-interval-sec` | 3.0 | Hand tracking + classification run at most once per this interval; the window shows **live** video every frame. A **green border** (and green “Gesture” label) marks the captured frame and the only moments input is fed to the model. |
| `--sample-border-sec` | 0.35 | How long the green border stays visible after each capture (so it is noticeable at normal FPS). |
| `--stable-frames` | 1 | The same predicted label must repeat on this many consecutive **inference samples** before the buffer commits. With the default 3 s interval, each step is ~3 s. |
| `--cooldown-frames` | 1 | After a commit, skip this many inference samples before another commit. |

There is **no** confidence cutoff: the classifier’s top class is always used (confidence is shown for information only).
****
## Features

- Real-time webcam inference with MediaPipe Hands (21 landmarks)
- Landmark normalization (wrist-centered + scale invariant)
- Classifier options:
  - Trained MLP model (`models/gesture_model.pkl`) with probabilities
  - Rule-based fallback (works out of the box)
- Debounced text buffer with stable multi-frame commit logic
- Expanded fallback vocabulary without model training
- Async non-blocking TTS queue
- Lightweight TTS default is `pyttsx3` (good Docker fit)
- Kokoro TTS is optional (`--tts-backend kokoro`)
- Optional fallback chain (when enabled): Kokoro -> Coqui -> pyttsx3 -> macOS `say`
- OpenCV UI overlays for gesture, confidence, FPS, current mode, sentence
- Word mode and character mode switch
- Spoken sentence logging to `data/spoken_log.txt` (created at runtime; ignored by git)

## Project Structure

```text
hand_gesture_voice_app/
├── core/
│   ├── hand_tracker.py
│   ├── gesture_model.py
│   └── inference.py
├── tts/
│   └── engine.py
├── app/
│   ├── main.py
│   ├── buffer.py
│   └── ui.py
├── models/
│   ├── gesture_model.pkl       # trained MLP weights (checked in)
│   ├── labels.json             # class-id -> label
│   └── training_report.txt     # holdout metrics
├── data/
│   ├── mini_vocab.txt          # phrase labels used by the checked-in model
│   └── word_map_mini.json      # label -> spoken output
├── scripts/
│   ├── build_landmark_dataset_from_images.py
│   ├── collect_vocab_data.py
│   ├── generate_bootstrap_dataset.py
│   └── train_model.py
├── 5g_hackathon_2026_proposal.tex
└── README.md
```

## Install

```bash
cd /Users/arjavsethi/Downloads/hand_gesture_voice_app
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Run App

```bash
python app/main.py
```

Useful flags:

```bash
python app/main.py --camera-index 0 --mode word --infer-interval-sec 3
python app/main.py --camera-source 0 --mode word --infer-interval-sec 3
python app/main.py --camera-source "rtsp://user:pass@192.168.1.10:554/stream1"
python app/main.py --camera-source "rtsp://user:pass@192.168.1.10:554/stream1" --rtsp-transport tcp --open-timeout-ms 8000 --read-timeout-ms 8000
python app/main.py --mode char
python app/main.py --voice "<voice-id>"
python app/main.py --tts-backend pyttsx3
python app/main.py --tts-backend kokoro
python app/main.py --tts-backend kokuro
python app/main.py --tts-backend kokoro --allow-tts-fallback
python app/main.py --tts-backend pyttsx3 --tts-toggle-primary pyttsx3 --tts-fallback-backend say
python app/main.py --require-mlp --mode word --word-map data/word_map_mini.json
```

### Mini Phrase Model (Recommended For Accuracy)

This repo currently ships a **small phrase-only** MLP (5 classes) to reduce confusion vs large multi-symbol models.

Phrase classes:
`HOW_ARE_YOU`, `PLEASE`, `I_NEED_HELP`, `GOOD_MORNING`, `HAPPY_BIRTHDAY`

Run the app with the phrase map:

```bash
python app/main.py --require-mlp --mode word --word-map data/word_map_mini.json
```

Collect webcam samples + retrain (recommended):

```bash
python scripts/collect_vocab_data.py \
  --vocab-file data/mini_vocab.txt \
  --out data/mini_webcam_gestures.csv \
  --samples-per-label 300 \
  --camera-index 0 \
  --auto-next

python scripts/train_model.py \
  --data data/mini_webcam_gestures.csv \
  --vocab-file data/mini_vocab.txt \
  --min-samples-per-class 200 \
  --hidden-layers 256,128 \
  --max-iter 800
```

Vocabulary: `data/mini_vocab.txt`. Spoken phrases: `data/word_map_mini.json`.

Note on `HUNGRY`: the provided `hungry/` images did not produce any MediaPipe hand detections, so the landmark dataset contained 0 usable `HUNGRY` samples. To add `HUNGRY`, you’ll need a different set of images where MediaPipe Hands can detect the hand reliably.

Kokoro install (if missing):

```bash
pip install kokoro sounddevice
```

## Docker

Build:

```bash
docker build -t gesture-voice-app:latest .
```

Run (uses lightweight `pyttsx3` by default):

```bash
docker run --rm -it gesture-voice-app:latest
```

Run with host camera (Linux example):

```bash
docker run --rm -it \
  --device=/dev/video0 \
  -e CAMERA_SOURCE=0 \
  -e TTS_BACKEND=pyttsx3 \
  gesture-voice-app:latest
```

## Keyboard Controls

- `q`: quit
- `s`: speak current sentence
- `c`: clear sentence
- `m`: switch mode (`word` <-> `char`)
- `t`: test TTS audio output
- `v`: toggle TTS backend (`--tts-toggle-primary` <-> fallback backend)

## Fallback Gesture Vocabulary

When no trained model is present, the built-in rule-based mode supports:

- Words (17):
  `HELLO`, `YES`, `NO`, `THANKS`, `PLEASE`, `SORRY`, `HELP`, `I`, `YOU`, `WE`, `GO`, `STOP`, `WATER`, `FOOD`, `LOVE`, `WANT`, `NEED`
- Sentence gestures (2):
  `I_NEED_WATER`, `I_NEED_FOOD`
- Control gestures (4):
  `SPACE`, `DELETE`, `CLEAR`, `SPEAK`

----


## MLP Vocabulary Reference

**Checked-in model:** A small phrase-only MLP (5 classes). See `models/labels.json` and `data/word_map_mini.json`.

| Label | Spoken Output |
|---|---|
| `GOOD_MORNING` | `good morning` |
| `HAPPY_BIRTHDAY` | `happy birthday` |
| `HOW_ARE_YOU` | `how are you` |
| `I_NEED_HELP` | `I need help` |
| `PLEASE` | `please` |


## How It Works (Technical)

### 1) Frame Acquisition

- The app reads frames from either:
  - local camera index (`--camera-index` or `--camera-source 0`)
  - RTSP source (`--camera-source rtsp://...`)
- For RTSP streams, OpenCV FFmpeg options are configured with transport (`tcp`/`udp`) and open/read timeouts.

### 2) Hand Tracking and Landmark Extraction

- File: `core/hand_tracker.py`
- MediaPipe Hands detects a single hand and returns 21 landmarks.
- Each landmark has `(x, y, z)` coordinates.
- Raw shape per frame: `(21, 3)` -> flattened to 63 features.

### 3) Landmark Normalization (translation + scale invariance)

- Wrist landmark (`id=0`) is used as origin:
  - `centered = landmarks - wrist`
- Scale is computed as max radial distance from wrist:
  - `scale = max(norm(centered[i]))`
- Normalized features:
  - `normalized = centered / max(scale, 1e-6)`
- Result is robust to hand position and approximate hand size changes.

### 4) Gesture Identification

- File: `core/gesture_model.py`
- Two classifier modes:
  1. **MLP mode** (if `models/gesture_model.pkl` and `models/labels.json` exist):
     - Input: `1 x 63` normalized feature vector
     - Output: class probabilities via `predict_proba`
     - Decision: `argmax(probabilities)` + confidence score
  2. **Rule-based fallback**:
     - Finger open/closed state is computed for thumb/index/middle/ring/pinky
     - A 5-bit finger-state tuple maps to labels (words + control + sentence gestures)
     - Example sentence labels: `I_NEED_WATER`, `I_NEED_FOOD`

#### MLP internals (scikit-learn MLPClassifier)

- The trained model is a **feed-forward MLP** from scikit-learn (`MLPClassifier`).
- Training pipeline in `scripts/train_model.py`:
  1. `StandardScaler()` normalizes each input feature:
     - `x'_j = (x_j - mean_j) / std_j`
  2. `MLPClassifier(hidden_layer_sizes=(...), activation="relu", solver="adam", ...)`
- Network shape:
  - Input layer: **63** values (flattened hand landmarks)
  - Hidden layers: configured via `--hidden-layers` (the current mini model was trained with `128,64`)
  - Output layer: **K** neurons (`K = number of gesture classes`) with softmax-style probabilities exposed by `predict_proba`
- Forward pass (per layer):
  - `z^(l) = W^(l) a^(l-1) + b^(l)`
  - `a^(l) = ReLU(z^(l)) = max(0, z^(l))` for hidden layers
  - Final class scores are converted to probabilities; inference picks:
    - `y_hat = argmax(p)`
    - `confidence = max(p)`
- Optimization and regularization:
  - Optimizer: **Adam** (`solver="adam"`, `learning_rate_init=1e-3`, `batch_size=128`)
  - L2 weight regularization: `alpha=1e-4`
  - Early stopping enabled: `early_stopping=True`, `n_iter_no_change=30`, `max_iter` set by `--max-iter`
- Data split and evaluation:
  - Stratified holdout split (`train_test_split(..., stratify=y, test_size=0.2)`)
  - Report saved in `models/training_report.txt` via `classification_report`
- Temporal stability is handled outside the model in `app/buffer.py` using frame-window debounce (`stable_frames` + `cooldown_frames`), not by recurrent neural network memory.

### 5) Inference rate and stability filtering

- File: `app/main.py`
- By default, **MediaPipe + gesture classification** run at most once every `--infer-interval-sec` (3 s). The camera preview is **live** every frame; between samples you see the mirrored feed without new landmarks, while the HUD still shows the last gesture. When a frame is captured for inference, the **border turns green** (for `--sample-border-sec`) and that same frame is processed.
- File: `core/inference.py`
- The model’s **top-scoring** label is always used (no minimum-confidence filter).
- File: `app/buffer.py`
- Debounce/stability logic prevents repeated noisy commits:
  - Maintains rolling history of last `stable_frames`
  - Commits only if label is stable across the full window
  - Applies `cooldown_frames` after each commit
- Special control actions:
  - `SPACE`, `DELETE`, `CLEAR`, `SPEAK`

### 6) Sentence Buffer and Modes

- File: `app/buffer.py`
- `word` mode maps gesture labels to words/sentences.
- `char` mode appends first character of label.
- Buffer operations:
  - append token
  - append space
  - delete last character
  - clear full sentence

### 7) Text-to-Speech (Async, Non-blocking)

- File: `tts/engine.py`
- TTS runs in a dedicated worker thread with a queue.
- Main vision loop enqueues text with `speak_async(...)` and never waits on synthesis.
- Default backend:
  - `pyttsx3` (offline, lightweight)
- By default, startup fails fast if requested backend is unavailable.
- If `--allow-tts-fallback` is enabled, the engine will try your requested backend first, then fall back in this order:
  - `kokoro` -> `coqui` -> `pyttsx3` -> macOS `say`
- Runtime fallback:
  - If active backend fails while speaking, engine falls back to `macos-say`.
- Spoken output is logged to `data/spoken_log.txt`.

### 8) Real-Time Loop Integration

- File: `app/main.py`
- Each loop iteration:
  1. capture frame
  2. if `--infer-interval-sec` has elapsed: hand tracking + normalized features + classifier; run stability/debounce on the buffer; optional speech trigger
  3. otherwise: show the latest camera frame; keep showing the last prediction on the HUD
  4. render OpenCV overlays (gesture, confidence, FPS, mode, sentence)
- Keyboard control path:
  - `s`: speak current sentence
  - `t`: TTS test phrase

### 9) Why Latency Stays Low

- Lightweight 63-feature input instead of full image classification.
- MediaPipe tracking mode (`static_image_mode=False`).
- Inference can be throttled with `--infer-interval-sec` to cap CPU/GPU use; debounce still reduces accidental double-commits.
- TTS isolated from inference loop to avoid frame stalls.

## Training Notes

- This repo intentionally does not include training images or collected landmark CSVs.
- Use `scripts/collect_vocab_data.py` (webcam) to build your own `data/*.csv`, then train with `scripts/train_model.py`.
