"""
src/engine/audio.py
PulseAudio and ALSA device discovery, desktop audio monitor loopback, and GStreamer audio capture integration.
Fallback hierarchy: PulseAudio (pulsesrc) -> ALSA (alsasrc) -> Silence (audiotestsrc).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("CaptureEngine.Audio")


@dataclass
class AudioDevice:
    """Represents a discovered audio input or monitor loopback device."""
    id: str           # e.g., 'default', 'hw:1,0', 'pulse:alsa_output.pci.monitor', 'silence'
    name: str         # e.g., 'Default System Input', 'Built-in Microphone'
    description: str  # Detailed description
    device_type: str  # 'input', 'monitor', 'alsa', 'virtual'
    is_default: bool
    is_monitor: bool


class AudioDiscovery:
    """Discovers audio sources from PulseAudio, ALSA, and virtual synthetic devices."""

    @staticmethod
    def list_pulse_sources() -> List[AudioDevice]:
        """Discovers PulseAudio input sources and monitor loopback sinks via pactl."""
        devices: List[AudioDevice] = []
        try:
            res = subprocess.run(
                ["pactl", "list", "sources"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout:
                current: dict = {}
                for line in res.stdout.splitlines():
                    sline = line.strip()
                    if sline.startswith("Source #"):
                        if current and "Name" in current:
                            devices.append(AudioDiscovery._parse_pulse_source(current))
                        current = {"id": sline.split("#")[1].strip()}
                    elif ": " in sline:
                        k, v = sline.split(": ", 1)
                        current[k.strip()] = v.strip()
                if current and "Name" in current:
                    devices.append(AudioDiscovery._parse_pulse_source(current))
        except Exception as e:
            logger.debug(f"PulseAudio source discovery error: {e}")
        return devices

    @staticmethod
    def _parse_pulse_source(d: dict) -> AudioDevice:
        raw_name = d.get("Name", "")
        desc = d.get("Description", raw_name)
        is_monitor = ".monitor" in raw_name
        dev_type = "monitor" if is_monitor else "input"
        return AudioDevice(
            id=f"pulse:{raw_name}",
            name=desc,
            description=f"PulseAudio {'Monitor Loopback' if is_monitor else 'Input Source'}: {raw_name}",
            device_type=dev_type,
            is_default=False,
            is_monitor=is_monitor,
        )

    @staticmethod
    def list_alsa_sources() -> List[AudioDevice]:
        """Discovers ALSA capture devices via /proc/asound/cards and /proc/asound/pcm."""
        devices: List[AudioDevice] = []
        cards_path = "/proc/asound/cards"
        pcm_path = "/proc/asound/pcm"
        cards = {}

        if os.path.exists(cards_path):
            try:
                with open(cards_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                for match in re.finditer(r"^\s*(\d+)\s+\[([^\]]+)\]:\s+(.+)$", content, re.MULTILINE):
                    c_id, c_short, c_desc = match.groups()
                    cards[int(c_id)] = {"short": c_short.strip(), "desc": c_desc.strip()}
            except Exception as e:
                logger.debug(f"ALSA cards read error: {e}")

        if os.path.exists(pcm_path):
            try:
                with open(pcm_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                for line in content.splitlines():
                    parts = line.strip().split(":")
                    if len(parts) >= 4 and "capture" in ":".join(parts[2:]):
                        m = re.match(r"(\d+)-(\d+)", parts[0].strip())
                        if m:
                            c_num, d_num = int(m.group(1)), int(m.group(2))
                            card_info = cards.get(c_num, {})
                            dev_name = parts[1].strip()
                            card_desc = card_info.get("desc", f"Card {c_num}")
                            devices.append(
                                AudioDevice(
                                    id=f"hw:{c_num},{d_num}",
                                    name=f"{card_desc} ({dev_name})",
                                    description=f"ALSA Capture Card {c_num} Device {d_num}",
                                    device_type="alsa",
                                    is_default=False,
                                    is_monitor=False,
                                )
                            )
            except Exception as e:
                logger.debug(f"ALSA pcm read error: {e}")

        return devices

    @classmethod
    def get_all_devices(cls) -> List[AudioDevice]:
        """Returns catalog of all available audio devices including default and virtual options."""
        devices: List[AudioDevice] = []

        # 1. Default system audio device
        devices.append(
            AudioDevice(
                id="default",
                name="Default Audio Source",
                description="System default recording device (PulseAudio / ALSA)",
                device_type="input",
                is_default=True,
                is_monitor=False,
            )
        )

        # 2. PulseAudio devices
        pulse_devs = cls.list_pulse_sources()
        devices.extend(pulse_devs)

        # 3. ALSA devices
        alsa_devs = cls.list_alsa_sources()
        devices.extend(alsa_devs)

        # 4. Virtual silence device
        devices.append(
            AudioDevice(
                id="silence",
                name="Silent Audio Track",
                description="Synthetic silent audio generator (audiotestsrc)",
                device_type="virtual",
                is_default=False,
                is_monitor=False,
            )
        )

        return devices

    @classmethod
    def get_default_device(cls) -> AudioDevice:
        """Returns the primary default audio device."""
        all_devs = cls.get_all_devices()
        for dev in all_devs:
            if dev.is_default:
                return dev
        return all_devs[0]

    @staticmethod
    def probe_gstreamer_source(source_pipeline_str: str) -> bool:
        """Tests if a given GStreamer audio source pipeline can transition to READY."""
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
            Gst.init(None)

            pipe = Gst.parse_launch(f"{source_pipeline_str} ! fakesink")
            ret = pipe.set_state(Gst.State.READY)
            pipe.set_state(Gst.State.NULL)
            return ret != Gst.StateChangeReturn.FAILURE
        except Exception:
            return False

    @classmethod
    def resolve_audio_source(cls, requested_source: str = "default") -> str:
        """
        Resolves the requested audio source string to a functional GStreamer source string,
        following the fallback hierarchy: Pulse -> ALSA -> Silence.
        """
        req = requested_source.strip().lower() if requested_source else "default"

        if req == "silence" or req == "none":
            return "audiotestsrc is-live=true wave=silence"

        if req.startswith("pulse:") and len(req) > 6:
            pulse_dev = req[6:]
            candidate = f'pulsesrc device="{pulse_dev}"'
            if cls.probe_gstreamer_source(candidate):
                return candidate

        if req.startswith("hw:"):
            candidate = f'alsasrc device="{req}"'
            if cls.probe_gstreamer_source(candidate):
                return candidate

        # Handle 'default' or custom:
        # Step 1: Probe pulsesrc
        if cls.probe_gstreamer_source("pulsesrc"):
            return "pulsesrc"

        # Step 2: Probe alsasrc default
        if cls.probe_gstreamer_source("alsasrc"):
            return "alsasrc"

        # Step 3: Probe any discovered ALSA hw device
        for alsa_dev in cls.list_alsa_sources():
            candidate = f'alsasrc device="{alsa_dev.id}"'
            if cls.probe_gstreamer_source(candidate):
                return candidate

        # Step 4: Fallback to synthetic silence
        return "audiotestsrc is-live=true wave=silence"


class AudioMixer:
    """Builds GStreamer audio capture pipeline branches for container muxing."""

    @staticmethod
    def build_audio_branch(
        device_id: str = "default",
        format_type: str = "mp4",
        bitrate: int = 128000,
    ) -> str:
        """
        Constructs a GStreamer audio capture and encoding branch ending in queue ! mux.audio_0.

        Args:
            device_id: Audio device ID ('default', 'pulse:...', 'hw:X,Y', 'silence').
            format_type: Output container format ('mp4' or 'webm').
            bitrate: Audio encoder bitrate in bits per second (e.g. 128000).

        Returns:
            GStreamer pipeline segment string.
        """
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)

        src_str = AudioDiscovery.resolve_audio_source(device_id)

        if format_type.lower() == "mp4":
            # Prefer voaacenc or avenc_aac
            if Gst.ElementFactory.find("voaacenc") is not None:
                encoder_str = f"voaacenc bitrate={bitrate} ! aacparse"
            elif Gst.ElementFactory.find("avenc_aac") is not None:
                encoder_str = f"avenc_aac bitrate={bitrate} ! aacparse"
            else:
                encoder_str = "audioconvert ! lamemp3enc ! mpegaudioparse"

            return (
                f"{src_str} ! audio/x-raw,rate=44100,channels=2 ! "
                f"audioconvert ! audioresample ! "
                f"{encoder_str} ! queue max-size-buffers=100 max-size-time=2000000000 ! mux.audio_0"
            )
        else:  # WebM
            # Prefer opusenc or vorbisenc
            if Gst.ElementFactory.find("opusenc") is not None:
                encoder_str = f"opusenc bitrate={bitrate}"
            elif Gst.ElementFactory.find("vorbisenc") is not None:
                encoder_str = "vorbisenc"
            else:
                encoder_str = "audioconvert ! opusenc"

            return (
                f"{src_str} ! audio/x-raw,rate=44100,channels=2 ! "
                f"audioconvert ! audioresample ! "
                f"{encoder_str} ! queue max-size-buffers=100 max-size-time=2000000000 ! mux.audio_0"
            )
