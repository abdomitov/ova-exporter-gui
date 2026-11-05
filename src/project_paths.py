"""Locate shared resources in a source checkout or a frozen application."""
from pathlib import Path
import sys

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
