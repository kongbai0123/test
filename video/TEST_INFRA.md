# E2E Test Infra: Screen Capture & Recording GUI Application

## Test Philosophy
- Opaque-box, requirement-driven testing directly derived from `ORIGINAL_REQUEST.md`.
- No dependency on internal implementation hacks; tests exercise the application through public interfaces, CLI options, simulated X11 GUI events, and filesystem/codec verification.
- Progressive verification: Tiers 1-4 execute cleanly in the Linux sandbox environment using Python's standard `unittest` and headless X11 `$DISPLAY=:0` / PyGObject / Tkinter / GStreamer / OpenCV verification.

## Feature Inventory & Test Mapping
| # | Feature | Requirement | Tier 1 (Coverage) | Tier 2 (Boundaries) | Tier 3 (Interactions) | Tier 4 (Workloads) |
|---|---------|-------------|:-----------------:|:-------------------:|:---------------------:|:------------------:|
| F1 | Single-Window GUI Layout | R1 | 5 tests | 5 tests | Pairwise | ✓ |
| F2 | System Tray Integration | R1 | 5 tests | 5 tests | Pairwise | ✓ |
| F3 | Global Hotkeys | R1 | 5 tests | 5 tests | Pairwise | ✓ |
| F4 | Floating Recording Bar | R1 | 5 tests | 5 tests | Pairwise | ✓ |
| F5 | Manual Capture Mode | R2 | 5 tests | 5 tests | Pairwise | ✓ |
| F6 | Automatic Capture Mode | R2 | 5 tests | 5 tests | Pairwise | ✓ |
| F7 | Cross-Platform Formats (PNG/JPG/MP4/WebM) | R2 | 5 tests | 5 tests | Pairwise | ✓ |
| F8 | Region & Fullscreen Capture | R3 | 5 tests | 5 tests | Pairwise | ✓ |
| F9 | Audio Recording & Mixing | R3 | 5 tests | 5 tests | Pairwise | ✓ |
| F10 | Hardware / System Encoding (NVENC/x264) | R3 | 5 tests | 5 tests | Pairwise | ✓ |
| F11 | Pause / Resume Recording | R3 | 5 tests | 5 tests | Pairwise | ✓ |
| F12 | Embedded Media Manager | R4 | 5 tests | 5 tests | Pairwise | ✓ |
| F13 | In-App Image Preview | R4 | 5 tests | 5 tests | Pairwise | ✓ |
| F14 | In-App Video Playback | R4 | 5 tests | 5 tests | Pairwise | ✓ |

## Test Architecture
- **Runner**: Python `unittest` runner (`python3 -m unittest discover tests -v` or `python3 run_tests.py`).
- **Headless GUI Simulation**: Headless initialization via `$DISPLAY=:0`, widget event generation, and state introspection.
- **Media Output Verification**:
  - Image verification: PIL / GdkPixbuf / OpenCV reading, resolution check, header check, non-blank pixel verification.
  - Video verification: OpenCV `cv2.VideoCapture` / GStreamer probe, FPS, duration, resolution, frame-seeking, faststart moov atom inspection.
  - Audio verification: Audio track stream presence and non-silent stream verification.

## Coverage Goals
- **Tier 1 (Feature Coverage)**: ≥70 test cases (≥5 per feature across F1–F14).
- **Tier 2 (Boundary & Corner Cases)**: ≥70 test cases (≥5 per feature: zero/negative intervals, malformed interval strings, 1x1 region, full screen, rapid start/stop bursts, special characters in output path, missing audio fallbacks).
- **Tier 3 (Cross-Feature Combinations)**: ≥15 pairwise interaction tests (e.g., Auto-mode + Region + Audio; Hotkey manual capture while Auto-mode running; Minimize to tray while recording with floating bar active; Media deletion and instant preview update).
- **Tier 4 (Real-World Scenarios)**: ≥8 application-level scenario tests (e.g., continuous 10s auto-capture session, 3-video recording series with pause/resume, full media gallery lifecycle, hotkey burst screenshot session).
- **Total Minimum Target**: ≥163 automated tests.
