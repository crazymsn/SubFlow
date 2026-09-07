"""Verify a Mac release has only relocatable links within its application."""
import sys
from pathlib import Path


def check_links(app: Path) -> int:
    app = app.resolve(strict=True)
    count = 0
    for path in app.rglob('*'):
        if not path.is_symlink():
            continue
        if path.readlink().is_absolute() or not path.resolve(strict=True).is_relative_to(app):
            raise ValueError(f'Non-portable application link: {path}')
        count += 1
    return count


if __name__ == '__main__':
    print(f'Validated {check_links(Path(sys.argv[1]))} internal application links')
