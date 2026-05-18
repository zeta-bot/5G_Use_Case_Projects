import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
import googlemaps
import json
import math
import time
import polyline
import re
import folium
import os

# =====================================================
# 1. CONFIGURATION
# =====================================================
# REPLACE WITH YOUR ACTUAL KEY
GOOGLE_KEY = "AIzaSyAXktgfo3zK9SuVlHMBReOpu4iP2o54nAg" 

MQTT_BROKER = "0690d86c6cd945d4a0fe5834c0333c74.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "iitg_user"
MQTT_PASS = "12345678aA"

TOPIC_REQUEST = "deafblind/user/request"
TOPIC_GPS     = "deafblind/user/gps"
TOPIC_CONTROL = "deafblind/user/control"
TOPIC_INSTR   = "deafblind/server/instruction"

# =====================================================
# 2. PRECISION NAV ENGINE
# =====================================================
class PrecisionNavigator:
    def __init__(self):
        self.active = False
        self.dense_path = []
        self.action_points = []
        self.destination_text = ""
        self.last_instr = "KEEP STRAIGHT"
        self.last_send_time = 0
        self.is_paused = False
        self.last_lat = 0.0
        self.last_lon = 0.0
        self.map_filename = "live_nav_map.html"
        self.first_move = True 

    def haversine(self, p1, p2):
        R = 6371000
        lat1, lon1, lat2, lon2 = map(math.radians, [p1[0], p1[1], p2[0], p2[1]])
        a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2-lon1)/2)**2
        return R * 2 * math.asin(math.sqrt(a))

    def get_bearing(self, p1, p2):
        lat1, lon1, lat2, lon2 = map(math.radians, [p1[0], p1[1], p2[0], p2[1]])
        dlon = lon2 - lon1
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    def generate_route(self, start_pos, dest_target):
        print(f"\n[ENGINE] Generating path for: {dest_target}")
        try:
            directions = gmaps.directions(start_pos, dest_target, mode="walking")
            if not directions: return False
            
            steps = directions[0]['legs'][0]['steps']
            raw_pts = []
            for s in steps:
                raw_pts.extend(polyline.decode(s['polyline']['points']))

            self.dense_path = [raw_pts[0]] 
            for i in range(len(raw_pts)-1):
                d = self.haversine(raw_pts[i], raw_pts[i+1])
                if d < 0.5: continue
                steps_needed = int(d / 0.5)
                for j in range(1, steps_needed + 1):
                    f = j / steps_needed
                    self.dense_path.append((
                        raw_pts[i][0] + (raw_pts[i+1][0] - raw_pts[i][0]) * f,
                        raw_pts[i][1] + (raw_pts[i+1][1] - raw_pts[i][1]) * f
                    ))

            self.action_points = []
            look = 10
            for i in range(look, len(self.dense_path) - look):
                b_in = self.get_bearing(self.dense_path[i-look], self.dense_path[i])
                b_out = self.get_bearing(self.dense_path[i], self.dense_path[i+look])
                diff = (b_out - b_in + 180) % 360 - 180
                if abs(diff) > 22:
                    cmd = "TURN_LEFT" if diff < 0 else "TURN_RIGHT"
                    self.action_points.append({'coords': self.dense_path[i], 'msg': cmd})
            
            self.destination_text = str(dest_target)
            self.active = True
            self.first_move = True 
            self.update_visual_map(start_pos[0], start_pos[1])
            return True
        except Exception as e:
            print(f"[ERROR] Engine Failure: {e}")
            return False

    def update_visual_map(self, u_lat, u_lon):
        """Creates the HTML file for live tracking."""
        try:
            m = folium.Map(location=[u_lat, u_lon], zoom_start=20, tiles="CartoDB positron")
            
            # Path
            if self.dense_path:
                folium.PolyLine(self.dense_path, color="blue", weight=5, opacity=0.4).add_to(m)
                # Waypoints
                for ap in self.action_points:
                    color = 'red' if 'LEFT' in ap['msg'] else 'green'
                    folium.CircleMarker(location=ap['coords'], radius=6, color=color, fill=True).add_to(m)
                # Destination
                folium.Marker(self.dense_path[-1], icon=folium.Icon(color='black', icon='flag')).add_to(m)
            
            # Current Position
            folium.Marker([u_lat, u_lon], icon=folium.Icon(color='blue', icon='user', prefix='fa')).add_to(m)
            
            m.save(self.map_filename)
        except Exception as e:
            print(f"[MAP ERROR] {e}")

    def check_position(self, lat, lon):
        self.last_lat, self.last_lon = lat, lon
        u_pos = (lat, lon)
        self.update_visual_map(lat, lon)
        
        if not self.active or not self.dense_path: return "IDLE"

        if self.first_move:
            self.first_move = False
            return "WALK STRAIGHT TO START"

        if self.haversine(u_pos, self.dense_path[-1]) < 8:
            return "ARRIVED: TARGET REACHED"

        distances = [self.haversine(u_pos, p) for p in self.dense_path]
        min_dist = min(distances)
        nearest_idx = distances.index(min_dist)
        nearest_pt = self.dense_path[nearest_idx]

        if min_dist > 10:
            bearing_to_path = self.get_bearing(u_pos, nearest_pt)
            path_heading = self.get_bearing(self.dense_path[max(0, nearest_idx-5)], self.dense_path[min(len(self.dense_path)-1, nearest_idx+5)])
            angle_diff = (bearing_to_path - path_heading + 180) % 360 - 180
            side = "LEFT" if angle_diff < 0 else "RIGHT"
            if min_dist > 20: return "CRITICAL_DRIFT: REROUTING"
            return f"DRIFT: PATH IS TO YOUR {side}"
        
        for ap in self.action_points:
            if self.haversine(u_pos, ap['coords']) < 5: 
                return f"ACTION: {ap['msg']}"
        
        return "KEEP STRAIGHT"

    def reset(self):
        self.active = False
        self.dense_path = []
        self.first_move = True
        print("[SESSION] Reset.")

nav = PrecisionNavigator()
gmaps = googlemaps.Client(key=GOOGLE_KEY)

# =====================================================
# 3. MQTT HANDLERS
# =====================================================
def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print("[MQTT] Server Online. Map file: live_nav_map.html")
        client.subscribe([(TOPIC_REQUEST, 1), (TOPIC_GPS, 1), (TOPIC_CONTROL, 1)])

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
    except: return

    if msg.topic == TOPIC_REQUEST:
        dest_input = data.get('dest', "").strip().upper()
        target_dest = (26.196249529948126, 91.69737955152347) if dest_input == "A" else dest_input
        if nav.generate_route((data.get('lat'), data.get('lon')), target_dest):
            client.publish(TOPIC_INSTR, f"START: NAV TO {dest_input}")

    elif msg.topic == TOPIC_GPS:
        now = time.time()
        instr = nav.check_position(data.get('lat'), data.get('lon'))
        
        if nav.active and not nav.is_paused:
            if "REROUTING" in instr:
                nav.generate_route((data.get('lat'), data.get('lon')), nav.destination_text)
                return

            is_urgent = any(x in instr for x in ["ACTION", "DRIFT", "ARRIVED", "WALK STRAIGHT"])
            if is_urgent or (now - nav.last_send_time >= 20):
                nav.last_instr = instr
                nav.last_send_time = now
                client.publish(TOPIC_INSTR, instr)
                print(f"[DISPATCH] {instr}")

    elif msg.topic == TOPIC_CONTROL:
        cmd = data.get('cmd')
        if cmd == "cancel": nav.reset(); client.publish(TOPIC_INSTR, "TERMINATED")
        elif cmd == "resay": client.publish(TOPIC_INSTR, f"REPEAT: {nav.last_instr}")
        elif cmd == "reroute": nav.generate_route((nav.last_lat, nav.last_lon), nav.destination_text)

# =====================================================
# 4. EXECUTION
# =====================================================
client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id="Precision_Server")
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.tls_set()
client.on_connect, client.on_message = on_connect, on_message

print("--- [5G PRECISION NAVIGATION ENGINE ACTIVE] ---")
try:
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.loop_forever()
except KeyboardInterrupt:
    print("\n[SHUTDOWN] Server offline.")
