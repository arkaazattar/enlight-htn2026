import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import cv2
import queue

class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/video_feed':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            while True:
                try:
                    # Get the latest frame from the server's global frame queue
                    frame_bytes = self.server.get_latest_frame()
                    if frame_bytes is None:
                        time.sleep(0.01)
                        continue
                        
                    self.wfile.write(b'--frame\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(frame_bytes)))
                    self.end_headers()
                    self.wfile.write(frame_bytes)
                    self.wfile.write(b'\r\n')
                except Exception as e:
                    break
        else:
            self.send_error(404)
            self.end_headers()

class MJPEGServer:
    def __init__(self, port=8001):
        self.port = port
        self.server = HTTPServer(('', port), MJPEGHandler)
        self.latest_frame = None
        self.lock = threading.Lock()
        
        # Add a custom method to the server instance to retrieve frames
        self.server.get_latest_frame = self._get_latest_frame
        
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        
    def start(self):
        self.thread.start()
        
    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        
    def update_frame(self, frame):
        # Encode frame as JPEG
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
        ret, buffer = cv2.imencode('.jpg', frame, encode_param)
        if ret:
            with self.lock:
                self.latest_frame = buffer.tobytes()
                
    def _get_latest_frame(self):
        with self.lock:
            return self.latest_frame
