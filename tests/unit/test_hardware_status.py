import pytest

from bilingual_sub.gui import hardware


@pytest.mark.parametrize('full,short', [
    ('NVIDIA GeForce RTX 3060 Laptop GPU', 'RTX 3060 Laptop'),
    ('NVIDIA GeForce RTX 4070 Ti SUPER', 'RTX 4070 Ti SUPER'),
    ('AMD Radeon RX 7800 XT', 'RX 7800 XT'),
    ('Intel(R) UHD Graphics 630', 'UHD Graphics 630'),
    ('Apple M1', 'M1'), ('Apple M4 Pro', 'M4 Pro'), ('Apple M3 Max', 'M3 Max'),
    ('NVIDIA Tesla T4\nNVIDIA RTX A5000', 'T4\nRTX A5000'),
])
def test_short_name_preserves_model_variants(full, short):
    assert hardware.short_device_name(full) == short


@pytest.mark.parametrize('chip,machine', [('Apple M1', 'arm64'), ('Apple M4 Pro', 'arm64'), ('Apple M2', 'x86_64')])
def test_apple_chip_name_is_reported_even_under_rosetta(monkeypatch, chip, machine):
    monkeypatch.setattr(hardware.sys, 'platform', 'darwin')
    monkeypatch.setattr(hardware.platform, 'machine', lambda: machine)
    monkeypatch.setattr(hardware, 'apple_chip_name', lambda: chip)
    assert hardware.detect_hardware() == ('gpu_apple', chip)


def test_windows_reports_real_cuda_names_without_using_forced_cpu_setting(monkeypatch):
    monkeypatch.setattr(hardware.sys, 'platform', 'win32')
    monkeypatch.setenv('SUBFLOW_TORCH_BACKEND', 'cpu')
    monkeypatch.setattr(hardware, 'cuda_names', lambda: ['NVIDIA RTX 3060', 'NVIDIA RTX 4090'])
    assert hardware.detect_hardware() == ('gpu_cuda', 'NVIDIA RTX 3060\nNVIDIA RTX 4090')


def test_detected_non_cuda_display_is_not_mislabeled_as_supported_gpu(monkeypatch):
    monkeypatch.setattr(hardware.sys, 'platform', 'win32')
    monkeypatch.setattr(hardware, 'cuda_names', lambda: [])
    monkeypatch.setattr(hardware, 'windows_display_names', lambda: ['AMD Radeon RX 7800 XT'])
    assert hardware.detect_hardware() == ('gpu_detected_cpu', 'AMD Radeon RX 7800 XT')
    monkeypatch.setattr(hardware, 'windows_display_names', lambda: [])
    assert hardware.detect_hardware() == ('gpu_cpu', '')


def test_apple_query_failure_does_not_invent_a_chip_model(monkeypatch):
    monkeypatch.setattr(hardware.sys, 'platform', 'darwin')
    monkeypatch.setattr(hardware.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(hardware, 'apple_chip_name', lambda: '')
    assert hardware.detect_hardware() == ('gpu_apple', '')
