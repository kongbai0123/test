import os
import sys
import yaml
import json
import asyncio

# Ensure the backend directory is in the Python search path for sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List, Optional

from system_monitor import get_system_status
from camera import CameraReader

app = FastAPI(title="Vision AI Backend API (PC Developer Version)")

# Allow CORS for development (React runs on 3000, backend on 8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables
camera_reader = None
inference_running = False

# Path helper
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")

# --- Schemas ---
class LoginRequest(BaseModel):
    username: str
    password: str

class UserConfig(BaseModel):
    username: str
    password_hash: str
    role: str

# --- Startup and Shutdown Events ---
@app.on_event("startup")
async def startup_event():
    global camera_reader
    camera_cfg_path = os.path.join(CONFIG_DIR, "camera.yaml")
    camera_reader = CameraReader(camera_cfg_path)
    camera_reader.start()
    print("FastAPI application started and Camera capture initialized.")

@app.on_event("shutdown")
async def shutdown_event():
    global camera_reader
    if camera_reader:
        camera_reader.stop()
    print("FastAPI application stopped and Camera capture released.")

# --- Helper Functions ---
def load_yaml_config(filename: str) -> dict:
    path = os.path.join(CONFIG_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error loading config {filename}: {e}")
    return {}

def load_users() -> list:
    path = os.path.join(CONFIG_DIR, "users.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("users", [])
        except Exception as e:
            print(f"Error loading users: {e}")
    return []

# --- API Endpoints ---

@app.get("/health")
def health():
    camera_status = "offline"
    camera_source = "None"
    if camera_reader:
        status_info = camera_reader.get_status()
        if status_info.get("connected"):
            camera_status = "connected"
            camera_source = status_info.get("source", "Unknown")
            
    return {
        "status": "ok",
        "backend": "online",
        "model": "loaded" if load_yaml_config("model.yaml").get("model", {}).get("loaded", False) else "not_loaded",
        "camera": camera_status,
        "camera_source": camera_source
    }

@app.get("/system/status")
def system_status():
    return get_system_status(inference_active=inference_running)

@app.get("/camera/status")
def camera_status():
    if camera_reader:
        return camera_reader.get_status()
    # Fallback if app not fully started
    camera_cfg = load_yaml_config("camera.yaml").get("camera", {})
    return {
        "source": camera_cfg.get("source", 0),
        "width": camera_cfg.get("width", 640),
        "height": camera_cfg.get("height", 480),
        "fps": camera_cfg.get("fps", 30),
        "is_mock": True,
        "connected": False
    }

@app.get("/model/status")
def model_status():
    model_cfg = load_yaml_config("model.yaml").get("model", {})
    if not model_cfg:
        return {
            "loaded": False,
            "model_name": "unknown",
            "backend": "none"
        }
    return {
        "loaded": model_cfg.get("loaded", False),
        "model_name": model_cfg.get("model_name", "unknown"),
        "version": model_cfg.get("version", "0.0.0"),
        "input_size": model_cfg.get("input_size", [640, 640]),
        "backend": model_cfg.get("backend", "TensorRT")
    }

# Video streaming helper generator
def video_frame_generator():
    global camera_reader
    while True:
        if camera_reader:
            frame_bytes = camera_reader.get_frame()
            if frame_bytes:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        # Pause slightly to match frame timing (about 30 FPS)
        time_to_sleep = 0.03
        import time
        time.sleep(time_to_sleep)

@app.get("/video_feed")
def video_feed():
    return StreamingResponse(
        video_frame_generator(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.post("/auth/login")
def login(request: LoginRequest):
    users = load_users()
    for user in users:
        # Simple plain text match for development/PC design stage as described in schema
        if user["username"] == request.username and user["password_hash"] == request.password:
            return {
                "success": True,
                "token": f"mock_token_{user['username']}",
                "user": {
                    "username": user["username"],
                    "role": user["role"]
                }
            }
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Username or password incorrect."
    )

@app.post("/inference/start")
def start_inference():
    global inference_running
    inference_running = True
    return {"status": "success", "inference_running": inference_running}

@app.post("/inference/stop")
def stop_inference():
    global inference_running
    inference_running = False
    return {"status": "success", "inference_running": inference_running}

@app.get("/inference/status")
def inference_status():
    global inference_running
    return {"inference_running": inference_running}

# Serve frontend static files if built
dist_dir = os.path.join(BASE_DIR, "frontend", "dist")
if os.path.exists(dist_dir):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static")

