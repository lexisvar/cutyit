import sys
import os
import ctypes
import ctypes.util

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon


def _set_macos_dock_icon(png_path: str) -> None:
    """Set the macOS Dock icon via the Objective-C runtime (no pyobjc required)."""
    try:
        libobjc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))  # type: ignore[arg-type]

        libobjc.objc_getClass.restype = ctypes.c_void_p
        libobjc.sel_registerName.restype = ctypes.c_void_p

        def msg(receiver, sel, *args):
            libobjc.objc_msgSend.restype = ctypes.c_void_p
            libobjc.objc_msgSend.argtypes = (
                [ctypes.c_void_p, ctypes.c_void_p]
                + [type(a) for a in args]
            )
            return libobjc.objc_msgSend(receiver, sel, *args)

        # NSString from UTF-8 path
        NSString = libobjc.objc_getClass(b"NSString")
        sel_swu = libobjc.sel_registerName(b"stringWithUTF8String:")
        libobjc.objc_msgSend.restype = ctypes.c_void_p
        libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
        path_nsstr = libobjc.objc_msgSend(NSString, sel_swu, png_path.encode())

        # NSImage alloc + initWithContentsOfFile:
        NSImage = libobjc.objc_getClass(b"NSImage")
        sel_alloc = libobjc.sel_registerName(b"alloc")
        sel_init  = libobjc.sel_registerName(b"initWithContentsOfFile:")
        ns_img = msg(NSImage, sel_alloc)
        libobjc.objc_msgSend.restype = ctypes.c_void_p
        libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        ns_img = libobjc.objc_msgSend(ns_img, sel_init, path_nsstr)

        # NSApplication.sharedApplication.setApplicationIconImage:
        NSApp = libobjc.objc_getClass(b"NSApplication")
        sel_shared   = libobjc.sel_registerName(b"sharedApplication")
        sel_set_icon = libobjc.sel_registerName(b"setApplicationIconImage:")
        ns_app = msg(NSApp, sel_shared)
        libobjc.objc_msgSend.restype = ctypes.c_void_p
        libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        libobjc.objc_msgSend(ns_app, sel_set_icon, ns_img)
    except Exception:
        pass  # non-critical — silently skip on any error


def main() -> None:
    # High-DPI scaling (Qt6 handles this automatically, but be explicit)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Cutyit")
    app.setApplicationDisplayName("Cutyit")
    app.setStyle("Fusion")

    # App icon
    _base = os.path.dirname(os.path.abspath(__file__))
    _icns = os.path.join(_base, "assets", "icon.icns")
    _png  = os.path.join(_base, "assets", "icon.png")
    _icon_path = _icns if os.path.exists(_icns) else _png
    if os.path.exists(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    # macOS: set the Dock icon via the Obj-C runtime (no extra packages needed)
    if sys.platform == "darwin" and os.path.exists(_png):
        _set_macos_dock_icon(_png)

    # Check for FFmpeg before opening the main window
    try:
        from src.core.video_processor import check_ffmpeg
        check_ffmpeg()
    except RuntimeError as exc:
        QMessageBox.critical(None, "Missing dependency", str(exc))
        sys.exit(1)

    from src.ui.main_window import MainWindow
    win = MainWindow()
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
