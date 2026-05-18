#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <TinyGPS++.h>

// =====================================================
// 1. DATA STRUCTURES & QUEUES
// =====================================================
enum MsgType { MSG_INIT_REQ, MSG_CTRL_CMD };
struct OutgoingMsg {
    MsgType type;
    char payload[128];
};

QueueHandle_t msgQueue; 
static uint32_t heartbeatCount = 0;

// =====================================================
// 2. CONFIGURATION & PINS
// =====================================================
const char* ssid = "eemani's"; 
const char* password = "87654321";
const char* mqtt_server = "0690d86c6cd945d4a0fe5834c0333c74.s1.eu.hivemq.cloud";
const int mqtt_port = 8883;
const char* mqtt_user = "iitg_user";
const char* mqtt_pass = "12345678aA";

const char* TOPIC_INIT    = "deafblind/user/request";
const char* TOPIC_GPS     = "deafblind/user/gps";
const char* TOPIC_CONTROL = "deafblind/user/control";
const char* TOPIC_INSTR   = "deafblind/server/instruction";

#define BTN_DOT_PIN     33
#define BTN_DASH_PIN    32
#define BTN_DELETE_PIN  27
#define BTN_CLEAR_PIN   14
#define BTN_ACTION_PIN  13 

struct Button {
  uint8_t pin;
  bool stableState;
  bool lastReading;
  unsigned long lastChange;
  unsigned long pressedAt;
  Button(uint8_t p) : pin(p), stableState(HIGH), lastReading(HIGH), lastChange(0), pressedAt(0) {}
};

Button btnDot(BTN_DOT_PIN);
Button btnDash(BTN_DASH_PIN);
Button btnDelete(BTN_DELETE_PIN);
Button btnClear(BTN_CLEAR_PIN);
Button btnAction(BTN_ACTION_PIN);

// =====================================================
// 3. GLOBAL STATE (Thread-Safe/Volatile)
// =====================================================
enum State { MODE_INPUT, MODE_REVIEW, MODE_NAVIGATION, MODE_PAUSED };
volatile State currentState = MODE_INPUT;
volatile bool navigationStarted = false; 

char destination[100] = "";
char frame[6] = ""; 
int frameLen = 0, destLen = 0;
unsigned long lastGPSUpdate = 0;
double currentLat = 0, currentLon = 0;
bool gpsValid = false;

TinyGPSPlus gps;
HardwareSerial gpsSerial(2);
WiFiClientSecure espClient;
PubSubClient client(espClient);

// =====================================================
// 4. CORE 0: TACTILE INPUT & DECODING
// =====================================================
char decode5BitFrame(char* code) {
    int val = 0;
    for (int i = 0; i < 5; i++) {
        val <<= 1;
        if (code[i] == '-') val |= 1;
    }
    if (val >= 0 && val <= 25) return (char)('A' + val); 
    if (val == 26) return ' '; 
    if (val >= 27 && val <= 36) return (char)('0' + (val - 27)); 
    return '?';
}

void addBitToBuffer(char b) {
    if (frameLen < 5) {
        frame[frameLen++] = b;
        frame[frameLen] = '\0';
    }
    if (frameLen == 5) {
        char c = decode5BitFrame(frame);
        if (destLen < 99) {
            destination[destLen++] = c;
            destination[destLen] = '\0';
            Serial.printf("[INPUT] Added: %c | Buffer: %s\n", c, destination);
        }
        frameLen = 0; frame[0] = '\0';
    }
}

void handleButtonPress(Button &b, int id) {
    bool reading = digitalRead(b.pin);
    if (reading != b.lastReading) {
        b.lastChange = millis();
        b.lastReading = reading;
    }
    if ((millis() - b.lastChange) > 25 && reading != b.stableState) {
        b.stableState = reading;
        if (b.stableState == LOW) {
            b.pressedAt = millis();
        } else {
            unsigned long duration = millis() - b.pressedAt;

            if (currentState == MODE_INPUT) {
                if (id == 0) addBitToBuffer('.');
                if (id == 1) addBitToBuffer('-');
                if (id == 2 && duration > 1000) { 
                    destLen = 0; frameLen = 0; destination[0] = '\0';
                    Serial.println("[INPUT] Memory Cleared.");
                }
                if (id == 4 && destLen > 0) {
                    currentState = MODE_REVIEW;
                    Serial.println("[STATE] REVIEW MODE.");
                }
            } 
            else if (currentState == MODE_REVIEW) {
                if (id == 4) { 
                    OutgoingMsg msg; msg.type = MSG_INIT_REQ; 
                    snprintf(msg.payload, sizeof(msg.payload), "%s", destination);
                    xQueueSend(msgQueue, &msg, 0); 
                    navigationStarted = true;
                    currentState = MODE_NAVIGATION;
                    Serial.println("[STATE] STARTING NAVIGATION.");
                }
                if (id == 2) currentState = MODE_INPUT;
            }
            else if (currentState == MODE_NAVIGATION) {
                if (id == 0) { // Dot: REPEAT
                    OutgoingMsg m; m.type = MSG_CTRL_CMD; strcpy(m.payload, "resay");
                    xQueueSend(msgQueue, &m, 0);
                    Serial.println("[CONTROL] Requesting REPEAT.");
                }
                if (id == 1) { // Dash: PAUSE
                    currentState = MODE_PAUSED;
                    OutgoingMsg m; m.type = MSG_CTRL_CMD; strcpy(m.payload, "pause");
                    xQueueSend(msgQueue, &m, 0);
                    Serial.println("[CONTROL] Paused.");
                }
                if (id == 4) { // Action: REROUTE
                    OutgoingMsg m; m.type = MSG_CTRL_CMD; strcpy(m.payload, "reroute");
                    xQueueSend(msgQueue, &m, 0);
                    Serial.println("[CONTROL] Requesting REROUTE.");
                }
                if (id == 2 && duration > 1500) { // Cancel
                    navigationStarted = false;
                    currentState = MODE_INPUT;
                    destLen = 0; destination[0] = '\0';
                    OutgoingMsg m; m.type = MSG_CTRL_CMD; strcpy(m.payload, "cancel");
                    xQueueSend(msgQueue, &m, 0);
                    Serial.println("[CONTROL] Session Cancelled.");
                }
            }
            else if (currentState == MODE_PAUSED) {
                if (id == 1) {
                    currentState = MODE_NAVIGATION;
                    OutgoingMsg m; m.type = MSG_CTRL_CMD; strcpy(m.payload, "resume");
                    xQueueSend(msgQueue, &m, 0);
                    Serial.println("[CONTROL] Resumed.");
                }
            }
        }
    }
}

void InputTask(void *pv) {
    pinMode(BTN_DOT_PIN, INPUT_PULLUP);
    pinMode(BTN_DASH_PIN, INPUT_PULLUP);
    pinMode(BTN_DELETE_PIN, INPUT_PULLUP);
    pinMode(BTN_CLEAR_PIN, INPUT_PULLUP);
    pinMode(BTN_ACTION_PIN, INPUT_PULLUP);
    for (;;) {
        handleButtonPress(btnDot, 0); handleButtonPress(btnDash, 1);
        handleButtonPress(btnDelete, 2); handleButtonPress(btnClear, 3);
        handleButtonPress(btnAction, 4);
        vTaskDelay(pdMS_TO_TICKS(10)); 
    }
}

// =====================================================
// 5. CORE 1: RADIO & GPS
// =====================================================
void mqttCallback(char* topic, uint8_t* payload, unsigned int length) {
    String msg = "";
    for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
    Serial.printf("\n>>> [SERVER]: %s\n", msg.c_str());
    if (msg.indexOf("ARRIVED") >= 0 || msg.indexOf("TERMINATED") >= 0) {
        navigationStarted = false;
        currentState = MODE_INPUT;
    }
}

void tryReconnect() {
    static unsigned long lastAttempt = 0;
    if (!client.connected() && millis() - lastAttempt > 5000) {
        lastAttempt = millis();
        String clientId = "ESP32_User_" + String(esp_random() % 0xffff, HEX);
        if (client.connect(clientId.c_str(), mqtt_user, mqtt_pass)) {
            client.subscribe(TOPIC_INSTR);
            Serial.println("[MQTT] Link Established.");
        }
    }
}

void CommTask(void *pv) {
    gpsSerial.begin(9600, SERIAL_8N1, 16, 17);
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) vTaskDelay(pdMS_TO_TICKS(500));
    espClient.setInsecure();
    client.setServer(mqtt_server, mqtt_port);
    client.setCallback(mqttCallback);
    OutgoingMsg qMsg;

    for (;;) {
        tryReconnect();
        client.loop(); 
        while (gpsSerial.available()) gps.encode(gpsSerial.read());
        if (gps.location.isUpdated()) {
            currentLat = gps.location.lat();
            currentLon = gps.location.lng();
            gpsValid = gps.location.isValid();
        }
        if (xQueueReceive(msgQueue, &qMsg, 0) == pdTRUE) {
            if (qMsg.type == MSG_INIT_REQ) {
                String p = "{\"dest\":\"" + String(qMsg.payload) + "\",\"lat\":" + String(currentLat, 6) + ",\"lon\":" + String(currentLon, 6) + "}";
                client.publish(TOPIC_INIT, p.c_str());
            } else if (qMsg.type == MSG_CTRL_CMD) {
                String p = "{\"cmd\":\"" + String(qMsg.payload) + "\"}";
                client.publish(TOPIC_CONTROL, p.c_str());
            }
        }
        if (navigationStarted && client.connected() && (millis() - lastGPSUpdate > 5000)) {
            lastGPSUpdate = millis();
            String p = "{\"lat\":" + String(currentLat, 6) + ",\"lon\":" + String(currentLon, 6) + "}";
            client.publish(TOPIC_GPS, p.c_str());
        }
        vTaskDelay(pdMS_TO_TICKS(15));
    }
}

void setup() {
    Serial.begin(115200);
    msgQueue = xQueueCreate(10, sizeof(OutgoingMsg));
    xTaskCreatePinnedToCore(InputTask, "Input", 4096, NULL, 3, NULL, 0);
    xTaskCreatePinnedToCore(CommTask, "Comm", 8192, NULL, 2, NULL, 1);
}

void loop() { vTaskDelete(NULL); }
