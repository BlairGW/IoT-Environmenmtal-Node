import paho.mqtt.client as mqtt
import ssl
import time
import requests
import json
import os
import base64
from sense_hat import SenseHat
from datetime import datetime
from urllib.parse import quote_plus
from cryptography.fernet import Fernet

sense = SenseHat()

# --- Configuration ---
broker_address = "mqtt3.thingspeak.com"
port = 443

CREDENTIALS_FILE = "EnvNode/credentials.enc"
KEY_FILE = "EnvNode/credentials.key"
LOG_FILE = "EnvNode/sensor_readings.txt"

# --- Sensor Metadata ---
SENSOR_INFO = """
========================================
        SENSOR SPECIFICATIONS
========================================
TEMPERATURE
  Range:            -40°C to 120°C
  Optimal Accuracy: 15°C to 40°C
  Accuracy:         ±2°C (0°C to 65°C)
  Resolution:       0.016°C

HUMIDITY
  Range:            0% to 100%
  Optimal Accuracy: 20% to 80%
  Accuracy:         ±4.5% (20% to 80%)
  Resolution:       0.004%

PRESSURE
  Range:            260 hPa to 1260 hPa
  Absolute Accuracy:  ±0.2 hPa
  Relative Accuracy:  ±0.1 hPa
  Resolution:         0.0002 hPa
========================================
"""

# ============================================================
#  ENCRYPTION HELPERS
# ============================================================

def load_or_create_key() -> bytes:
    """Load the Fernet key from disk, creating it if it doesn't exist."""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    print(f"[INFO] New encryption key created and saved to '{KEY_FILE}'.")
    print("[WARN] Keep this file safe — losing it means losing access to your credentials.")
    return key


def save_credentials(creds: dict, key: bytes) -> None:
    """Encrypt and save credentials to disk."""
    fernet = Fernet(key)
    plaintext = json.dumps(creds).encode()
    token = fernet.encrypt(plaintext)
    with open(CREDENTIALS_FILE, "wb") as f:
        f.write(token)
    print(f"[INFO] Credentials saved to '{CREDENTIALS_FILE}'.")


def load_credentials(key: bytes) -> dict | None:
    """
    Load and decrypt credentials from disk.
    Returns None if the file is missing or empty.
    """
    if not os.path.exists(CREDENTIALS_FILE):
        return None
    with open(CREDENTIALS_FILE, "rb") as f:
        token = f.read()
    if not token.strip():
        return None
    fernet = Fernet(key)
    plaintext = fernet.decrypt(token)
    return json.loads(plaintext.decode())


# ============================================================
#  CREDENTIAL PROMPT
# ============================================================

def prompt_credentials(existing: dict | None = None) -> dict:
    """
    Interactively prompt the user for ThingSpeak credentials.
    If `existing` is provided, pressing Enter keeps the current value.
    """
    print("\n--- ThingSpeak Credential Setup ---")
    print("(Press Enter to keep the current value where shown)\n")

    def ask(field: str, current: str | None) -> str:
        hint = f" [{current}]" if current else ""
        value = input(f"  {field}{hint}: ").strip()
        if not value and current:
            return current
        while not value:
            value = input(f"  {field} (required): ").strip()
        return value

    return {
        "client_id":  ask("Client ID",  existing.get("client_id")  if existing else None),
        "username":   ask("Username",   existing.get("username")    if existing else None),
        "password":   ask("Password",   existing.get("password")    if existing else None),
        "channel_id": ask("Channel ID", existing.get("channel_id")  if existing else None),
    }


def get_credentials() -> dict:
    """
    Manage the credential lifecycle:
      1. Load the encryption key (or create it).
      2. Load stored credentials (if any).
      3. Ask the user whether to update or run.
    """
    key = load_or_create_key()
    stored = load_credentials(key)

    if stored is None:
        print("\n[INFO] No credentials found. Please enter your ThingSpeak details.")
        creds = prompt_credentials()
        save_credentials(creds, key)
        return creds

    # Credentials exist — let the user decide
    print("\n========================================")
    print("  ThingSpeak credentials found.")
    print("  What would you like to do?")
    print("  [1] Run with current credentials")
    print("  [2] Update credentials")
    print("========================================")

    while True:
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            print("[INFO] Using existing credentials.")
            return stored
        elif choice == "2":
            creds = prompt_credentials(existing=stored)
            save_credentials(creds, key)
            return creds
        else:
            print("  Please enter 1 or 2.")


# ============================================================
#  FILE LOGGING
# ============================================================

def init_log_file() -> None:
    """Write sensor specs header to log file on startup."""
    with open(LOG_FILE, "a") as f:
        f.write(f"\n{'='*40}\n")
        f.write(f"  SESSION STARTED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(SENSOR_INFO)


def log_reading(temperature: float, humidity: float, pressure: float,
                lat, lon) -> None:
    """Append a timestamped sensor reading to the log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    temp_note     = "" if (15 <= temperature <= 40) else " [OUTSIDE optimal accuracy range 15-40°C]"
    humidity_note = "" if (20 <= humidity    <= 80) else " [OUTSIDE optimal accuracy range 20-80%]"

    entry = f"""
----------------------------------------
Timestamp:   {timestamp}
Latitude:    {lat}
Longitude:   {lon}

  Temperature:  {temperature}°C{temp_note}
    Range:      -40°C to 120°C
    Accuracy:   ±2°C (valid 0-65°C)
    Resolution: 0.016°C

  Humidity:     {humidity}%{humidity_note}
    Range:      0% to 100%
    Accuracy:   ±4.5% (valid 20-80%)
    Resolution: 0.004%

  Pressure:     {pressure} hPa
    Range:      260 to 1260 hPa
    Abs. Acc.:  ±0.2 hPa
    Rel. Acc.:  ±0.1 hPa
    Resolution: 0.0002 hPa
----------------------------------------"""

    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")
    print(f"Reading logged to {LOG_FILE}")


# ============================================================
#  MQTT CALLBACKS
# ============================================================

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"Connected to ThingSpeak via Port {port}!")
        client.subscribe(userdata["TOPIC_SUB"])
    else:
        print(f"Connection failed. Error code: {rc}")

def on_message(client, userdata, msg):
    print("\n--- NEW MESSAGE RECEIVED ---")
    print(f"Topic: {msg.topic} | Message: {msg.payload.decode()}")
    try:
        payload_dict = json.loads(msg.payload.decode())
        print(f"Field 1 (Temp):     {payload_dict.get('field1')}")
        print(f"Field 2 (Humidity): {payload_dict.get('field2')}")
        print(f"Field 3 (Pressure): {payload_dict.get('field3')}")
    except json.JSONDecodeError as e:
        print(f"Failed to parse message: {e}")

def on_subscribe(client, userdata, mid, reason_codes, properties=None):
    print(f"Subscribed to {userdata['TOPIC_SUB']} (MID: {mid})")

def on_publish(client, userdata, mid, reason_code=None, properties=None):
    print(f"Message Published Successfully (MID: {mid})")

def on_log(client, userdata, level, buf):
    if "error" in buf.lower():
        print(f"DEBUG: {buf}")

def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    if reason_code != 0:
        print(f"--- Unexpected Disconnect! Reason code: {reason_code} ---")
    else:
        print("--- Disconnected gracefully ---")


# ============================================================
#  LOCATION
# ============================================================

def get_location():
    try:
        response = requests.get("http://ip-api.com/json/", timeout=10)
        data = response.json()
        if data["status"] == "success":
            return data["lat"], data["lon"]
        print("API error:", data.get("message"))
    except requests.exceptions.ConnectionError:
        print("No internet connection")
    except requests.exceptions.Timeout:
        print("Request timed out")
    return None, None


# ============================================================
#  MAIN
# ============================================================

def main():
    # Resolve credentials before doing anything else
    creds = get_credentials()

    client_id  = creds["client_id"]
    username   = creds["username"]
    password   = creds["password"]
    channel_id = creds["channel_id"]

    TOPIC_SUB  = f"channels/{channel_id}/subscribe"
    TOPIC_PUB  = f"channels/{channel_id}/publish"

    # Initialise log file
    init_log_file()

    # Build MQTT client
    userdata = {"TOPIC_SUB": TOPIC_SUB}
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        transport="websockets",
        userdata=userdata,
    )

    headers = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin":          "https://thingspeak.com",
    }
    client.ws_set_options(path="/mqtt", headers=headers)
    client.username_pw_set(username, password)
    client.tls_set_context(ssl.create_default_context())

    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_subscribe  = on_subscribe
    client.on_publish    = on_publish
    client.on_log        = on_log
    client.on_disconnect = on_disconnect

    print("Connecting to ThingSpeak...")
    client.connect(broker_address, port, 20)
    client.loop_start()

    try:
        while True:
            if client.is_connected():
                temperature = round(sense.get_temperature(), 2)
                humidity    = round(sense.get_humidity(),    2)
                pressure    = round(sense.get_pressure(),    2)

                lat, lon = get_location()

                payload = (
                    f"field1={temperature}&field2={humidity}&field3={pressure}"
                    f"&latitude={quote_plus(str(lat))}"
                    f"&longitude={quote_plus(str(lon))}"
                    f"&status={quote_plus('sensehat')}"
                )

                client.publish(TOPIC_PUB, payload)

                print(
                    f"Data published -> Temp: {temperature}°C | "
                    f"Humidity: {humidity}% | Pressure: {pressure} hPa | "
                    f"Lat: {lat}, Lon: {lon}"
                )

                log_reading(temperature, humidity, pressure, lat, lon)
                print("DEBUG payload:", payload)

                time.sleep(300)

    except KeyboardInterrupt:
        print("\nShutting down...")
        with open(LOG_FILE, "a") as f:
            f.write(f"\n  SESSION ENDED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 40 + "\n")
        client.unsubscribe(TOPIC_SUB)
        time.sleep(1)
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()