import os
import cv2
import time
import yaml
import threading
import numpy as np
from datetime import datetime

class CameraReader:
    def __init__(self, config_path=None):
        if config_path is None:
            # Locate relative to workspace root (assuming config/camera.yaml)
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config", "camera.yaml")
        
        self.config_path = config_path
        self.source = 0
        self.width = 640
        self.height = 480
        self.fps = 30
        self.is_mock = False
        
        self.load_config()
        
        self.cap = None
        self.latest_frame = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
        # Mock animation helper state
        self.angle = 0
        
    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data and "camera" in data:
                        cam_cfg = data["camera"]
                        self.source = cam_cfg.get("source", 0)
                        self.width = cam_cfg.get("width", 640)
                        self.height = cam_cfg.get("height", 480)
                        self.fps = cam_cfg.get("fps", 30)
            else:
                print(f"Warning: Configuration file not found at {self.config_path}. Using defaults.")
        except Exception as e:
            print(f"Error loading camera config: {e}. Using defaults.")

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print("Camera capture thread started.")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.cap and self.cap.isOpened():
            self.cap.release()
        print("Camera capture thread stopped.")

    def _capture_loop(self):
        frame_delay = 1.0 / self.fps
        
        while self.running:
            start_time = time.time()
            frame = None
            
            # If camera is not opened, try to open it
            if self.cap is None or not self.cap.isOpened():
                try:
                    src = self.source
                    if isinstance(src, str) and src.isdigit():
                        src = int(src)
                        
                    is_jetson = os.path.exists("/etc/nv_tegra_release")
                    opened = False
                    
                    if is_jetson and isinstance(src, int):
                        # Try opening CSI camera via GStreamer for Jetson
                        pipeline = (
                            f"nvarguscamerasrc sensor-id={src} ! "
                            f"video/x-raw(memory:NVMM), width=(int){self.width}, height=(int){self.height}, format=(string)NV12, framerate=(fraction){self.fps}/1 ! "
                            f"nvvidconv flip-method=0 ! "
                            f"video/x-raw, width=(int){self.width}, height=(int){self.height}, format=(string)BGRx ! "
                            f"videoconvert ! "
                            f"video/x-raw, format=(string)BGR ! appsink drop=true"
                        )
                        print(f"Attempting to open CSI camera via GStreamer: {pipeline}")
                        self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                        if self.cap is not None and self.cap.isOpened():
                            opened = True
                            print(f"CSI camera on Jetson initialized successfully (Source: {src})")
                    
                    if not opened:
                        print(f"Attempting to open camera using default API (Source: {src})")
                        self.cap = cv2.VideoCapture(src)
                        if self.cap is not None and self.cap.isOpened():
                            # Configure resolution
                            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                            opened = True
                            print(f"Camera initialized successfully (Source: {src})")
                except Exception as e:
                    print(f"Exception initializing physical camera: {e}. Will retry in next loop iteration.")
                    if self.cap:
                        self.cap.release()
                    self.cap = None

            # Read frame if camera is opened
            if self.cap and self.cap.isOpened():
                try:
                    ret, img = self.cap.read()
                    if ret:
                        frame = img
                    else:
                        print("Failed to read frame from physical camera. Releasing for retry.")
                        self.cap.release()
                        self.cap = None
                except Exception as e:
                    print(f"Exception reading frame: {e}. Releasing camera.")
                    if self.cap:
                        self.cap.release()
                    self.cap = None
            
            # Generate black OFFLINE frame if camera is offline (never fallback to simulated pattern)
            if frame is None:
                frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
                # Draw white warning text
                cv2.putText(frame, "NO CAMERA DETECTED (CAM0)", (self.width // 2 - 210, self.height // 2), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                cv2.putText(frame, "Please check physical connection to CAM0 port", (self.width // 2 - 240, self.height // 2 + 40), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 150), 1)
                
            # Compress to jpeg
            ret, jpeg = cv2.imencode('.jpg', frame)
            if ret:
                with self.lock:
                    self.latest_frame = jpeg.tobytes()
                    
            # Maintain target FPS
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_delay - elapsed)
            time.sleep(sleep_time)

    def get_frame(self) -> bytes:
        with self.lock:
            return self.latest_frame
            
    def get_status(self) -> dict:
        connected = self.cap is not None and self.cap.isOpened()
        return {
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "is_mock": False,
            "connected": connected
        }
