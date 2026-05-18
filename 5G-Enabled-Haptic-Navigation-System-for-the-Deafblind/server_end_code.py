import asyncio
import websockets
import googlemaps
import json
import math
import time
import polyline
import folium
import signal
import socket
from datetime import datetime

# ==============================================================================
# 1. SYSTEM CONFIGURATION & ANTI-KILL MECHANISM
# ==============================================================================
GOOGLE_KEY = "AIzaSyAXktgfo3zK9SuVlHMBReOpu4iP2o54nAg" # <- Paste your Google API key here
gmaps = googlemaps.Client(key=GOOGLE_KEY)

def log(tag, msg):
    t = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{t}] [{tag:^15}] {msg}")

def ignore_interrupt(sig, frame):
    log("SYSTEM", "Interrupt caught and BLOCKED. Close the terminal window to force quit.")
    
try:
    signal.signal(signal.SIGINT, ignore_interrupt)
except NotImplementedError:
    pass 

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# ==============================================================================
# 2. EDGE NAVIGATION ENGINE (1M DENSIFICATION + 1 POINT WARNING)
# ==============================================================================
class MasterNavigator:
    def __init__(self):
        self.is_active = False
        self.is_paused = False
        self.dense_path = []
        self.action_points = []
        self.original_target = ""
        self.last_known_lat = 0.0
        self.last_known_lon = 0.0
        self.last_instruction = "KEEP STRAIGHT"
        self.last_dispatch_time = 0
        self.first_move = True
        self.map_filename = "live_nav_map.html"

    def haversine(self, p1, p2):
        R = 6371000 
        lat1, lon1, lat2, lon2 = map(math.radians, [p1[0], p1[1], p2[0], p2[1]])
        a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
        return R * 2 * math.asin(math.sqrt(a))

    def get_bearing(self, p1, p2):
        lat1, lon1, lat2, lon2 = map(math.radians, [p1[0], p1[1], p2[0], p2[1]])
        dlon = lon2 - lon1
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    def generate_route(self, start_pos, dest_pos):
        log("ENGINE", f"Mapping route via Google Maps to: {dest_pos}")
        try:
            res = gmaps.directions(start_pos, dest_pos, mode="walking")
            if not res: 
                log("ENGINE_ERROR", "Maps API returned no route.")
                return False
            
            self.original_target = dest_pos
            steps = res[0]['legs'][0]['steps']
            raw_pts = []
            for s in steps:
                raw_pts.extend(polyline.decode(s['polyline']['points']))

            # Path Densification (1-meter intervals)
            self.dense_path = [raw_pts[0]]
            for i in range(len(raw_pts)-1):
                d = self.haversine(raw_pts[i], raw_pts[i+1])
                if d < 1.0: continue
                steps_needed = int(d / 1.0) # Changed to 1m resolution
                for j in range(1, steps_needed + 1):
                    f = j / steps_needed
                    new_lat = raw_pts[i][0] + (raw_pts[i+1][0] - raw_pts[i][0]) * f
                    new_lon = raw_pts[i][1] + (raw_pts[i+1][1] - raw_pts[i][1]) * f
                    self.dense_path.append((new_lat, new_lon))

            # Action Point Extraction
            self.action_points = []
            look = 8
            for i in range(look, len(self.dense_path) - look):
                b_in = self.get_bearing(self.dense_path[i-look], self.dense_path[i])
                b_out = self.get_bearing(self.dense_path[i], self.dense_path[i+look])
                diff = (b_out - b_in + 180) % 360 - 180
                
                if abs(diff) > 22:
                    if not self.action_points or self.haversine(self.dense_path[i], self.action_points[-1]['coords']) > 15:
                        
                        # TRIGGER: Exactly 1 point (1 meter) before the actual turn
                        warning_idx = max(0, i - 1) 
                        warning_pt = self.dense_path[warning_idx]

                        self.action_points.append({
                            'coords': self.dense_path[i],            
                            'warning_coords': warning_pt,            
                            'msg': "TURN_LEFT" if diff < 0 else "TURN_RIGHT",
                            'done': False
                        })
            
            self.is_active = True
            self.first_move = True
            log("ENGINE", f"Path Ready: {len(self.dense_path)} nodes | Detected {len(self.action_points)} turns.")
            
            self.update_visual_map()
            return True
            
        except Exception as e:
            log("CRITICAL", f"Engine Crash: {e}")
            return False

    def update_visual_map(self):
        try:
            m = folium.Map(location=[self.last_known_lat, self.last_known_lon], zoom_start=19)
            
            if self.dense_path:
                folium.PolyLine(self.dense_path, color="#2E86C1", weight=6, opacity=0.7).add_to(m)
            
            for ap in self.action_points:
                if not ap['done']:
                    folium.CircleMarker(
                        location=ap['coords'], radius=5, color="red",
                        fill=True, fill_color="red", fill_opacity=0.9,
                        popup="Actual Turn"
                    ).add_to(m)
                    
                    folium.CircleMarker(
                        location=ap['warning_coords'], radius=8, color="#F1C40F",
                        fill=True, fill_color="#F1C40F", fill_opacity=0.6,
                        popup="Instruction Sent Here"
                    ).add_to(m)

            folium.Marker(
                [self.last_known_lat, self.last_known_lon], 
                icon=folium.Icon(color='green', icon='user', prefix='fa'),
                popup="User"
            ).add_to(m)
            
            m.save(self.map_filename)
        except Exception as e:
            log("MAP_ERROR", f"Could not update HTML map: {e}")

    def process_telemetry(self, current_lat, current_lon):
        self.last_known_lat = current_lat
        self.last_known_lon = current_lon
        
        self.update_visual_map()
        
        if not self.is_active: return "IDLE"
        if self.first_move: 
            self.first_move = False
            return "WALK STRAIGHT TO START"

        user_pos = (current_lat, current_lon)
        dist_to_end = self.haversine(user_pos, self.dense_path[-1])
        if dist_to_end < 8: return "ARRIVED"

        dists = [self.haversine(user_pos, p) for p in self.dense_path]
        min_deviation = min(dists)
        
        if min_deviation > 12: return "DRIFT: CHECK PATH"
        
        for ap in self.action_points:
            # 4-Meter Catch Radius: Needed to safely intercept the 5-second GPS jump
            if not ap['done'] and self.haversine(user_pos, ap['warning_coords']) < 4:
                ap['done'] = True
                return f"ACTION: {ap['msg']}"
                
        return "KEEP STRAIGHT"

nav = MasterNavigator()

# ==============================================================================
# 3. WEBSOCKET ASYNC HANDLER
# ==============================================================================
async def socket_handler(websocket):
    client_ip = websocket.remote_address[0]
    log("NETWORK", f"Glove Connected: {client_ip}")
    try:
        async for message in websocket:
            data = json.loads(message)
            
            if 'cmd' in data:
                log("RX_CMD", f"User Command: {data['cmd'].upper()}")
            elif 'dest' in data:
                log("RX_DEST", f"New Target: {data['dest']}")
            elif 'lat' in data and len(data) == 2:
                log("RX_GPS", f"Update -> {data['lat']}, {data['lon']}")
            else:
                log("RX_RAW", f"{message}") 
            
            if 'dest' in data:
                target = (26.189277653645444, 91.69798626409093) if data['dest'] == "A" else data['dest']
                
                if nav.generate_route((data['lat'], data['lon']), target):
                    resp = f"STARTING NAV TO: {data['dest']}"
                    await websocket.send(resp)
                    log("TX_SERVER", "Nav Started")
                else:
                    # NEW: Explicitly tell the ESP32 we failed
                    await websocket.send("ERROR_NO_ROUTE")
                    log("TX_SERVER", "Sent Routing Failure")
            
            elif 'lat' in data:
                instruction = nav.process_telemetry(data['lat'], data['lon'])
                
                if nav.is_active and not nav.is_paused:
                    is_urgent = any(x in instruction for x in ["ACTION", "DRIFT", "ARRIVED", "WALK"])
                    
                    if is_urgent or (time.time() - nav.last_dispatch_time >= 15):
                        nav.last_instruction = instruction
                        nav.last_dispatch_time = time.time()
                        await websocket.send(instruction)
                        log("TX_SERVER", f"Sent: {instruction}")
            
            elif 'cmd' in data:
                cmd = data['cmd']
                
                if cmd == "reroute":
                    nav.generate_route((nav.last_known_lat, nav.last_known_lon), nav.original_target)
                    await websocket.send("REROUTING COMPLETE")
                    log("TX_SERVER", "Sent: REROUTING COMPLETE")
                    
                elif cmd == "resay":
                    await websocket.send(f"REPEAT: {nav.last_instruction}")
                    log("TX_SERVER", f"Sent: REPEAT: {nav.last_instruction}")
                    
                elif cmd == "pause":
                    nav.is_paused = True
                    await websocket.send("PAUSED")
                    log("TX_SERVER", "Sent: PAUSED")
                    
                elif cmd == "resume":
                    nav.is_paused = False
                    await websocket.send("RESUMED")
                    log("TX_SERVER", "Sent: RESUMED")
                    
                elif cmd == "cancel":
                    nav.is_active = False
                    await websocket.send("TERMINATED")
                    log("TX_SERVER", "Sent: TERMINATED")

    except websockets.exceptions.ConnectionClosed:
        nav.is_active = False
        log("ENGINE", "Session cleanly terminated due to disconnect.")
        log("NETWORK", f"Glove Disconnected. Awaiting Auto-Resume Request...")
    except Exception as e:
        log("ERROR", f"Socket Error: {e}")

async def main():
    mac_ip = get_local_ip()
    log("SYSTEM", "="*50)
    log("SYSTEM", "--- [MASTER 5G EDGE NAVIGATION SERVER] ---")
    log("SYSTEM", f"UPDATE ESP32 'ws_server_ip' TO: {mac_ip}")
    log("SYSTEM", "="*50)
    
    while True:
        try:
            async with websockets.serve(socket_handler, "0.0.0.0", 8765, ping_interval=3, ping_timeout=5):
                await asyncio.Future()
        except Exception as e:
            log("SYSTEM", f"Restarting server loop after error: {e}")
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
