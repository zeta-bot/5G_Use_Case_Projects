# Alternative Implementations

This folder contains additional and experimental implementations developed during the design and testing phase of the 5G-Enabled Haptic Navigation System for the Blind-Deaf.

These files were used to:
- test alternative communication protocols
- benchmark latency
- evaluate synchronization performance
- compare MQTT and WebSocket architectures
- test ESP32 networking behavior

---

# Files Included

## `server_mqtt_code.py`
MQTT-based Python server implementation used for communication testing and telemetry handling.

---

## `user_mqtt_code.cpp`
ESP32 MQTT client firmware used to test publish/subscribe communication with the server.

---

## `websockets_latency.py`
Python latency testing server used to measure WebSocket communication delay and response timing.

---

## `websockets_latency_test.cpp`
ESP32 latency benchmarking firmware used for round-trip timing and synchronization tests.

---

# Purpose

These implementations were created to compare:
- MQTT vs WebSockets
- communication latency
- telemetry synchronization
- networking reliability
- real-time responsiveness

The final system architecture selected WebSockets for the main implementation due to better real-time bidirectional communication performance.

---

# Main Project Files

Primary project implementation:
- `server_end_code.py`
- `user_module_code.cpp`

located in the root repository directory.

---
