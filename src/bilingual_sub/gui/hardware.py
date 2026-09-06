"""Read device names without loading Torch, models, or changing GPU selection."""
import ctypes
import platform
import re
import subprocess
import sys

from bilingual_sub.adapters.procwin import hidden_run_kwargs


def short_device_name(name):
    """Short display labels; retain model numbers and Pro/Max/Ti/Laptop variants."""
    names = []
    for line in name.splitlines():
        value = re.sub(r'\((?:R|TM)\)|[®™]', '', line, flags=re.IGNORECASE).strip()
        value = re.sub(r'^(?:NVIDIA|AMD|Intel|Apple)\s+', '', value, flags=re.IGNORECASE)
        value = re.sub(r'^(?:GeForce|Tesla)\s+', '', value, flags=re.IGNORECASE)
        value = re.sub(r'^Radeon\s+(?=RX\b)', '', value, flags=re.IGNORECASE)
        value = re.sub(r'\s+GPU$', '', value, flags=re.IGNORECASE)
        value = ' '.join(value.split())
        if value:
            names.append(value)
    return '\n'.join(names)


def cuda_names():
    try:
        driver = (ctypes.WinDLL('nvcuda.dll', winmode=0x800) if sys.platform == 'win32'
                  else ctypes.CDLL('libcuda.so.1'))
        count = ctypes.c_int()
        if driver.cuInit(0) != 0 or driver.cuDeviceGetCount(ctypes.byref(count)) != 0:
            return []
        names = []
        for index in range(min(count.value, 32)):
            device, name = ctypes.c_int(), ctypes.create_string_buffer(256)
            if driver.cuDeviceGet(ctypes.byref(device), index) == 0 and driver.cuDeviceGetName(name, len(name), device) == 0:
                value = name.value.decode('utf-8', errors='replace').strip()
                if value and value not in names:
                    names.append(value)
        return names
    except (OSError, AttributeError):
        return []


def windows_display_names():
    class DisplayDevice(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_uint32), ('device_name', ctypes.c_wchar * 32),
                    ('description', ctypes.c_wchar * 128), ('flags', ctypes.c_uint32),
                    ('device_id', ctypes.c_wchar * 128), ('device_key', ctypes.c_wchar * 128)]
    try:
        user32 = ctypes.WinDLL('user32.dll', winmode=0x800)
        names = []
        for index in range(32):
            device = DisplayDevice()
            device.cb = ctypes.sizeof(device)
            if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
                break
            if device.device_id.startswith('PCI\\') and not device.flags & 8 and device.description not in names:
                names.append(device.description)
        return names
    except (OSError, AttributeError):
        return []


def apple_chip_name():
    try:
        result = subprocess.run(['/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string'],
            capture_output=True, text=True, timeout=3, check=True, **hidden_run_kwargs())
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def detect_hardware():
    if sys.platform == 'darwin':
        chip = apple_chip_name()
        if chip.startswith('Apple M') or platform.machine().lower() in {'arm64', 'aarch64'}:
            return 'gpu_apple', chip if chip.startswith('Apple M') else ''
        return 'gpu_cpu', ''
    if sys.platform in {'win32', 'linux'}:
        names = cuda_names()
        if names:
            return 'gpu_cuda', '\n'.join(names)
        if sys.platform == 'win32':
            names = windows_display_names()
            if names:
                return 'gpu_detected_cpu', '\n'.join(names)
    return 'gpu_cpu', ''
