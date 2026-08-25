"""
src/main.py
Main entry point for Screen Capture & Recording Application on Ubuntu Linux (NVIDIA environment).
"""

import logging
import os
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.gui.app import MainWindow


def main():
    """Main application initialization and Gtk event loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("Main")
    logger.info("Initializing Screen Capture & Recorder...")

    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "captures"))

    app = MainWindow(output_dir=output_dir)
    app.show_all()

    logger.info("Entering Gtk main loop...")
    Gtk.main()


if __name__ == "__main__":
    main()
