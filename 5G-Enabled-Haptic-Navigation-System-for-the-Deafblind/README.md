#  5G-Enabled Haptic Navigation System for the Blind-Deaf

> **Distributed Spatial Intelligence and Haptic Feedback Framework**  
> A wearable assistive navigation system that restores independent mobility to deafblind individuals through tactile vibration — no vision, no hearing required.

---

##  Table of Contents

1. [Project Overview](#1-project-overview)
2. [The Problem We're Solving](#2-the-problem-were-solving)
3. [System Architecture](#3-system-architecture)
4. [How the Glove Works](#4-how-the-glove-works)
5. [Hardware — ESP32 Firmware (C++)](#5-hardware--esp32-firmware-c)
   - [FreeRTOS Dual-Core Design](#51-freertos-dual-core-design)
   - [Core 0: Input Decoding & State Machine](#52-core-0-input-decoding--state-machine)
   - [Core 1: Radio, GPS & WebSocket Engine](#53-core-1-radio-gps--websocket-engine)
   - [Kill Switch & Auto-Resume](#54-kill-switch--auto-resume)
6. [Server — Edge Navigation Engine (Python)](#6-server--edge-navigation-engine-python)
   - [Route Generation & 1-Meter Densification](#61-route-generation--1-meter-densification)
   - [Bearing Differential & Turn Detection](#62-bearing-differential--turn-detection)
   - [Telemetry Processing & GPS Noise Filtering](#63-telemetry-processing--gps-noise-filtering)
   - [WebSocket Handler & Instruction Dispatch](#64-websocket-handler--instruction-dispatch)
   - [Live Folium Map](#65-live-folium-map)
7. [5G Technology Pillars](#6-5g-technology-pillars)
8. [ESP32 Hardware Wiring Guide](#8-esp32-hardware-wiring-guide)
9. [Installation & Setup](#9-installation--setup)
   - [Server Dependencies (Python)](#91-server-dependencies-python)
   - [ESP32 Firmware Dependencies (Arduino/PlatformIO)](#92-esp32-firmware-dependencies-arduinoplatformio)
   - [Running the Server](#93-running-the-server)
   - [Flashing the ESP32](#94-flashing-the-esp32)
10. [Operational Guide — How to Use](#10-operational-guide--how-to-use)
11. [Societal & Industrial Impact](#11-societal--industrial-impact)

---

## 1. Project Overview

This project is a **thin-client haptic navigation wearable** designed specifically for individuals who are both blind and deaf (deafblind). Conventional navigation technology — GPS apps with voice guidance, visual maps, screen readers — provides zero utility to this demographic. Our system bypasses both vision and hearing entirely by encoding navigation instructions as **tactile vibration patterns delivered directly to the wrist**.

The core innovation is a **distributed intelligence architecture**: instead of cramming a heavy processor into a wrist-mounted wearable (which would make it too bulky, too hot, and too battery-hungry), we split the work across two specialized nodes:

- **The ESP32 wrist module** — a lightweight microcontroller that handles tactile input from a conductive glove, GPS telemetry, and haptic actuator output. It is the "thin client."
- **The Python Edge Server** — a 5G Multi-access Edge Computing (MEC) node that handles all the mathematically intensive work: fetching routes from Google Maps, densifying paths to 1-meter resolution, computing bearing differentials, and dispatching real-time turn instructions back to the wrist.

The two nodes communicate over a **persistent WebSocket connection** carried over a 5G cellular channel, targeting sub-30ms URLLC latency so that haptic triggers arrive at the user's wrist in real time — precisely 1 meter before each turn.

---

## 2. The Problem We're Solving

Modern navigation infrastructure is built entirely on two sensory channels: vision (maps, screens) and hearing (voice prompts). For the deafblind, both channels are simultaneously unavailable. This creates a total exclusion from smart city infrastructure, making independent outdoor travel extremely hazardous and cognitively exhausting — in most cases requiring a full-time human guide.

Existing assistive solutions for the blind (screen reader + voice navigation) still require functional hearing. Solutions for the deaf (visual maps) still require functional vision. No mature product addresses the intersection.

**Our system is designed from first principles for this gap.** The entire I/O pipeline — both input (destination entry) and output (navigation instructions) — is purely tactile. The user never needs to see a screen or hear a sound at any point in the journey.

**The hardware constraint we specifically solve:** running a precision pedestrian navigation engine locally on a wrist wearable is impractical. Path densification at 1-meter resolution, Haversine distance calculations across thousands of nodes, and real-time map-matching all require significant compute power. Doing this on an ESP32 is impossible; doing it on a smartphone-class chip requires a device too large, too hot, and too power-hungry to be a comfortable wristband. Our solution offloads all of this math to a 5G edge server, allowing the wearable to remain tiny and cool.

---

## 3. System Architecture(Simplified)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          USER INTERACTION LAYER                         │
│                                                                         │
│  [Conductive Glove]          [GPS Module]          [5G Radio]           │
│  dot · dash · action pins    NMEA sentences        WebSocket channel    │
└────────────────┬────────────────┬──────────────────────┬─────────────── ┘
                 │                │                      │
         ┌───────▼────────────────▼──────────────────────▼─────── ┐
         │              ESP32 — FreeRTOS Dual-Core                │
         │                                                        │
         │   ┌─── Core 0 (Input Processor) ────────────────── ┐   │
         │   │  Debounce (25ms)  │  6-bit decode              │   │
         │   │  5 buttons        │  dot/dash → char A-Z,0-9   │   │
         │   │                   │                            │   │
         │   │  State Machine: INPUT → REVIEW → NAV → PAUSED  │   │
         │   │  FreeRTOS Queue (outgoing commands)            │   │
         │   └─────────────────────|──────────────────────────┘   │
         │                         ▼                              │
         │   ┌─── Core 1 (Radio & GPS Sync) ───────────────── ┐   │
         │   │  GPS Reader (mutex-locked lat/lon cache)       │   │
         │   │  WS Manager: connect · ping · kill-switch 10s  │   │
         │   │  Telemetry Dispatcher: GPS every 5s            │   │
         │   │  Auto-Resume Engine: reconnect → replay dest   │   │
         │   └────────────────────────────────────────────────┘   │
         └───────────────────────────┬────────────────────────────┘
                                     │
                    5G WebSocket · URLLC · MEC · Network Slicing
                                     │
         ┌───────────────────────────▼────────────────────────────┐
         │           Python Edge Server — 5G MEC Node             │
         │                                                        │
         │   ┌─── WebSocket Handler ──────────────────────────┐   │
         │   │  asyncio + websockets                          │   │
         │   │  Parses: dest init, GPS telemetry, commands    │   │
         │   └────────────────────────────────────────────────┘   │
         │                                                        │
         │   ┌─── Route Generator ───┐  ┌─── Telemetry Proc ─┐    │
         │   │  Google Maps API      │  │  map-match (4m)    │    │
         │   │  1m path densification│  │  bearing diff >22° │    │
         │   └───────────────────────┘  └────────────────────┘    │
         │                                                        │
         │   ┌─── Action Points ─────┐  ┌─── Instruction Out ┐    │
         │   │  TURN_LEFT/RIGHT      │  │  KEEP STRAIGHT     │    │
         │   │  Triggered 1m before  │  │  ARRIVED / DRIFT   │    │
         │   └───────────────────────┘  └────────────────────┘    │
         │                                                        │
         │   Folium live map → live_nav_map.html (updates on GPS) │
         └────────────────────────────────────────────────────────┘
                                     │
                        ◀ haptic instruction → ESP32
```

---

## 4. How the Glove Works

The conductive glove is the **sole input interface** of the entire system. It replaces a touchscreen, keyboard, or voice command with a tactile binary encoding scheme that a deafblind user can operate entirely by touch.

### Physical Design

The glove is a standard conductive glove (any anti-static or conductive-fabric glove). Five specific contact points are mapped to five buttons wired into the ESP32. When a fingertip touches the thumb (which acts as the ground rail), it closes a circuit and registers as a button press.

| Contact Point | Button Pin (ESP32) | Function in INPUT mode | Function in NAVIGATION mode |
|---|---|---|---|
| Index finger | GPIO 33 | DOT (`.`) | Re-say last instruction (`resay`) |
| Middle finger | GPIO 32 | DASH (`-`) | Pause navigation (`pause`) |
| Ring finger | GPIO 27 | Delete last character | (hold 1.5s) Cancel session |
| Pinky finger | GPIO 14 | Clear frame buffer / backspace | — |
| Thumb-press (all) | GPIO 13 | Confirm / advance state | Trigger reroute |

> The thumb acts as the common ground. Each finger-to-thumb touch closes the circuit for that finger's button.

### Entering a Destination

The glove uses a **5-bit binary encoding** scheme (similar in spirit to Braille or Morse code) to let the user type any alphanumeric character using only two symbols: DOT (`.`) and DASH (`-`).

**Encoding table:**

| Value | Binary (dot=0, dash=1) | Character |
|---|---|---|
| 0 | `00000` | A |
| 1 | `00001` | B |
| ... | ... | ... |
| 25 | `11001` | Z |
| 26 | `11010` | SPACE |
| 27–36 | `11011`–`11111` + beyond | 0–9 |

The user taps the index finger for DOT and the middle finger for DASH. After exactly 5 taps, the frame buffer is full and the firmware automatically decodes it to a character, appends it to the destination string, and (via a haptic actuator, to be wired to the output pins) vibrates once to confirm. The user repeats this to spell out a full address.

**Example — typing "A":**
```
Index · Index · Index · Index · Index  →  .....  →  binary 00000  →  'A'
```

**Example — typing "B":**
```
Index · Index · Index · Index · Middle  →  ....-  →  binary 00001  →  'B'  
```

### The Decoding Algorithm (in code)

```cpp
// From tcp_version.cpp — Task_Core0_Processor
char decode5Bit(char* binaryCode) {
    int val = 0;
    for (int i = 0; i < 5; i++) {
        val <<= 1;                        // Shift existing bits left
        if (binaryCode[i] == '-') val |= 1; // Dash = 1, Dot = 0
    }
    if (val <= 25)  return (char)('A' + val);       // A-Z
    if (val == 26)  return ' ';                      // Space
    if (val >= 27 && val <= 36) return (char)('0' + (val - 27)); // 0-9
    return '?';
}
```

The frame buffer is a 6-element `char` array (`frameBuffer[6]`). Each dot or dash press appends `.` or `-` to the buffer and increments `fLen`. When `fLen == 5`, the decode fires automatically:

```cpp
if (currentState == MODE_INPUT && fLen == 5) {
    char decodedChar = decode5Bit(frameBuffer);
    if (dLen < 99) {
        destBuffer[dLen++] = decodedChar;
        destBuffer[dLen] = '\0';
    }
    fLen = 0; frameBuffer[0] = '\0'; // Reset frame for next character
}
```

### Navigation Mode Controls

Once navigation is active, the same five fingers switch to real-time command mode:

- **Index finger tap** → sends `{"cmd":"resay"}` → server replies with the last instruction repeated
- **Middle finger tap** → sends `{"cmd":"pause"}` → navigation freezes; tap again to resume
- **Delete finger (hold 1.5s)** → sends `{"cmd":"cancel"}` → terminates the session, returns to input mode
- **Thumb button tap** → sends `{"cmd":"reroute"}` → server recalculates route from current GPS position

---

## 5. Hardware — ESP32 Firmware (C++)

**File:** `user_module_code.cpp`

The firmware is written for the ESP32 using the Arduino framework on top of FreeRTOS. The ESP32's dual-core architecture is a central design choice — we use it to guarantee that the networking/GPS work on Core 1 never blocks the input scanning on Core 0, which must respond to button presses within milliseconds.

### 5.1 FreeRTOS Dual-Core Design

The ESP32 runs two tasks pinned to separate cores:

```cpp
// From setup()
xTaskCreatePinnedToCore(Task_Core0_Processor, "InputTask",  4096, NULL, 3, NULL, 0);
xTaskCreatePinnedToCore(Task_Core1_Radio,     "RadioTask",  8192, NULL, 2, NULL, 1);
```

- `Task_Core0_Processor` runs on **Core 0** with priority 3 (higher) — handles all button reading, state transitions, and character decoding.
- `Task_Core1_Radio` runs on **Core 1** with priority 2 — handles WiFi, WebSocket connection, GPS polling, and message dispatch.

**Why this matters:** If both tasks ran on the same core, a slow WiFi reconnection attempt (which can take seconds) could prevent button presses from being detected. By separating them, Core 0 is always free to scan buttons at its 10ms polling rate regardless of what the network is doing.

**Inter-task communication** is handled by two FreeRTOS primitives:

```cpp
QueueHandle_t   msgQueue;   // Core 0 → Core 1: outgoing WebSocket messages
SemaphoreHandle_t gpsMutex; // Core 1 internal: protects shared GPS coordinates
```

The queue holds `OutgoingMsg` structs:
```cpp
enum MsgType { MSG_INIT_REQ, MSG_CTRL_CMD };
struct OutgoingMsg {
    MsgType type;
    char payload[128];
};
```

When the user confirms a destination, Core 0 pushes an `MSG_INIT_REQ` into the queue. Core 1 pulls it out and builds the JSON payload with live GPS coordinates before sending it over WebSocket. This decoupling is critical: the GPS coordinates attached to the route request are snapshotted at the moment of transmission (from the mutex-protected shared variables), not at the moment the user pressed the button.

### 5.2 Core 0: Input Decoding & State Machine

**The State Machine** is the backbone of the user experience. The system operates in four states:

```cpp
enum State { MODE_INPUT, MODE_REVIEW, MODE_NAVIGATION, MODE_PAUSED };
volatile State currentState = MODE_INPUT;
```

State transitions:

```
MODE_INPUT ──[Action btn, dest non-empty]──▶ MODE_REVIEW
MODE_REVIEW ──[Action btn]──▶ MODE_NAVIGATION  (fires route request)
MODE_REVIEW ──[Delete btn]──▶ MODE_INPUT
MODE_NAVIGATION ──[Middle finger]──▶ MODE_PAUSED
MODE_PAUSED ──[Middle finger]──▶ MODE_NAVIGATION
MODE_NAVIGATION ──[Delete hold 1.5s]──▶ MODE_INPUT  (cancel)
```

**Hardware Debouncing** is implemented entirely in software with a 25ms filter per button. Physical buttons bounce (rapidly close/open) for up to 20ms when pressed, which would register as multiple presses without filtering:

```cpp
bool checkTap(Button &b, unsigned long &outDuration) {
    bool reading = digitalRead(b.pin);
    bool triggered = false;

    if (reading != b.lastReading) {
        b.lastChange = millis();   // Reset timer on any reading change
        b.lastReading = reading;
    }

    // Only accept a state as stable after 25ms of no change
    if ((millis() - b.lastChange) > 25) {
        if (reading != b.stableState) {
            b.stableState = reading;
            if (b.stableState == LOW) {       // Falling edge = press start
                b.pressedAt = millis();
            } else {                           // Rising edge = release
                outDuration = millis() - b.pressedAt; // Measure hold duration
                triggered = true;
            }
        }
    }
    return triggered;
}
```

The `outDuration` value enables **long-press detection** without any extra hardware — a 1.5-second hold of the delete button cancels navigation; a 1-second hold while in input mode wipes the entire destination buffer.

Core 0 runs in a tight polling loop with a 10ms delay:
```cpp
vTaskDelay(pdMS_TO_TICKS(10));
```
This gives the RTOS scheduler time to run other tasks (preventing CPU starvation) while still polling buttons 100 times per second — fast enough that no human press is ever missed.

### 5.3 Core 1: Radio, GPS & WebSocket Engine

Core 1 handles everything network and sensor related. It runs a perpetual loop that handles:

1. **WiFi reconnection** — if not connected, attempt to connect and retry every 2 seconds
2. **WebSocket polling** — calls `client.poll()` every loop iteration to process incoming server messages
3. **Heartbeat ping** — sends a WebSocket ping every 3 seconds to keep the connection alive and detect silent failures
4. **GPS ingestion** — reads raw NMEA sentences from the hardware serial port (GPS module on pins 16/17) and decodes them via TinyGPS++
5. **Queue consumption** — checks the FreeRTOS message queue for pending outgoing commands from Core 0
6. **Telemetry sync** — if navigation is active, sends current GPS coordinates to the server every 5 seconds

**GPS thread safety** is handled by a mutex around the shared `safeLat` / `safeLon` variables:

```cpp
// Core 1 — GPS writer (inside the GPS update block)
if (xSemaphoreTake(gpsMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
    safeLat = gps.location.lat();
    safeLon = gps.location.lng();
    xSemaphoreGive(gpsMutex);
}

// Core 1 — GPS reader (when building telemetry payload)
if (xSemaphoreTake(gpsMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
    cLat = safeLat; cLon = safeLon;
    xSemaphoreGive(gpsMutex);
}
```

**JSON message formats** sent to the server:

```json
// Route initialization (MSG_INIT_REQ)
{"dest": "Guwahati Railway Station", "lat": 26.186285, "lon": 91.698728}

// GPS telemetry (periodic, every 5s during navigation)
{"lat": 26.187100, "lon": 91.699200}

// Control command (MSG_CTRL_CMD)
{"cmd": "reroute"}
{"cmd": "resay"}
{"cmd": "pause"}
{"cmd": "resume"}
{"cmd": "cancel"}
```

**Indoor Hackathon GPS Override:** Since GPS satellites cannot be received indoors, the firmware includes a hardcoded coordinate fallback for demo environments:

```cpp
if (cLat == 0.0) {
    cLat = 26.18628507035049;
    cLon = 91.6987279359482;
    sysLog("GPS_WARN", "No satellite fix. Using SIMULATED coordinates.");
}
```

This allows the full system to be demonstrated indoors without a satellite fix.

### 5.4 Kill Switch & Auto-Resume

Two of the most important reliability features of the firmware are the **kill switch** and the **auto-resume** mechanism.

**The Kill Switch** solves a specific problem: WebSocket connections can appear open from the client side even when the server has died silently. The TCP connection remains half-open because no data has been exchanged to reveal the break. Without the kill switch, the device would appear to be connected and functioning while receiving no navigation data — potentially leaving a deafblind user stranded mid-route with no awareness of the failure.

```cpp
// Every loop iteration on Core 1
if (millis() - lastServerResponse > 10000) {
    sysLog("NETWORK", "FATAL: Server went silent. Forcing drop.");
    client.close(); // Force-close the socket, triggering ConnectionClosed event
}
```

`lastServerResponse` is updated on every server message, ping, or pong. If 10 seconds pass with no signal from the server, the socket is force-closed. This immediately triggers the `ConnectionClosed` event callback, which activates the auto-resume mechanism.

**Auto-Resume** is the graceful recovery mechanism:

```cpp
// In the ConnectionClosed event handler
if (navActive) {
    navActive = false;
    needsAutoResume = true;
    strncpy(recoveryBuffer, destBuffer, 100); // Save the destination
    sysLog("STATE", "Nav Suspended. Auto-resume armed.");
}
```

When the connection is re-established:

```cpp
// In the ConnectionOpened event handler
if (needsAutoResume) {
    // Re-send the saved destination with current GPS coordinates
    OutgoingMsg msg = {MSG_INIT_REQ};
    snprintf(msg.payload, 128, "%s", recoveryBuffer);
    xQueueSend(msgQueue, &msg, portMAX_DELAY);
    navActive = true;
    currentState = MODE_NAVIGATION;
    needsAutoResume = false;
}
```

The user never needs to re-enter their destination. The system silently saves the destination on disconnect and replays the route request the moment the connection is restored.

---

## 6. Server — Edge Navigation Engine (Python)

**File:** `server_side_code.py`

The server is a Python `asyncio` application built around the `websockets` library. It runs as a persistent async WebSocket server on port 8765 and is designed to run indefinitely — it catches its own exceptions and restarts itself automatically.

### 6.1 Route Generation & 1-Meter Densification

When the ESP32 sends a `dest` message, the server calls `nav.generate_route()`. This is the heaviest computational step in the entire system.

```python
res = gmaps.directions(start_pos, dest_pos, mode="walking")
steps = res[0]['legs'][0]['steps']
raw_pts = []
for s in steps:
    raw_pts.extend(polyline.decode(s['polyline']['points']))
```

The Google Maps Directions API returns a walking route as an encoded polyline. After decoding, the raw waypoints are typically 10–50 meters apart — far too sparse for precise pedestrian turn detection.

**Path Densification** interpolates new points between each raw waypoint at exactly 1-meter intervals using the Haversine formula:

```python
self.dense_path = [raw_pts[0]]
for i in range(len(raw_pts) - 1):
    d = self.haversine(raw_pts[i], raw_pts[i+1])
    if d < 1.0: continue
    steps_needed = int(d / 1.0)
    for j in range(1, steps_needed + 1):
        f = j / steps_needed
        new_lat = raw_pts[i][0] + (raw_pts[i+1][0] - raw_pts[i][0]) * f
        new_lon = raw_pts[i][1] + (raw_pts[i+1][1] - raw_pts[i][1]) * f
        self.dense_path.append((new_lat, new_lon))
```

For a 500-meter walking route, this generates approximately 500 densified nodes. This dense representation is what enables the system to detect when a user is precisely 1 meter away from a turn.

**The Haversine formula** accounts for the curvature of the Earth when computing distances between GPS coordinates:

```python
def haversine(self, p1, p2):
    R = 6371000  # Earth's radius in metres
    lat1, lon1, lat2, lon2 = map(math.radians, [p1[0], p1[1], p2[0], p2[1]])
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return R * 2 * math.asin(math.sqrt(a))
```

### 6.2 Bearing Differential & Turn Detection

After densification, the server scans the entire path to identify turns. This is done by computing the **bearing** (compass heading in degrees) of segments before and after each point, and measuring how sharply the direction changes:

```python
def get_bearing(self, p1, p2):
    lat1, lon1, lat2, lon2 = map(math.radians, [p1[0], p1[1], p2[0], p2[1]])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360
```

Turn detection logic:

```python
look = 8  # Look 8 nodes (8 metres) ahead and behind each candidate point
for i in range(look, len(self.dense_path) - look):
    b_in  = self.get_bearing(self.dense_path[i-look], self.dense_path[i])
    b_out = self.get_bearing(self.dense_path[i],      self.dense_path[i+look])
    diff  = (b_out - b_in + 180) % 360 - 180  # Normalize to [-180, +180]

    if abs(diff) > 22:  # 22-degree threshold separates turns from gentle curves
        if not self.action_points or \
           self.haversine(self.dense_path[i], self.action_points[-1]['coords']) > 15:
            
            warning_idx = max(0, i - 1)  # 1 meter BEFORE the actual turn
            warning_pt  = self.dense_path[warning_idx]

            self.action_points.append({
                'coords':         self.dense_path[i],  # The actual turn
                'warning_coords': warning_pt,           # Where the instruction fires
                'msg': "TURN_LEFT" if diff < 0 else "TURN_RIGHT",
                'done': False
            })
```

Key design decisions:
- **22-degree threshold:** below this, the path is considered a gentle curve that the user will follow naturally. Above this, an explicit turn instruction is needed.
- **15-meter deduplication:** prevents two turns within 15 meters of each other from both generating instructions (e.g., an S-bend would fire once, not twice).
- **1-meter pre-warning:** the instruction is sent when the user is at the node 1 meter *before* the actual turn apex — accounting for the ~0.5 seconds of human reaction time and haptic motor response time.

### 6.3 Telemetry Processing & GPS Noise Filtering

Every 5 seconds, the ESP32 sends its current GPS coordinates. The server processes this in `process_telemetry()`:

```python
def process_telemetry(self, current_lat, current_lon):
    user_pos = (current_lat, current_lon)

    # Check arrival
    dist_to_end = self.haversine(user_pos, self.dense_path[-1])
    if dist_to_end < 8: return "ARRIVED"

    # Check off-path (GPS drift or wrong turn)
    dists = [self.haversine(user_pos, p) for p in self.dense_path]
    min_deviation = min(dists)
    if min_deviation > 12: return "DRIFT: CHECK PATH"

    # Check action points (turns)
    for ap in self.action_points:
        if not ap['done'] and self.haversine(user_pos, ap['warning_coords']) < 4:
            ap['done'] = True
            return f"ACTION: {ap['msg']}"

    return "KEEP STRAIGHT"
```

**GPS Noise Filtering — The 4-Meter Catch Radius:**

Consumer GPS modules (especially those inside buildings or in urban canyons) have a positional accuracy of ±5–15 meters. A user walking at 1 m/s in a straight line will appear to "jump" by several meters between 5-second GPS updates. If the catch radius around a turn trigger were only 1 meter, the user's GPS position would frequently skip over it entirely.

The **4-meter catch radius** (`< 4` in the code above) ensures the turn instruction fires even if GPS places the user up to 4 meters off the exact warning node. This was empirically tuned to be small enough not to fire prematurely on nearby streets, but large enough to reliably catch the ~5-second GPS jump.

**Map-matching** is handled implicitly by the `min_deviation` check: the server constantly knows the shortest distance from the user's reported position to any point on the dense path. If this exceeds 12 meters, it's almost certainly not GPS noise — the user has physically deviated (taken a wrong turn or veered off-path) and a `DRIFT` warning is sent.

### 6.4 WebSocket Handler & Instruction Dispatch

The WebSocket handler is an `async` function that drives the entire server-side session:

```python
async def socket_handler(websocket):
    async for message in websocket:
        data = json.loads(message)

        if 'dest' in data:
            # Route initialization
            target = data['dest']
            if nav.generate_route((data['lat'], data['lon']), target):
                await websocket.send(f"STARTING NAV TO: {data['dest']}")
            else:
                await websocket.send("ERROR_NO_ROUTE")

        elif 'lat' in data:
            # GPS telemetry update
            instruction = nav.process_telemetry(data['lat'], data['lon'])
            if nav.is_active and not nav.is_paused:
                is_urgent = any(x in instruction for x in ["ACTION", "DRIFT", "ARRIVED", "WALK"])
                if is_urgent or (time.time() - nav.last_dispatch_time >= 15):
                    nav.last_dispatch_time = time.time()
                    await websocket.send(instruction)

        elif 'cmd' in data:
            # Control commands
            cmd = data['cmd']
            if   cmd == "reroute": nav.generate_route(...); await websocket.send("REROUTING COMPLETE")
            elif cmd == "resay":   await websocket.send(f"REPEAT: {nav.last_instruction}")
            elif cmd == "pause":   nav.is_paused = True;  await websocket.send("PAUSED")
            elif cmd == "resume":  nav.is_paused = False; await websocket.send("RESUMED")
            elif cmd == "cancel":  nav.is_active = False; await websocket.send("TERMINATED")
```

**Instruction throttling:** Non-urgent instructions (i.e., `KEEP STRAIGHT`) are throttled to a maximum of once every 15 seconds to avoid flooding the haptic motor with continuous vibrations. Urgent instructions (`ACTION`, `DRIFT`, `ARRIVED`, `WALK STRAIGHT TO START`) bypass the throttle and are sent immediately regardless of timing.

**Anti-kill mechanism:** The server blocks `SIGINT` (Ctrl+C) to prevent accidental shutdown while a deafblind user is mid-navigation:

```python
def ignore_interrupt(sig, frame):
    log("SYSTEM", "Interrupt caught and BLOCKED. Close the terminal window to force quit.")

signal.signal(signal.SIGINT, ignore_interrupt)
```

The server also auto-restarts itself after any crash:

```python
while True:
    try:
        async with websockets.serve(socket_handler, "0.0.0.0", 8765, ...):
            await asyncio.Future()  # Run forever
    except Exception as e:
        log("SYSTEM", f"Restarting server loop after error: {e}")
        await asyncio.sleep(2)
```

### 6.5 Live Folium Map

The server generates a live HTML map (`live_nav_map.html`) that updates every time a GPS telemetry ping is received. This is a debugging/monitoring tool for sighted operators:

- **Blue polyline** — the densified 1-meter resolution path
- **Red circles** — actual turn apex positions
- **Yellow circles** — the warning positions where the haptic instruction fires (1 metre before each turn)
- **Green user marker** — current reported GPS position

```python
def update_visual_map(self):
    m = folium.Map(location=[self.last_known_lat, self.last_known_lon], zoom_start=19)
    folium.PolyLine(self.dense_path, color="#2E86C1", weight=6).add_to(m)
    for ap in self.action_points:
        if not ap['done']:
            folium.CircleMarker(ap['coords'], color="red", ...).add_to(m)
            folium.CircleMarker(ap['warning_coords'], color="#F1C40F", ...).add_to(m)
    folium.Marker([self.last_known_lat, self.last_known_lon], ...).add_to(m)
    m.save(self.map_filename)
```

Open `live_nav_map.html` in any browser and refresh it to see the user's progress in real time.

---

## 7. 5G Technology Pillars

This system is specifically designed to exploit four structural features of 5G that are not available on 4G, Wi-Fi, or other wireless standards:

### URLLC — Ultra-Reliable Low-Latency Communication

Tactile navigation requires deterministic timing. If a "turn left" instruction arrives 300ms late, the user has already walked past the turn. 4G introduces non-deterministic jitter that can exceed 100ms under load; public Wi-Fi can exceed 500ms during congestion. 5G URLLC guarantees sub-30ms end-to-end latency for the WebSocket channel. At a walking pace of ~1 m/s, 30ms of latency means the instruction arrives while the user is still 0.97m from the turn — functionally instantaneous.

### MEC — Multi-access Edge Computing

Our Python navigation server runs on the 5G base station itself (the MEC node), not on a distant cloud server. This eliminates the "backhaul" leg of the network — the data never has to travel to a remote data center and back. The round-trip path is: wrist → base station → MEC server → base station → wrist. This is what makes the sub-30ms latency achievable in practice, not just in theory.

### Network Slicing for Mission-Critical Isolation

A public 5G tower is shared by hundreds of devices simultaneously streaming video, downloading files, browsing social media. During peak congestion, throughput for any one device can drop dramatically. Network slicing creates a **virtualized, isolated channel** carved out of the same physical infrastructure, with a guaranteed bandwidth reservation that is completely protected from consumer traffic. Our navigation WebSocket stream runs in this isolated slice, ensuring it is never starved for bandwidth even during peak hours.

### eMBB — Enhanced Mobile Broadband (Future Roadmap)

The current system sends only small JSON packets (GPS coordinates, text instructions). The eMBB layer is reserved for the next development phase: streaming a live camera feed from the user's wearable to the edge server for real-time obstacle detection via computer vision. The eMBB uplink capacity (multiple Gbps) is the only wireless standard capable of supporting high-definition video streaming at this scale from a wearable device.

---

## 8. ESP32 Hardware Wiring Guide

### Components Required

| Component | Specification |
|---|---|
| Microcontroller | ESP32 DevKit v1 (or any ESP32 with dual-core) |
| GPS Module | NEO-6M or NEO-8M (UART, 9600 baud) |
| Conductive Glove | Any anti-static / conductive fabric glove |
| Haptic Motor | Coin vibration motors (one per instruction type, or one with PWM control) |
| Power | LiPo 3.7V battery or USB |

### Pin Connections

```
ESP32 GPIO    →    Component
─────────────────────────────────────────────
GPIO 33       →    Index finger button (DOT / resay)
GPIO 32       →    Middle finger button (DASH / pause)
GPIO 27       →    Ring finger button (Delete)
GPIO 14       →    Pinky button (Clear)
GPIO 13       →    Action button / Thumb button
GND           →    All button common ground (glove thumb rail)

GPIO 16 (RX2) →    GPS module TX
GPIO 17 (TX2) →    GPS module RX
GND           →    GPS module GND
3.3V          →    GPS module VCC

[Your output GPIO]  →  Haptic motor driver input
GND                 →  Haptic motor driver GND
```

> **Note:** All glove buttons use `INPUT_PULLUP` mode. The default state is `HIGH` (finger off thumb). When finger touches thumb and closes the circuit to GND, the pin reads `LOW` (button pressed). This means you do **not** need external pull-up resistors.

```cpp
// From setup() in tcp_version.cpp
pinMode(BTN_DOT_PIN,    INPUT_PULLUP);
pinMode(BTN_DASH_PIN,   INPUT_PULLUP);
pinMode(BTN_DELETE_PIN, INPUT_PULLUP);
pinMode(BTN_CLEAR_PIN,  INPUT_PULLUP);
pinMode(BTN_ACTION_PIN, INPUT_PULLUP);
```

---

## 9. Installation & Setup

### 9.1 Server Dependencies (Python)

**Requires:** Python 3.9+

```bash
pip install websockets googlemaps polyline folium
```

| Library | Purpose |
|---|---|
| `websockets` | Async WebSocket server (asyncio-native) |
| `googlemaps` | Google Maps Directions API client |
| `polyline` | Decodes Google's encoded polyline route format |
| `folium` | Generates the live HTML map |
| `asyncio` | Built-in Python async runtime |
| `math` | Haversine and bearing calculations |
| `signal` | SIGINT blocking (anti-kill) |
| `socket` | Auto-detects server's local IP address |

**Google Maps API Key:**

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Enable the **Directions API**
3. Create an API key
4. Paste it into `websockets_version.py` line 12:
```python
GOOGLE_KEY = "YOUR_API_KEY_HERE"
```

### 9.2 ESP32 Firmware Dependencies (Arduino/PlatformIO)

Install these libraries via Arduino Library Manager or `platformio.ini`:

| Library | Install Name | Purpose |
|---|---|---|
| `ArduinoWebsockets` | `ArduinoWebsockets` | WebSocket client for ESP32 |
| `TinyGPS++` | `TinyGPSPlus` | NMEA sentence parsing from GPS module |
| `WiFi` | Built-in (ESP32 Arduino core) | WiFi connectivity |
| `Arduino.h` | Built-in | FreeRTOS, GPIO, Serial |

**Board:** ESP32 Dev Module  
**Partition scheme:** Default (or "No OTA" for more program space)  
**Upload speed:** 921600

**`platformio.ini` (if using PlatformIO):**
```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
lib_deps =
    arkhipenko/TaskScheduler
    mikalhart/TinyGPSPlus
    gilmaimon/ArduinoWebsockets
```

### 9.3 Running the Server

1. Connect your computer to the same 5G/WiFi network as the ESP32 router
2. Find your machine's local IP:
   - macOS/Linux: `ifconfig` → look for `en0` or `wlan0`
   - Windows: `ipconfig` → look for IPv4 Address
3. Run the server:
```bash
python websockets_version.py
```

The server will print its detected IP on startup:
```
[12:34:56.789] [    SYSTEM    ] UPDATE ESP32 'ws_server_ip' TO: 192.168.x.x
```

4. Copy this IP address into the ESP32 firmware before flashing.

### 9.4 Flashing the ESP32

1. Open `tcp_version.cpp` in Arduino IDE or PlatformIO
2. Update WiFi credentials:
```cpp
const char* ssid     = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
```
3. Update the server IP (from step 9.3 above):
```cpp
const char* ws_server_ip = "192.168.x.x";  // ← Your server's IP
```
4. (Optional for indoor/demo use) Update the simulated GPS coordinates to your actual indoor location:
```cpp
cLat = 26.18628507035049;
cLon = 91.6987279359482;
```
5. Select the correct board and port, then upload
6. Open the Serial Monitor at **115200 baud** to see the full diagnostic log

---

## 10. Operational Guide — How to Use

### Step 1 — Boot
Power on the ESP32. Core 1 will connect to WiFi and then establish the WebSocket tunnel to the server. Watch the Serial Monitor for:
```
[NETWORK] Tunnel Verified OPEN.
```

### Step 2 — Enter Destination (INPUT mode)
Using the glove, tap the **index finger** (DOT) and **middle finger** (DASH) to spell your destination address in 5-bit code. Each completed 5-tap sequence is decoded to one character. Use **ring finger** to backspace, **pinky** to clear the current 5-tap frame.

Example — to type "PARK":
```
P = 01111  →  . - - - -
A = 00000  →  . . . . .
R = 10001  →  - . . . -
K = 01010  →  . - . - .
```

### Step 3 — Review (REVIEW mode)
Tap the **action/thumb button** once. You enter REVIEW mode. At this point a future implementation can deliver a haptic replay of the typed destination. Tap **delete** to go back and correct.

### Step 4 — Start Navigation (NAVIGATION mode)
Tap the **action/thumb button** again. The ESP32 sends your destination and current GPS to the server. The server fetches the route, densifies it, and replies: `STARTING NAV TO: [destination]`. Navigation is now active.

### Step 5 — Walk
- **Haptic pulse pattern for `KEEP STRAIGHT`:** [define your motor pattern]
- **Haptic pulse pattern for `ACTION: TURN_LEFT`:** [define your motor pattern]
- **Haptic pulse pattern for `ACTION: TURN_RIGHT`:** [define your motor pattern]
- **Haptic pulse pattern for `ARRIVED`:** [define your motor pattern]

### Step 6 — In-Navigation Controls
| Glove gesture | Action |
|---|---|
| Index finger tap | Repeat last instruction (`resay`) |
| Middle finger tap | Toggle pause/resume |
| Thumb button tap | Request reroute from current position |
| Delete button hold (1.5s) | Cancel session, return to INPUT mode |

### Step 7 — Arrival
The server sends `ARRIVED` when you are within 8 meters of the destination. The session ends automatically.

---

## 11. Societal & Industrial Impact

### Societal Impact

For the deafblind demographic, autonomy in public space is frequently described as a "forgotten concept." Current smart city infrastructure — navigation apps, public transit displays, wayfinding signage — is built entirely on visual and auditory channels. Our system is a direct intervention at the exclusion point.

By providing reliable, private, and discreet navigation through a subtle wrist wearable, we restore the ability to access education, employment, healthcare, and public spaces without requiring a full-time human guide. The system is intentionally unobtrusive — to a bystander, the user simply appears to be wearing a glove.

### Industrial & Emergency Services Impact

The same architecture — a thin-client haptic wearable guided by a 5G edge navigation server — has direct applications in zero-visibility professional environments:

- **Firefighters** navigating smoke-filled buildings where visibility is zero and radio communication may be limited
- **Miners** in underground tunnels with no GPS signal (using local UWB beacons instead of GPS as the positional source)
- **Military personnel** requiring silent, covert navigation without visible screens or audible instructions
- **Warehouse and logistics workers** in high-noise environments where audio instructions are inaudible

In all these cases, the modularity of our architecture means only the positional data source (GPS → UWB beacons → pre-mapped building blueprints) needs to change. The routing engine, WebSocket protocol, and haptic feedback system remain identical.

---

## License

This project is licensed under the **GNU General Public License v3.0** — see the [LICENSE](LICENSE) file for details.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

> In short: you are free to use, modify, and distribute this project, but any derivative work must also be open-sourced under the same GPL v3 license.

## 🎬 Demo

[![Watch the demo](https://img.shields.io/badge/Watch-Demo%20Video-red?style=for-the-badge&logo=googledrive)](https://drive.google.com/drive/folders/1ng-BPUKp2r5qMjSuTW8unrUdH3J2a17x?usp=sharing)
---

##  Authors & Team
>  April 2026 · IIT Guwahati

| Role | Name |
|------|------|
|  Faculty Advisor | Prof. Dr. Salil Kashyap |
|  Teaching Assistant | Aditya Gupta |
|  Student | Emani Sri Ajay Karthik |
|  Student | G Mani Shankar |

---

*When maps fail, feel the way.*
