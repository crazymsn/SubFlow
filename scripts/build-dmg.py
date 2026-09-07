"""Build and verify a drag-to-install DMG containing one complete native Mac app."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import runpy
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
check_links = runpy.run_path(str(ROOT/'scripts/check-macos-links.py'))['check_links']


def macho_arches(path: Path) -> set[int]:
    with path.open('rb') as stream:
        magic = stream.read(4)
        if magic in (b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe'):
            return {struct.unpack('<I', stream.read(4))[0]}
        if magic in (b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf'):
            return {struct.unpack('>I', stream.read(4))[0]}
        fat = {b'\xca\xfe\xba\xbe': ('>', 20), b'\xbe\xba\xfe\xca': ('<', 20),
               b'\xca\xfe\xba\xbf': ('>', 32), b'\xbf\xba\xfe\xca': ('<', 32)}
        if magic not in fat or path.suffix == '.class':
            return set()
        endian, size = fat[magic]
        count = struct.unpack(endian+'I', stream.read(4))[0]
        if not 0 < count <= 32:
            raise ValueError(f'Invalid universal binary: {path}')
        return {struct.unpack(endian+'I', stream.read(size)[:4])[0] for _ in range(count)}


def validate_app(app: Path, arch: str) -> dict:
    info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
    offline = app/'Contents/Resources/offline'
    manifest = json.loads((offline/'bundle.json').read_text())
    if manifest['machine'] != arch or manifest['version'] != info['CFBundleShortVersionString']:
        raise ValueError('App and offline runtime architecture/version do not match')
    backend = 'mps' if arch == 'arm64' else 'cpu'
    binaries = [app/'Contents/MacOS/SubFlow']
    binaries += [app/'Contents/Resources'/name for name in ('ffmpeg', 'ffprobe', 'uv')]
    for kind in ('qwentts', 'gptsovits', 'asr', 'whisperx'):
        record = manifest['runtimes'][kind]
        if record['backend'] != backend:
            raise ValueError(f'Unexpected {kind} backend for {arch}')
        binary = (offline/record['python']).resolve(strict=True)
        if not binary.is_relative_to(app.resolve()):
            raise ValueError('An interpreter points outside the application')
        binaries.append(binary)
    for binary in binaries:
        subprocess.run(['lipo', str(binary), '-verify_arch', arch], check=True)
    links = check_links(app)
    expected = 0x0100000C if arch == 'arm64' else 0x01000007
    native_count = 0
    for path in app.rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        arches = macho_arches(path)
        if arches:
            native_count += 1
            if expected not in arches:
                raise ValueError(f'Native dependency has the wrong architecture: {path}')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    return {'version': info['CFBundleShortVersionString'], 'arch': arch,
            'minimum_macos': info['LSMinimumSystemVersion'], 'links': links,
            'native_binaries_checked': native_count, 'backend': backend}


def background(path: Path, label: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    scale = 2
    canvas = Image.new('RGB', (720*scale, 470*scale), '#f4f5f7')
    draw = ImageDraw.Draw(canvas)
    font_path = '/System/Library/Fonts/PingFang.ttc'

    def text(x, y, value, size, color='#20232a'):
        font = ImageFont.truetype(font_path, size*scale)
        draw.text((x*scale, y*scale), value, font=font, fill=color)

    text(44, 26, 'SubFlow', 36)
    text(44, 84, '将 SubFlow 拖入 Applications', 20, '#555b66')
    text(484, 42, label, 15, '#555b66')
    draw.line((326*scale, 200*scale, 394*scale, 200*scale), fill='#9299a4', width=3*scale)
    draw.line((382*scale, 188*scale, 394*scale, 200*scale, 382*scale, 212*scale),
              fill='#9299a4', width=3*scale, joint='curve')
    text(160, 280, '复制完成后，从“应用程序”启动', 19, '#555b66')
    text(42, 426, '安装及 Cookies 导入步骤 →', 14, '#666e7a')
    canvas.save(path)


def build(app: Path, output: Path, arch: str, report: Path, *, verify_existing: bool = False) -> None:
    import dmgbuild

    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report.mkdir(parents=True, exist_ok=True)
    before = validate_app(app, arch)
    label = 'Apple M · arm64' if arch == 'arm64' else 'Intel · x86_64'
    artwork = report/'installer-background@2x.png'
    background(artwork, label)
    # dmgbuild discovers @2x at the companion filename.
    from PIL import Image
    Image.open(artwork).resize((720, 470), Image.Resampling.LANCZOS).save(report/'installer-background.png')
    pending = output.with_name(output.stem+'.unverified.dmg')
    if verify_existing and not pending.is_file():
        raise FileNotFoundError(pending)
    if not verify_existing and pending.exists():
        raise FileExistsError(pending)
    guide_name = '安装与Cookies说明.md'

    def progress(event):
        if event['type'] == 'operation::start' or event['type'] == 'command::start':
            print(event.get('operation', event.get('command', '')), flush=True)

    def validate_staged_copy(mount, options):
        staged = Path(mount)/'SubFlow.app'
        check_links(staged)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(staged)], check=True)

    if not verify_existing:
        dmgbuild.build_dmg(str(pending), f'SubFlow {before["version"]} {label}', settings={
            'format': 'ULFO', 'filesystem': 'HFS+',
            'files': [(str(app), 'SubFlow.app'), (str(ROOT/'docs/mac-install-cookies.md'), guide_name)],
            'symlinks': {'Applications': '/Applications'},
            'icon_locations': {'SubFlow.app': (180, 200), 'Applications': (540, 200), guide_name: (535, 380)},
            'icon_size': 100, 'text_size': 13, 'window_rect': ((160, 120), (720, 470)),
            'background': str(report/'installer-background.png'),
            # SetFile -a E would add FinderInfo to the sealed .app and invalidate it.
            'icon': str(ROOT/'build/SubFlow.icns'),
            'create_hook': validate_staged_copy,
            'default_view': 'icon-view', 'show_sidebar': False,
        }, callback=progress)
    subprocess.run(['hdiutil', 'verify', str(pending)], check=True)
    attached = plistlib.loads(subprocess.check_output([
        'hdiutil', 'attach', '-readonly', '-nobrowse', '-plist', str(pending)]))
    mount = Path(next(item['mount-point'] for item in attached['system-entities'] if 'mount-point' in item))
    try:
        after = validate_app(mount/'SubFlow.app', arch)
        if after != before:
            raise ValueError('Mounted application does not match the input application')
        if (mount/'Applications').readlink() != Path('/Applications'):
            raise ValueError('Install shortcut is missing')
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1')
        for name in ('SUBFLOW_OFFLINE_DIR', 'PYTHONPATH', 'PYTHONHOME'):
            env.pop(name, None)
        smoke_path = (report/'mounted-smoke.json').resolve()
        with (report/'mounted-smoke.log').open('w') as log:
            subprocess.run([str(mount/'SubFlow.app/Contents/MacOS/SubFlow'), '--self-test', str(smoke_path)],
                           # XProtect may scan the complete offline models on first launch.
                           cwd=mount, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
        smoke = json.loads(smoke_path.read_text())
        if not smoke['ok']:
            raise ValueError('Mounted application self-test failed')
    finally:
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True)
    pending.rename(output)
    with output.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    result = {'ok': True, **after, 'file': str(output), 'bytes': output.stat().st_size,
              'sha256': digest, 'mounted_readonly_self_test': True, 'notarized': False}
    (report/'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--arch', choices=('arm64', 'x86_64'), required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--verify-existing', action='store_true',
                        help='Resume all validation of an existing .unverified.dmg without recompressing it')
    args = parser.parse_args()
    build(args.app.resolve(), args.output.resolve(), args.arch, args.report.resolve(),
          verify_existing=args.verify_existing)
