import asyncio
import websockets
import time

# Reference point to keep numbers small for ESP32 (prevent overflow)
SYS_START = time.monotonic()

def current_ms():
    # Returns milliseconds since the script started
    return int((time.monotonic() - SYS_START) * 1000)

async def handle_client(websocket):
    print("ESP32 Connected. Protocol: Research-Grade Min-RTT + Rolling Heartbeat.")
    
    try:
        while True:
            # 1. Prepare Heartbeat Sync Packet
            t1_server_sent = current_ms()
            # Format: SYNC, ServerSentTime
            await websocket.send(f"SYNC,{t1_server_sent}")

            # 2. Wait for ESP32 Reflection
            try:
                # 2-second timeout to handle potential 5G drops
                raw_msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                t4_server_recv = current_ms()
                
                parts = raw_msg.split(",")
                if parts[0] == "REPLY":
                    # Data from ESP32
                    orig_t1 = int(parts[1])
                    esp_t2_recv = int(parts[2])
                    esp_t3_sent = int(parts[3])

                    # Calculate Full Round Trip
                    rtt = t4_server_recv - orig_t1
                    # How long the ESP32 held the packet
                    esp_hold_time = esp_t3_sent - esp_t2_recv
                    # Actual Airtime
                    airtime = rtt - esp_hold_time

                    print(f"\n[NETWORK REPORT] RTT: {rtt}ms | Airtime: {airtime}ms")
                    print(f"Server Stats: T1={orig_t1}, T4={t4_server_recv}")

            except asyncio.TimeoutError:
                print("[WARNING] Heartbeat timeout. Link unstable.")

            # Send a benchmark packet every 2 seconds
            await asyncio.sleep(2.0)

    except websockets.exceptions.ConnectionClosed:
        print("ESP32 Disconnected.")

async def main():
    print("--- 5G EDGE BENCHMARK SERVER RUNNING ---")
    async with websockets.serve(handle_client, "0.0.0.0", 8765):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())