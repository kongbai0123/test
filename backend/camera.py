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
        self.is_mock = True
        
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
        # Try to open the physical camera
        try:
            # If source is a string representing a number, convert it to int
            src = self.source
            if isinstance(src, str) and src.isdigit():
                src = int(src)
                
            self.cap = cv2.VideoCapture(src)
            if self.cap is not None and self.cap.isOpened():
                # Configure resolution
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.is_mock = False
                print(f"Physical camera initialized successfully (Source: {src})")
            else:
                self.is_mock = True
                print(f"Could not open physical camera (Source: {src}). Falling back to Mock Camera.")
        except Exception as e:
            self.is_mock = True
            print(f"Exception initializing physical camera: {e}. Falling back to Mock Camera.")
            
        frame_delay = 1.0 / self.fps
        
        while self.running:
            start_time = time.time()
            frame = None
            
            if not self.is_mock and self.cap and self.cap.isOpened():
                ret, img = self.cap.read()
                if ret:
                    frame = img
                else:
                    # If reading fails, degrade to mock
                    self.is_mock = True
                    print("Physical camera connection lost. Switching to Mock Camera.")
            
            if self.is_mock or frame is None:
                frame = self._generate_mock_frame()
                
            # Compress to jpeg
            ret, jpeg = cv2.imencode('.jpg', frame)
            if ret:
                with self.lock:
                    self.latest_frame = jpeg.tobytes()
                    
            # Maintain target FPS
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_delay - elapsed)
            time.sleep(sleep_time)

    def _generate_mock_frame(self):
        # Create a beautiful dark slate background (RGB: 15, 23, 42)
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = [42, 23, 15]  # BGR representation
        
        # Dynamic pulse circle
        self.angle = (self.angle + 4) % 360
        pulse_radius = int(80 + 15 * np.sin(np.radians(self.angle)))
        cx, cy = self.width // 2, self.height // 2
        
        # Draw scanning radar line
        rad = np.radians(self.angle)
        end_x = int(cx + pulse_radius * np.cos(rad))
        end_y = int(cy + pulse_radius * np.sin(rad))
        cv2.circle(frame, (cx, cy), pulse_radius, (118, 185, 0), 2)  # NVIDIA Green (RGB: 118, 185, 0 -> BGR: 0, 185, 118)
        cv2.line(frame, (cx, cy), (end_x, end_y), (118, 185, 0), 2)
        cv2.circle(frame, (cx, cy), 5, (0, 185, 118), -1)
        
        # Add target crosshairs or detection box overlays to simulate AI detection
        if self.angle % 60 < 30:
            # Simulate a detected vehicle bounding box
            cv2.rectangle(frame, (cx - 100, cy - 80), (cx + 100, cy + 80), (0, 0, 255), 2)
            cv2.putText(frame, "Simulated Car: 98.4%", (cx - 100, cy - 90), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            
        # Draw overlay text
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        cv2.putText(frame, f"TIME: {now_str}", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, f"CAMERA PORT: {self.source} (MOCKED)", (20, 75), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
        cv2.putText(frame, f"FPS: {self.fps} | RESOLUTION: {self.width}x{self.height}", (20, 110), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
        
        # Draw status indicator
        cv2.circle(frame, (self.width - 40, 40), 10, (0, 165, 255), -1) # Orange dot for simulated
        cv2.putText(frame, "SIMULATOR ACTIVE", (self.width - 210, 45), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)
                    
        return frame

    def get_frame(self) -> bytes:
        with self.lock:
            return self.latest_frame
            
    def get_status(self) -> dict:
        return {
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "is_mock": self.is_mock,
            "connected": not self.is_mock
        }
