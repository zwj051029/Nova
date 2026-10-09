"""Application branding shared by source and frozen builds."""
from pathlib import Path
import sys

from PySide6.QtGui import QIcon


def application_icon() -> QIcon:
    return QIcon(str(Path(__file__).resolve().parent / "assets" / "nova.ico"))


def configure_windows_app_id() -> None:
    """Keep source launches associated with Nova instead of the Python launcher."""
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Nova.SerialPID")
        except (AttributeError, OSError):
            # Branding must never prevent startup on an unsupported shell.
            pass
