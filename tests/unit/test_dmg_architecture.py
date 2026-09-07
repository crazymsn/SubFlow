import runpy
import struct
from pathlib import Path

import pytest

read_arches = runpy.run_path(str(Path(__file__).parents[2]/'scripts/build-dmg.py'))['macho_arches']


@pytest.mark.parametrize('cpu', [0x01000007, 0x0100000C])
def test_reads_actual_native_architecture_header(tmp_path, cpu):
    binary = tmp_path/'native.dylib'
    binary.write_bytes(b'\xcf\xfa\xed\xfe'+struct.pack('<I', cpu)+bytes(24))
    assert read_arches(binary) == {cpu}


def test_universal_binary_accepts_both_architectures(tmp_path):
    binary = tmp_path/'universal'
    binary.write_bytes(b'\xca\xfe\xba\xbe'+struct.pack('>I', 2)
                       +struct.pack('>5I', 0x01000007, 3, 4096, 100, 12)
                       +struct.pack('>5I', 0x0100000C, 0, 8192, 100, 12))
    assert read_arches(binary) == {0x01000007, 0x0100000C}


def test_non_native_resource_is_ignored(tmp_path):
    resource = tmp_path/'weights.bin'
    resource.write_bytes(b'not an executable')
    assert read_arches(resource) == set()
