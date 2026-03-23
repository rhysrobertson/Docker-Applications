import json  # For parsing incoming MQTT JSON payloads
import requests  # For making HTTP requests to the CMTK API
import paho.mqtt.client as mqtt  # MQTT client for subscribing to vibration data
from influxdb_client import InfluxDBClient, Point  # InfluxDB client and data point builder
from influxdb_client.client.write_api import SYNCHRONOUS  # Synchronous write mode
import os  # Access environment variables
import threading  # For running beacon polling in a separate thread
import time  # For delays and timing

# =========================
# INFLUX CONFIG VARIABLES
# =========================
INFLUX_URL = os.getenv("INFLUX_URL")  # InfluxDB server URL
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")  # Authentication token
INFLUX_ORG = os.getenv("INFLUX_ORG")  # Organization name
INFLUX_VIB_BUCKET = os.getenv("INFLUX_VIB_BUCKET")  # Bucket for vibration data

# Initialize InfluxDB client
client = InfluxDBClient(
    url=INFLUX_URL,
    token=INFLUX_TOKEN,
    org=INFLUX_ORG
)

# Create synchronous write API
write_api = client.write_api(write_options=SYNCHRONOUS)

# =========================
# CMTK CONFIG VARIABLES
# =========================
CMTK_IP = os.getenv("CMTK_IP")  # IP address of the CMTK device
USERNAME = os.getenv("CMTK_USER")  # Login username
PASSWORD = os.getenv("CMTK_PASS")  # Login password

LOGIN_ENDPOINT = "/api/balluff/users/login"  # API endpoint for authentication
BEACON_ENDPOINT = "/iolink/v1/devices/master1port1/processdata/value"  # Beacon control endpoint

MQTT_BROKER = CMTK_IP  # MQTT broker (same as CMTK device)
MQTT_PORT = 1883  # Default MQTT port
MQTT_TOPIC = "balluff/cmtk/master1/iolink/devices/port2/data/fromdevice"  # Topic to subscribe

# Vibration thresholds for beacon control
VIBRATION_THRESHOLD1 = 3.0  # Warning threshold
VIBRATION_THRESHOLD2 = 40.0  # Critical threshold

# Beacon color values (device-specific byte arrays)
GREEN = [1, 0]
YELLOW = [5, 0]
RED = [2, 0]

# =========================
# BEACON CONTROLLER CLASS
# =========================
class BeaconController:
    def __init__(self):
        # Create persistent HTTP session
        self.session = requests.Session()
        self.current_state = None  # Track current beacon state to avoid redundant updates

        # Authenticate with CMTK API
        login = self.session.post(
            f"http://{CMTK_IP}{LOGIN_ENDPOINT}",
            json={
                "username": USERNAME,
                "password": PASSWORD
            }
        )

    def set_beacon(self, color):
        # Prevent sending duplicate state updates
        if self.current_state == color:
            return  

        # Payload format for IO-Link beacon control
        payload = {
            "ioLink": {
                "valid": True,
                "value": color
            }
        }

        # Send command to beacon endpoint
        r = self.session.post(
            f"http://{CMTK_IP}{BEACON_ENDPOINT}",
            json=payload
        )

        # Update state if successful
        if r.status_code in (200, 204):
            self.current_state = color

            # Optional: determine color name (not used further)
            name = (
                "GREEN" if color == GREEN else
                "YELLOW" if color == YELLOW else
                "RED"
            )

    def reset(self):
        """Turn beacon off (used during shutdown)"""
        payload = {
            "ioLink": {
                "valid": True,
                "value": [0, 0]
            }
        }
        self.session.post(
            f"http://{CMTK_IP}{BEACON_ENDPOINT}",
            json=payload
        )

    def poll_beacon_state(self):
        """Poll current beacon state and write it to InfluxDB"""
        try:
            # Request current beacon data
            r = self.session.get(
                f"http://{CMTK_IP}{BEACON_ENDPOINT}",
                timeout=2
            )

            data = r.json()

            # Extract byte array and timestamp
            byte_array = data.get("setData", {}).get("ioLink", {}).get("value", [])
            timestamp = data.get("ts")

            if byte_array:
                segment1 = byte_array[0]  # First byte represents status

                # Create InfluxDB point
                point = (
                    Point("cmtk_device")
                    .tag("device", "master1port1")
                    .field("beacon_status", int(segment1))
                    .time(timestamp)
                )

                # Write to InfluxDB
                write_api.write(
                    bucket=INFLUX_VIB_BUCKET,
                    org=INFLUX_ORG,
                    record=point
                )

        except Exception as e:
            print("Beacon poll error:", e)

# =========================
# MQTT CALLBACKS
# =========================
def on_connect(client, userdata, flags, rc):
    # Subscribe to topic on successful connection
    if rc == 0:
        client.subscribe(MQTT_TOPIC)


def on_message(client, userdata, msg):
    """Handle incoming MQTT vibration data"""
    try:
        # Parse JSON payload
        payload = json.loads(msg.payload.decode())
        items = payload.get("data", {}).get("items", {})

        # Extract vibration and temperature values
        x_vibration = float(items.get(
            "Vibration Velocity Peak to Peak v-Peak-to-Peak X", 0.0
        ))
        y_vibration = float(items.get(
            "Vibration Velocity Peak to Peak v-Peak-to-Peak Y", 0.0
        ))
        z_vibration = float(items.get(
            "Vibration Velocity Peak to Peak v-Peak-to-Peak Z", 0.0
        ))
        contact_temperature = float(items.get(
            "Contact Temperature Contact Temperature", 0.0
        ))

        # Determine beacon color based on X-axis vibration
        if VIBRATION_THRESHOLD1 <= x_vibration <= VIBRATION_THRESHOLD2:
            beacon.set_beacon(YELLOW)
        elif x_vibration > VIBRATION_THRESHOLD2:
            beacon.set_beacon(RED)
        else:
            beacon.set_beacon(GREEN)

        # Create InfluxDB point for vibration data
        point = (
            Point("cmtk_device")
            .tag("device", "master1port2")
            .field("vib_x", x_vibration)
            .field("vib_y", y_vibration)
            .field("vib_z", z_vibration)
            .field("temp", contact_temperature)
        )

        # Write data to InfluxDB
        write_api.write(
            bucket=INFLUX_VIB_BUCKET,
            org=INFLUX_ORG,
            record=point
        )

    except Exception as e:
        print("MQTT parse error:", e)

# =========================
# BACKGROUND BEACON POLLING
# =========================
def beacon_polling_loop():
    """Continuously poll beacon state in background"""
    while True:
        beacon.poll_beacon_state()
        time.sleep(0.25)  # Polling interval

# =========================
# MAIN ENTRY POINT
# =========================
if __name__ == "__main__":
    # Initialize beacon controller
    beacon = BeaconController()

    # Start background thread for polling beacon state
    threading.Thread(target=beacon_polling_loop, daemon=True).start()

    # Initialize MQTT client
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect to MQTT broker
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    try:
        # Start MQTT loop (blocking)
        client.loop_forever()
    except KeyboardInterrupt:
        # Graceful shutdown
        print("\nShutting down...")
        beacon.reset()  # Turn off beacon
        client.disconnect()