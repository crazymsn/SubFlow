"""Frozen entry: put Qt DLLs first, then start 语幕."""

from __future__ import annotations

import os
import sys


def _prepare_qt() -> None:
    if not getattr(sys, "frozen", False):
        return
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    meipass = getattr(sys, "_MEIPASS", exe_dir)
    roots = (meipass, os.path.join(exe_dir, "_internal"), exe_dir)
    seen: set[str] = set()
    for root in roots:
        for name in ("PySide6", "shiboken6"):
            path = os.path.join(root, name)
            if path in seen or not os.path.isdir(path):
                continue
            seen.add(path)
            os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
            add = getattr(os, "add_dll_directory", None)
            if add:
                try:
                    add(path)
                except OSError:
                    pass
    for root in roots:
        plugins = os.path.join(root, "PySide6", "plugins")
        platforms = os.path.join(plugins, "platforms")
        if os.path.isdir(platforms):
            os.environ["QT_PLUGIN_PATH"] = plugins
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platforms
            break


_prepare_qt()

from bilingual_sub.gui.app import main

if __name__ == "__main__":
    main()
