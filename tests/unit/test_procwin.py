import subprocess
import sys

from bilingual_sub.adapters.procwin import gui_python, hidden_run_kwargs, is_hidden_kwargs


def test_hidden_kwargs_hide_console_on_windows():
    kwargs = hidden_run_kwargs()
    if sys.platform == "win32":
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
        assert is_hidden_kwargs(kwargs)
    else:
        assert kwargs == {}


def test_gui_python_keeps_console_python(tmp_path):
    py = tmp_path / "python.exe"
    pyw = tmp_path / "pythonw.exe"
    py.write_text("", encoding="utf-8")
    pyw.write_text("", encoding="utf-8")
    assert gui_python(py) == py
