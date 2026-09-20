from datetime import datetime
import socket

def stream_movement_data(port=5005):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Ensure address reuse so it doesn't conflict easily
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass # SO_REUSEPORT not available on all systems
        
    sock.bind(("0.0.0.0", port))

    print(f"=== LISTENER READY ON PORT {port} ===")
    print("Waiting for UDP data stream from phone...\n")

    packet_id = 0

    while True:
        data, addr = sock.recvfrom(1024)
        packet_id += 1
        text = data.decode("utf-8", errors="ignore").strip()
        now = datetime.now().strftime("%H:%M:%S")

        print(f"[{now} | #{packet_id:04d}] RECEIVED: {text}", flush=True)
        yield {"raw": text}

if __name__ == "__main__":
    try:
        for data in stream_movement_data():
            pass
    except KeyboardInterrupt:
        print("\nStopped.")
