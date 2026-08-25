# Screen Recorder camera backend

This directory contains the FastAPI camera service used by the desktop
`ScreenRecorder.desktop` application. The desktop client connects only to the
loopback service at `http://127.0.0.1:8000` for camera status, capabilities,
FPS changes, and the MJPEG preview stream.

## Development start

From the `video` directory:

```bash
python3 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt
cd backend
venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

On the deployed Jetson, the service is normally installed at
`/opt/vision-system/backend` and started by `vision-system.service`. Do not run
two camera owners at the same time.

The C++ source under `tools/` enumerates Libargus sensor modes. Its compiled
binary is machine-specific and intentionally excluded from Git.
