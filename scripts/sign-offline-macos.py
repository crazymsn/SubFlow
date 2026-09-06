"""Sign each native executable/extension in the offline payload before sealing .app."""
import subprocess
import sys
from pathlib import Path

MACHO = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe',
         b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}


def sign(root):
    if sys.platform != 'darwin':
        raise RuntimeError('Signing requires macOS')
    for path in sorted(root.rglob('*')):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                native = stream.read(4) in MACHO
            if native:
                subprocess.run(['codesign', '--force', '--sign', '-', str(path)], check=True)
                subprocess.run(['codesign', '--verify', str(path)], check=True)


if __name__ == '__main__':
    sign(Path(sys.argv[1]).resolve())
