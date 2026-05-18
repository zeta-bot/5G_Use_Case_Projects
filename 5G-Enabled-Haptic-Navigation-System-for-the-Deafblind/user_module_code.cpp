#include <Arduino.h>
#include <WiFi.h>
#include <TinyGPS++.h>
#include <ArduinoWebsockets.h>

using namespace websockets;

// 1. DATA STRUCTURES & THREAD SAFETY

enum MsgType { MSG_INIT_REQ, MSG_CTRL_CMD };
struct OutgoingMsg {
    MsgType type;
    char payload[128];
};

QueueHandle_t msgQueue;    
SemaphoreHandle_t gpsMutex; 

void sysLog(String tag, String msg) {
    Serial.printf("[%08lu] [C%d] [%-12s] %s\n", millis(), xPortGetCoreID(), tag.c_str(), msg.c_str());
}

// 2. HARDWARE PINS & BUTTON STRUCT (POLLING ENGINE)

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

// 25ms Hardware Debounce Filter
bool checkTap(Button &b, unsigned long &outDuration) {
    bool reading = digitalRead(b.pin);
    bool triggered = false;

    if (reading != b.lastReading) {
        b.lastChange = millis();
        b.lastReading = reading;
    }

    if ((millis() - b.lastChange) > 25) {
        if (reading != b.stableState) {
            b.stableState = reading;
            if (b.stableState == LOW) { 
                b.pressedAt = millis();
            } else { 
                outDuration = millis() - b.pressedAt;
                triggered = true;
            }
        }
    }
    return triggered;
}

// 3. GLOBAL STATE

enum State { MODE_INPUT, MODE_REVIEW, MODE_NAVIGATION, MODE_PAUSED };
volatile State currentState = MODE_INPUT;
volatile bool navActive = false;
volatile bool isConnected = false; 
volatile bool needsAutoResume = false; 

// NEW: Track exactly when we last heard from the server for the Kill Switch
volatile unsigned long lastServerResponse = 0; 

char destBuffer[100] = ""; 
char frameBuffer[6] = "";
char recoveryBuffer[100] = ""; 
int fLen = 0, dLen = 0;

TinyGPSPlus gps;
HardwareSerial gpsSerial(2);
WebsocketsClient client;

double safeLat = 0.0, safeLon = 0.0;
unsigned long lastTelemetrySync = 0;

// 4. CORE 0: STATE MACHINE & LOGIC

char decode5Bit(char* binaryCode) {
    int val = 0;
    for (int i = 0; i < 5; i++) { 
        val <<= 1; 
        if (binaryCode[i] == '-') val |= 1; 
    }
    if (val <= 25) return (char)('A' + val);
    if (val == 26) return ' ';
    if (val >= 27 && val <= 36) return (char)('0' + (val - 27));
    return '?';
}

void Task_Core0_Processor(void *pvParameters) {
    sysLog("BOOT", "Core 0 Polling Processor Online.");

    for (;;) {
        unsigned long duration;

        if (checkTap(btnDot, duration)) {
            if (currentState == MODE_INPUT) {
                if (fLen < 5) { frameBuffer[fLen++] = '.'; frameBuffer[fLen] = '\0'; }
            } else if (currentState == MODE_NAVIGATION) {
                OutgoingMsg m = {MSG_CTRL_CMD, "resay"}; xQueueSend(msgQueue, &m, 0);
            }
        }

        if (checkTap(btnDash, duration)) {
            if (currentState == MODE_INPUT) {
                if (fLen < 5) { frameBuffer[fLen++] = '-'; frameBuffer[fLen] = '\0'; }
            } else if (currentState == MODE_NAVIGATION) {
                currentState = MODE_PAUSED; 
                OutgoingMsg m = {MSG_CTRL_CMD, "pause"}; xQueueSend(msgQueue, &m, 0);
            } else if (currentState == MODE_PAUSED) {
                currentState = MODE_NAVIGATION; 
                OutgoingMsg m = {MSG_CTRL_CMD, "resume"}; xQueueSend(msgQueue, &m, 0);
            }
        }

        if (checkTap(btnClear, duration)) {
            if (currentState == MODE_INPUT) {
                if (fLen > 0) { 
                    fLen = 0; frameBuffer[0] = '\0';
                } else if (dLen > 0) { 
                    destBuffer[--dLen] = '\0';
                }
            }
        }

        if (checkTap(btnDelete, duration)) {
            if (currentState == MODE_INPUT && duration > 1000) {
                dLen = 0; destBuffer[0] = '\0'; fLen = 0; frameBuffer[0] = '\0';
                sysLog("SYS_CMD", "Input Memory Wiped.");
            }
            else if (currentState == MODE_REVIEW) {
                currentState = MODE_INPUT;
            }
            else if ((currentState == MODE_NAVIGATION || needsAutoResume) && duration > 1500) {
                navActive = false; 
                needsAutoResume = false;
                currentState = MODE_INPUT; 
                dLen = 0; destBuffer[0] = '\0';
                OutgoingMsg m = {MSG_CTRL_CMD, "cancel"}; xQueueSend(msgQueue, &m, 0);
                sysLog("SYS_CMD", "Session Terminated by User.");
            }
        }

        if (checkTap(btnAction, duration)) {
            if (currentState == MODE_INPUT && dLen > 0) {
                currentState = MODE_REVIEW;
                sysLog("STATE", "MODE: REVIEW.");
            }
            else if (currentState == MODE_REVIEW) {
                OutgoingMsg msg = {MSG_INIT_REQ};
                snprintf(msg.payload, 128, "%s", destBuffer);
                xQueueSend(msgQueue, &msg, portMAX_DELAY);
                
                navActive = true; 
                currentState = MODE_NAVIGATION;
                sysLog("STATE", "MODE: NAVIGATION ACTIVE.");
            }
            else if (currentState == MODE_NAVIGATION) {
                OutgoingMsg m = {MSG_CTRL_CMD, "reroute"}; xQueueSend(msgQueue, &m, 0);
            }
        }

        if (currentState == MODE_INPUT && fLen == 5) {
            char decodedChar = decode5Bit(frameBuffer);
            if (dLen < 99) {
                destBuffer[dLen++] = decodedChar;
                destBuffer[dLen] = '\0';
                sysLog("INPUT", "Buffer: [" + String(destBuffer) + "]");
            }
            fLen = 0; frameBuffer[0] = '\0';
        }

        vTaskDelay(pdMS_TO_TICKS(10)); 
    }
}

// 5. CORE 1: RADIO & GPS EDGE SYNC

const char* ssid = "RUT_BEF3_2G"; 
const char* password = "Admin@123";
const char* ws_server_ip = "192.168.116.30"; 
const uint16_t ws_server_port = 8765;

void onWebsocketEvent(WebsocketsEvent event, String data) {
    if (event == WebsocketsEvent::ConnectionOpened) {
        isConnected = true;
        lastServerResponse = millis(); // NEW: Start the clock
        sysLog("NETWORK", "Tunnel Verified OPEN.");
        
        if (needsAutoResume) {
            sysLog("STATE", "Connection Restored. Auto-resuming navigation...");
            
            OutgoingMsg msg = {MSG_INIT_REQ};
            snprintf(msg.payload, 128, "%s", recoveryBuffer);
            xQueueSend(msgQueue, &msg, portMAX_DELAY);
            
            navActive = true;
            currentState = MODE_NAVIGATION;
            needsAutoResume = false;
        }
    } else if (event == WebsocketsEvent::ConnectionClosed) {
        isConnected = false;
        sysLog("NETWORK", "SIGNAL LOST.");
        
        if (navActive) {
            navActive = false; 
            needsAutoResume = true;
            
            strncpy(recoveryBuffer, destBuffer, 100); 
            sysLog("STATE", "Nav Suspended. Session killed. Auto-resume armed.");
            sysLog("HAPTIC_WARN", "Triggering SOS Pulses (Connection Lost Warning)");
        }
    } 
    // NEW: Reset heartbeat timer on ping/pong
    else if (event == WebsocketsEvent::GotPing || event == WebsocketsEvent::GotPong) {
        lastServerResponse = millis(); 
    }
}

void onWebsocketMessage(WebsocketsMessage msg) {
    lastServerResponse = millis(); 
    sysLog("RX_SERVER", "Data: " + msg.data());
    
    // NEW: Added the ERROR catch
    if (msg.data().indexOf("ARRIVED") >= 0 || 
        msg.data().indexOf("TERMINATED") >= 0 || 
        msg.data().indexOf("ERROR") >= 0) {
        
        navActive = false; 
        currentState = MODE_INPUT; // Drops user back to start
        dLen = 0; destBuffer[0] = '\0';
        
        sysLog("STATE", "Nav Cancelled/Failed. Reverted to INPUT mode.");
        
        // Optional but highly recommended: 
        // Trigger a specific "Error" vibration here so the blind user 
        // physically knows they need to type the destination again.
    }
}

void Task_Core1_Radio(void *pvParameters) {
    gpsSerial.begin(9600, SERIAL_8N1, 16, 17);
    WiFi.begin(ssid, password);
    
    while (WiFi.status() != WL_CONNECTED) {
        vTaskDelay(pdMS_TO_TICKS(500));
    }
    sysLog("WIFI", "Linked. Local IP: " + WiFi.localIP().toString());

    client.onEvent(onWebsocketEvent);
    client.onMessage(onWebsocketMessage);
    
    OutgoingMsg packet;
    unsigned long lastPingTime = 0; 

    for (;;) {
        if (!isConnected && WiFi.status() == WL_CONNECTED) {
            if (client.connect(ws_server_ip, ws_server_port, "/")) {
                vTaskDelay(pdMS_TO_TICKS(500)); 
            } else {
                vTaskDelay(pdMS_TO_TICKS(2000)); 
            }
        }
        
        if (isConnected) {
            client.poll(); 
            
            if (millis() - lastPingTime > 3000) {
                lastPingTime = millis();
                client.ping(); 
            }

            // === NEW: THE KILL SWITCH ===
            // If 10 seconds pass without a Ping, Pong, or Message, shatter the socket
            if (millis() - lastServerResponse > 10000) {
                sysLog("NETWORK", "FATAL: Server went silent. Forcing drop.");
                client.close(); 
            }
            // ============================
        }

        while (gpsSerial.available()) { 
            gps.encode(gpsSerial.read()); 
        }
        
        if (gps.location.isUpdated()) { 
            if (xSemaphoreTake(gpsMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                safeLat = gps.location.lat(); 
                safeLon = gps.location.lng(); 
                xSemaphoreGive(gpsMutex);
            }
        }

        if (isConnected && xQueueReceive(msgQueue, &packet, 0) == pdTRUE) {
            String jsonPayload;
            if (packet.type == MSG_INIT_REQ) {
                double tLat, tLon;
                xSemaphoreTake(gpsMutex, portMAX_DELAY);
                tLat = safeLat; tLon = safeLon;
                xSemaphoreGive(gpsMutex);
                
                jsonPayload = "{\"dest\":\"" + String(packet.payload) + "\",\"lat\":" + String(tLat, 6) + ",\"lon\":" + String(tLon, 6) + "}";
            } else {
                jsonPayload = "{\"cmd\":\"" + String(packet.payload) + "\"}";
            }
            client.send(jsonPayload);
            sysLog("TX_ESP", "Sent Command");
        }

        // 10-Second Telemetry Sync heartbeat 
        if (navActive && isConnected && (millis() - lastTelemetrySync > 5000)) {
            lastTelemetrySync = millis();
            
            double cLat, cLon;
            if (xSemaphoreTake(gpsMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                cLat = safeLat; cLon = safeLon;
                xSemaphoreGive(gpsMutex);
                
                // === INDOOR HACKATHON OVERRIDE ===
                if (cLat == 0.0) {
                    cLat = 26.18628507035049; 
                    cLon = 91.6987279359482;
                    sysLog("GPS_WARN", "No satellite fix. Using SIMULATED coordinates.");
                }
                // =================================

                if (cLat != 0.0) { 
                    String telemetry = "{\"lat\":" + String(cLat, 6) + ",\"lon\":" + String(cLon, 6) + "}";
                    client.send(telemetry);
                    sysLog("GPS_SYNC", String(cLat, 4) + ", " + String(cLon, 4));
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

// 6. SETUP 

void setup() {
    Serial.begin(115200);
    sysLog("BOOT", "--- MASTER 5G HAPTIC ENGINE ---");
    
    gpsMutex = xSemaphoreCreateMutex();
    msgQueue = xQueueCreate(10, sizeof(OutgoingMsg));

    pinMode(BTN_DOT_PIN, INPUT_PULLUP);
    pinMode(BTN_DASH_PIN, INPUT_PULLUP);
    pinMode(BTN_DELETE_PIN, INPUT_PULLUP);
    pinMode(BTN_CLEAR_PIN, INPUT_PULLUP);
    pinMode(BTN_ACTION_PIN, INPUT_PULLUP);

    xTaskCreatePinnedToCore(Task_Core0_Processor, "InputTask", 4096, NULL, 3, NULL, 0);
    xTaskCreatePinnedToCore(Task_Core1_Radio, "RadioTask", 8192, NULL, 2, NULL, 1);
}

void loop() { vTaskDelete(NULL); }
