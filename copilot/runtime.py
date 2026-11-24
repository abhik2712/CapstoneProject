"""Build a local copilot in demo or course-endpoint mode."""
import os
from pathlib import Path

from .handbook import HandbookSearch, course_clients
from .store import Store
from .telemetry import console_tracer
from .workflow import Copilot

DEFAULT_DB = Path("runtime/copilot.sqlite")


def build_copilot(path, mode="demo", telemetry=False):
    if mode == "demo":
        handbook, chat = HandbookSearch(), None
    elif mode == "live":
        handbook, chat = course_clients()
    else:
        raise ValueError("CAPSTONE_MODE must be demo or live.")
    return Copilot(Store(path), handbook, chat, console_tracer() if telemetry else None)


def settings():
    return {
        "path": Path(os.getenv("CAPSTONE_STATE_DB", str(DEFAULT_DB))),
        "mode": os.getenv("CAPSTONE_MODE", "demo"),
        "telemetry": os.getenv("CAPSTONE_OTEL_CONSOLE") == "1",
    }
