# Project: Screen Capture & Recording GUI Application

## Architecture
A unified, single-window Linux desktop application for screen capture and recording with NVIDIA hardware acceleration support, system tray integration, global hotkeys, floating control overlay, and embedded media manager.

```
+-----------------------------------------------------------------------------------+
|                        Unified Single-Window Main GUI                             |
|  +-----------------------------------------------------------------------------+  |
|  | Header: Status Indicator | Mode Toggle [Manual | Automatic] | Interval [ 5 ]s|  |
|  | Controls: [ Screenshot ] [ Record / Stop ] | Region [Full/ROI] | Audio [On] |  |
|  +-----------------------------------------------------------------------------+  |
|  | Embedded Media Panel (Split View)                                           |  |
|  | +-----------------------+-------------------------------------------------+ |  |
|  | | Recent Captures List  | In-App Media Preview / Embedded Video Player    | |  |
|  | | [Thumb] screenshot.png| [ Image Viewer / Canvas Video Player + Seekbar]| |  |
|  | | [Thumb] record.mp4    | [ Play / Pause / Seek / Counter / Metadata ]    | |  |
|  | +-----------------------+-------------------------------------------------+ |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
        |                      |                          |
        v                      v                          v
+------------------+  +--------------------+   +-----------------------+
|  Global Hotkeys  |  |  System Tray Icon  |   | Floating Control Bar  |
|  (Ctrl+Alt+A/R)  |  |  (AppIndicator3)   |   | (Timer, Pause, Stop)  |
+------------------+  +--------------------+   +-----------------------+
        |                      |                          |
        +----------------------+--------------------------+
                               |
                               v
+-----------------------------------------------------------------------------------+
|                           Core Capture & Media Engine                             |
|  +-----------------------+ +-----------------------+ +-------------------------+  |
|  | Screen Grabber        | | Video Encoder         | | Audio Mixer             |  |
|  | (GdkPixbuf / ximagesrc| | (NVENC / x264 faststart| | (PulseAudio / ALSA      |  |
|  |  Full & ROI Region)   | |  MP4 / WebM muxers)   | |  Mic + Desktop Monitor) |  |
|  +-----------------------+ +-----------------------+ +-------------------------+  |
|  | Dual-Mode Scheduler: Drift-Free Monotonic Target Loop & Instant Manual Trigger |  |
+-----------------------------------------------------------------------------------+
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Single-Window GUI Layout | Unified single-window dashboard without tabs or sub-page navigation | M3 | R1 |
| F2 | System Tray Integration | AppIndicator3/StatusIcon tray icon with context menu, status badges, background run | M2 | R1 |
| F3 | Global Hotkeys | System-wide hotkeys (Ctrl+Alt+A, Ctrl+Alt+R) via libX11 grabber | M2 | R1 |
| F4 | Floating Recording Bar | Borderless, topmost draggable overlay with live timer, pause/resume, and stop | M2 | R1 |
| F5 | Manual Capture Mode | Instant screenshot or recording trigger via hotkeys or UI buttons | M1 | R2 |
| F6 | Automatic Capture Mode | Dynamic interval textbox (validation 0.5s–3600s), drift-free recurring auto-capture | M1 | R2 |
| F7 | Cross-Platform Formats | Output screenshots in PNG/JPG and videos in MP4 (faststart) / WebM | M1 | R2 |
| F8 | Region & Fullscreen Capture | Full desktop or interactive rubberband ROI region capture | M1, M2 | R3 |
| F9 | Audio Recording & Mixing | PulseAudio/ALSA microphone and system desktop audio capture & synchronization | M1 | R3 |
| F10 | Hardware/System Encoding | NVIDIA NVENC / GStreamer / x264 low CPU hardware-optimized encoding | M1 | R3 |
| F11 | Pause / Resume Recording | Seamless video recording pause/resume with continuous container timeline | M1 | R3 |
| F12 | Embedded Media Manager | Integrated media panel with recent captures list, thumbnails, and file metadata | M3 | R4 |
| F13 | In-App Image Preview | Embedded image viewer with zoom/fit display inside the single window | M3 | R4 |
| F14 | In-App Video Playback | Embedded video player with frame-accurate seekbar, play/pause, and time counter | M3 | R4 |
| F15 | E2E Acceptance & Robustness | 100% pass of requirement-driven test suite & adversarial edge-case hardening | M4 | AC |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core Engine & Capture Backends | Screen grabber (PNG/JPG), video recorder (MP4/WebM, NVENC/x264, pause/resume), audio mixer (PulseAudio/ALSA), dual-mode scheduler | none | IN_PROGRESS |
| M2 | System Integration & Background Services | Global Hotkey Manager (libX11), System Tray Service (AppIndicator3), Floating Control Bar, Region Selector Overlay | M1 | PLANNED |
| M3 | Unified Single-Window GUI & Embedded Media Manager | Unified single-page GUI dashboard (no tabs), Embedded media manager (thumbnails, viewer, video playback), App entry point | M1, M2 | PLANNED |
| M4 | Final Milestone (E2E Test Pass & Coverage Hardening) | Phase 1: 100% pass of E2E test suite (Tiers 1-4). Phase 2: Adversarial coverage hardening (Tier 5) | M1, M2, M3 | PLANNED |

## Interface Contracts

### `src/engine/` ↔ `src/gui/` & `src/system/`
```python
class CaptureMode(Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"

class OutputFormat(Enum):
    PNG = "png"
    JPG = "jpg"
    MP4 = "mp4"
    WEBM = "webm"

class Region(NamedTuple):
    x: int
    y: int
    width: int
    height: int

class CaptureConfig:
    mode: CaptureMode
    interval: float # seconds (e.g. 5.0)
    region: Optional[Region] # None for fullscreen
    audio_enabled: bool
    audio_source: str # 'default', 'pulse', 'alsa', 'none'
    image_format: OutputFormat
    video_format: OutputFormat
    output_dir: str

class CaptureEngine:
    def capture_screenshot(self, config: Optional[CaptureConfig] = None) -> str:
        """Takes an immediate screenshot, writes to output_dir, returns filepath."""
    def start_recording(self, config: Optional[CaptureConfig] = None) -> None:
        """Starts video recording in background thread/pipeline."""
    def pause_recording(self) -> None:
        """Pauses current recording."""
    def resume_recording(self) -> None:
        """Resumes paused recording."""
    def stop_recording(self) -> str:
        """Stops recording, finalizes container, returns filepath."""
    def start_auto_mode(self, interval: float, callback: Callable[[str], None]) -> None:
        """Starts monotonic auto-capture loop with specified interval."""
    def stop_auto_mode(self) -> None:
        """Stops auto-capture loop cleanly."""
    def get_status(self) -> EngineStatus:
        """Returns current state: IDLE, RECORDING, PAUSED, AUTO_ACTIVE."""
```

### `src/system/` ↔ `src/gui/`
```python
class HotkeyManager:
    def register_hotkey(self, key_combo: str, callback: Callable[[], None]) -> bool: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...

class TrayService:
    def __init__(self, on_show_hide: Callable, on_mode_toggle: Callable, on_capture: Callable, on_record: Callable, on_quit: Callable): ...
    def set_recording_state(self, is_recording: bool) -> None: ...
    def update_icon(self, icon_name_or_pixbuf) -> None: ...

class FloatingBar:
    def show_bar(self, on_pause: Callable, on_stop: Callable) -> None: ...
    def update_timer(self, elapsed_seconds: float) -> None: ...
    def set_paused(self, is_paused: bool) -> None: ...
    def hide_bar(self) -> None: ...
```

### `src/media/` ↔ `src/gui/`
```python
class MediaItem(NamedTuple):
    filepath: str
    filename: str
    media_type: str # 'image' or 'video'
    filesize: int
    timestamp: float
    thumbnail_path: Optional[str]

class MediaManager:
    def scan_captures(self, output_dir: str) -> List[MediaItem]: ...
    def get_thumbnail(self, item: MediaItem) -> Any: ... # Cached thumbnail
```

## Code Layout
```
/home/user/program/video/
├── captures/                  # Default storage for recorded videos & screenshots
├── backend/                   # FastAPI camera owner used through 127.0.0.1:8000
│   ├── app.py                 # Status, capabilities, FPS and MJPEG endpoints
│   ├── camera.py              # CSI camera lifecycle and reconfiguration
│   ├── camera_capabilities.py # Libargus/IMX219 mode discovery
│   └── tools/                 # Sensor-mode enumerator source
├── config/
│   └── camera.yaml            # Camera service defaults
├── src/
│   ├── __init__.py
│   ├── main.py               # Main application entry point
│   ├── config.py             # Configuration defaults & validation
│   ├── engine/               # M1: Core Capture Engine
│   │   ├── __init__.py
│   │   ├── screenshot.py     # High-speed GdkPixbuf / X11 screen grabber
│   │   ├── recorder.py       # GStreamer / FFmpeg NVENC / x264 video recorder
│   │   ├── audio.py          # PulseAudio & ALSA audio capture / mixer
│   │   └── scheduler.py      # Monotonic drift-free auto-mode loop
│   ├── system/               # M2: System & Desktop Integration
│   │   ├── __init__.py
│   │   ├── hotkeys.py        # libX11 ctypes global key grabber
│   │   ├── tray.py           # AppIndicator3 / StatusIcon tray service
│   │   ├── floating_bar.py   # Draggable borderless topmost overlay bar
│   │   └── region_picker.py  # Interactive rubberband ROI selector
│   ├── media/                # M3: Media Preview & Management
│   │   ├── __init__.py
│   │   ├── manager.py        # Capture directory scanner & metadata indexer
│   │   ├── thumbnail.py      # Asynchronous thumbnail generator & cache
│   │   └── player.py         # In-app video playback controller
│   └── gui/                  # M3: Unified Single-Window UI
│       ├── __init__.py
│       ├── app.py            # Main application window & event wiring
│       ├── header.py         # Mode toggle, interval textbox, status badge
│       ├── controls.py       # Action buttons (Capture, Record, Region, Audio)
│       └── media_panel.py    # Embedded split-pane media gallery & player
├── tests/                    # E2E & Unit Test Track
│   ├── __init__.py
│   ├── harness/              # Test harness & headless runners
│   ├── tier1_features/       # Tier 1: Feature Coverage tests (>=5 per feature)
│   ├── tier2_boundaries/     # Tier 2: Boundary & Corner case tests
│   ├── tier3_combinations/   # Tier 3: Pairwise cross-feature combinations
│   ├── tier4_scenarios/      # Tier 4: Real-world application scenarios
│   └── tier5_adversarial/    # Tier 5: Adversarial hardening tests
├── PROJECT.md
├── TEST_INFRA.md
└── TEST_READY.md
```
