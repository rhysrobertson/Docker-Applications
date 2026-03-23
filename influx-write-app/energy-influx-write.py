import time  # Provides time-related functions (e.g., delays, timestamps)
import os  # Allows interaction with the operating system (files, environment variables, paths)

from pymodbus.client.sync import ModbusTcpClient  # Synchronous Modbus TCP client for communicating with Modbus devices
from pymodbus.payload import BinaryPayloadDecoder  # Decodes binary data from Modbus registers into usable values
from pymodbus.constants import Endian  # Defines byte and word order (endianness) for decoding data

from influxdb_client import InfluxDBClient, Point, WritePrecision  # InfluxDB client tools: connection, data points, and timestamp precision
from influxdb_client.client.write_api import SYNCHRONOUS  # Enables synchronous (blocking) writes to InfluxDB

from registers import REGISTERS  # Imports a custom list/dictionary of Modbus register definitions from a local module (registers.py)

# ---------------- CONFIG VARIABLES ----------------

MODBUS_IP = os.getenv("MODBUS_IP")  # IP address of the Modbus device, loaded from environment variables

MODBUS_PORT = int(os.getenv("MODBUS_PORT"))  # TCP port for Modbus communication (usually 502), converted to integer

UNIT_ID = int(os.getenv("UNIT_ID"))  # Modbus unit/slave ID used to identify the target device

POLL_INTERVAL = 1  # (seconds) Time interval between consecutive Modbus polls (data reads)

INFLUX_URL = os.getenv("INFLUX_URL")  # URL endpoint of the InfluxDB instance

INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")  # Authentication token for accessing InfluxDB

INFLUX_ORG = os.getenv("INFLUX_ORG")  # InfluxDB organization name or ID

INFLUX_WAGO_BUCKET = os.getenv("INFLUX_WAGO_BUCKET")  # Target InfluxDB bucket where WAGO/Modbus data will be stored


# ---------------- INFLUX SETUP ----------------
# Initialize InfluxDB client
client = InfluxDBClient(
    url=INFLUX_URL,
    token=INFLUX_TOKEN,
    org=INFLUX_ORG,
)

write_api = client.write_api(write_options=SYNCHRONOUS)


# ---------------- HELPERS ----------------

# Defined function for converting a hexadecimal address to its decimal equivalent
def hex_address_to_decimal(addr):
    return int(str(addr), 16)

# Defined function for decoding Modbus register values based on their specified data type
def decode_register(reg, registers):

    decoder = BinaryPayloadDecoder.fromRegisters(
        registers,
        byteorder=Endian.Big,
        wordorder=Endian.Big
    )

    if reg["type"] == "float32":
        return decoder.decode_32bit_float()

    if reg["type"] == "signed":
        return decoder.decode_16bit_int()

    return None

# Defined function for sanitizing register names into safe, standardized field names
def sanitize(name):
    """
    Convert register names into safe field names
    """
    return (
        name.lower()
        .replace(" ", "_")
        .replace("*", "")
        .replace("-", "_")
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
    )


# ---------------- INFLUX WRITE ----------------

# Defined function for writing a data point to InfluxDB with timestamp and tags
def write_point(register_name, value):

    point = (
        Point("wago_meter")
        .tag("meter", "main")
        .field(sanitize(register_name), float(value))
        .time(time.time_ns(), WritePrecision.NS)
    )

    write_api.write(
        bucket=INFLUX_WAGO_BUCKET,
        org=INFLUX_ORG,
        record=point
    )


# ---------------- MODBUS LOOP ----------------

# Defined function for continuously polling Modbus registers and sending data to InfluxDB
def poll():

    client = ModbusTcpClient(MODBUS_IP, port=MODBUS_PORT)

    print("Connecting to Modbus...")

    if not client.connect():
        print("Modbus connection failed")
        return

    print("Connected to Modbus")

    while True:

        for name, reg in REGISTERS.items():

            try:

                result = client.read_holding_registers(
                    address=hex_address_to_decimal(reg["address"]),
                    count=reg["count"],
                    unit=UNIT_ID
                )

                if result.isError():
                    continue

                value = decode_register(reg, result.registers)

                if value is None:
                    continue

                write_point(name, value)

            except Exception as e:
                print(f"Error reading {name}: {e}")

        time.sleep(POLL_INTERVAL)


# ---------------- MAIN ----------------

if __name__ == "__main__":

    print("Starting Modbus → Influx logger")

    while True:
        try:
            poll()
        except Exception as e:
            print("Poll loop crashed:", e)
            time.sleep(3)