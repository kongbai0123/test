import os
import cv2

def scan_cameras():
    print("=== Jetson Camera Port Detection Tool ===")
    is_jetson = os.path.exists("/etc/nv_tegra_release")
    print(f"Platform: {'Jetson' if is_jetson else 'Standard PC'}")
    
    found = False
    
    # 1. Test Jetson CSI Ports
    if is_jetson:
        print("\nScanning Jetson CSI Ports...")
        for sensor_id in [0, 1]:
            pipeline = (
                f"nvarguscamerasrc sensor-id={sensor_id} ! "
                f"video/x-raw(memory:NVMM), width=640, height=480, format=(string)NV12, framerate=(fraction)30/1 ! "
                f"nvvidconv ! video/x-raw, format=(string)BGR ! appsink drop=true"
            )
            try:
                cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                if cap is not None and cap.isOpened():
                    ret, img = cap.read()
                    if ret and img is not None:
                        print(f"-> SUCCESS: CSI Camera detected on Port CAM{sensor_id} (sensor-id={sensor_id})")
                        found = True
                    else:
                        print(f"-> FAILED: CSI Camera Port CAM{sensor_id} opened but cannot read frames.")
                    cap.release()
                else:
                    print(f"-> FAILED: CSI Camera Port CAM{sensor_id} could not be opened.")
            except Exception as e:
                print(f"-> ERROR testing CSI CAM{sensor_id}: {e}")
                
    # 2. Test V4L2 Device Nodes
    print("\nScanning V4L2 USB/Standard Camera Ports...")
    for idx in range(5):
        try:
            cap = cv2.VideoCapture(idx)
            if cap is not None and cap.isOpened():
                ret, img = cap.read()
                if ret and img is not None:
                    print(f"-> SUCCESS: USB/V4L2 Camera detected on /dev/video{idx}")
                    found = True
                else:
                    print(f"-> FAILED: /dev/video{idx} opened but cannot read frames.")
                cap.release()
            else:
                # Check if file exists to see if it's there but busy
                if os.path.exists(f"/dev/video{idx}"):
                    print(f"-> BUSY: /dev/video{idx} exists but could not be opened (might be in use by another app).")
                    found = True
        except Exception as e:
            print(f"-> ERROR testing /dev/video{idx}: {e}")
                
    if not found:
        print("\n❌ Result: No working camera detected on any CSI or V4L2 port!")
    else:
        print("\n✅ Result: Scanning completed.")

if __name__ == "__main__":
    scan_cameras()
