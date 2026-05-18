#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoWebsockets.h>

using namespace websockets;

// --- CONFIG ---
const char* ssid = "RUT_BEF3_2G"; 
const char* password = "Admin@123";
const char* ws_server_ip = "192.168.116.30"; 
const uint16_t ws_server_port = 8765;

WebsocketsClient client;
unsigned long lastSendTime = 0;

void sysLog(String tag, String msg) {
    Serial.printf("[%08lu] [%-12s] %s\n", millis(), tag.c_str(), msg.c_str());
}

// ASYNCHRONOUS LISTENER: This fires the moment the Mac sends a PUSH
void onMessage(WebsocketsMessage msg) {
    sysLog("FROM_MAC", ">>> " + msg.data());
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    sysLog("WIFI", "CONNECTED. IP: " + WiFi.localIP().toString());

    client.onMessage(onMessage);
}

void loop() {
    // 1. Ensure Connection
    if (!client.available()) {
        sysLog("WS", "Attempting Link...");
        if (client.connect(ws_server_ip, ws_server_port, "/")) {
            sysLog("WS", "SUCCESS: Duplex Tunnel Open.");
        } else {
            delay(3000);
            return;
        }
    }

    // 2. The "Ear": Listen for server data
    client.poll();

    // 3. The "Mouth": Independent send (Every 5 seconds)
    if (millis() - lastSendTime > 5000) {
        lastSendTime = millis();
        
        // Virtual GPS (Core 2 IITG) + Your "hi ok" message
        String packet = "{\"dest\":\"hi ok\",\"lat\":26.192340,\"lon\":91.691740}";
        client.send(packet);
        sysLog("TO_MAC", "<<< Sending: " + packet);
    }
}
