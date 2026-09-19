from datetime import datetime
import socket

def stream_movement_data(port=5005):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))

    print(f"=== LISTENER READY ON PORT {port} ===")
    print("Waiting for data stream (1 update/sec)...\n")

    packet_id = 0

    while True:
        data, addr = sock.recvfrom(1024)
        packet_id += 1
        text = data.decode("utf-8", errors="ignore").strip()
        now = datetime.now().strftime("%H:%M:%S")

        try:
            parts = text.split("|")
            acc_str = parts[0]
            heading = float(parts[1])
            lat, lon, alt = [float(v) for v in parts[2].split(",")]

            gps_status = (
                f"Lat: {lat:10.6f} | Lon: {lon:11.6f} | Alt: {alt:5.1f}m"
                if lat != 0.0
                else "Acquiring GPS fix..."
            )

            print(
                f"[{now} | #{packet_id:04d}] Compass: {heading:5.1f}° | Accel: {acc_str} | {gps_status}",
                flush=True,
            )
            
            # Yield the parsed data as a dictionary so other scripts can use it
            yield {
                "accel": acc_str,
                "facing": heading,
                "lat": lat,
                "lon": lon
            }

        except Exception:
            print(f"[{now} | #{packet_id:04d}] RAW: {text}", flush=True)
            yield None

if __name__ == "__main__":
    # If run directly, just loop through the stream (which will print the status inside the function)
    for data in stream_movement_data():
        pass