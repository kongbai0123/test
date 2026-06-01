import os
import platform
import random

try:
    import psutil
except ImportError:
    psutil = None

def get_cpu_usage() -> float:
    if psutil:
        return psutil.cpu_percent(interval=None)
    return round(random.uniform(10.0, 30.0), 1)

def get_memory_info() -> dict:
    if psutil:
        vm = psutil.virtual_memory()
        return {
            "total_gb": round(vm.total / (1024 ** 3), 2),
            "used_gb": round(vm.used / (1024 ** 3), 2),
            "percent": vm.percent
        }
    return {
        "total_gb": 8.0,
        "used_gb": 3.2,
        "percent": 40.0
    }

def get_disk_info() -> dict:
    if psutil:
        try:
            # Check partition containing current workspace
            du = psutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
            return {
                "total_gb": round(du.total / (1024 ** 3), 2),
                "used_gb": round(du.used / (1024 ** 3), 2),
                "free_gb": round(du.free / (1024 ** 3), 2),
                "percent": du.percent
            }
        except Exception:
            pass
    return {
        "total_gb": 128.0,
        "used_gb": 45.0,
        "free_gb": 83.0,
        "percent": 35.2
    }

def get_temperatures() -> dict:
    temps = {
        "cpu": 0.0,
        "gpu": 0.0,
        "is_mock": True
    }
    
    # Check if we are on Jetson Linux
    if platform.system() == "Linux":
        # Thermal zones mapping for Jetson Orin Series
        # Usually: /sys/class/thermal/thermal_zone0 (CPU), /sys/class/thermal/thermal_zone1 (GPU / GPU-thermal)
        cpu_temp_path = "/sys/class/thermal/thermal_zone0/temp"
        gpu_temp_path = "/sys/class/thermal/thermal_zone1/temp"
        
        try:
            if os.path.exists(cpu_temp_path):
                with open(cpu_temp_path, "r") as f:
                    temps["cpu"] = round(float(f.read().strip()) / 1000.0, 1)
                    temps["is_mock"] = False
            if os.path.exists(gpu_temp_path):
                with open(gpu_temp_path, "r") as f:
                    temps["gpu"] = round(float(f.read().strip()) / 1000.0, 1)
                    temps["is_mock"] = False
        except Exception:
            pass
            
    # Fallback to Mock temperatures for Windows/macOS or if reading fails
    if temps["is_mock"]:
        # Generate stable realistic temperatures with a small random walk
        temps["cpu"] = round(45.0 + random.uniform(-1.0, 1.0), 1)
        temps["gpu"] = round(48.0 + random.uniform(-1.0, 1.0), 1)
        
    return temps

def get_power_usage(inference_active: bool = False) -> dict:
    # Jetson Orin Nano power limits: typically 7W or 15W modes.
    # Idle power around 3.8W - 4.5W. Active AI inference around 10.5W - 13.8W.
    base_power = 12.1 if inference_active else 4.2
    fluctuation = random.uniform(-0.3, 0.3)
    current_w = round(base_power + fluctuation, 1)
    return {
        "current_w": current_w,
        "max_w": 15.0,
        "percent": round((current_w / 15.0) * 100, 1)
      }

def get_system_status(inference_active: bool = False) -> dict:
    return {
        "cpu_percent": get_cpu_usage(),
        "memory": get_memory_info(),
        "disk": get_disk_info(),
        "temperatures": get_temperatures(),
        "power": get_power_usage(inference_active),
        "platform": platform.system(),
        "processor": platform.processor()
    }
