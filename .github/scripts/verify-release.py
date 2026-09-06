"""Validate a release recovery source and reuse only byte-identical uploaded assets."""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

PLATFORMS = ('Windows-x64', 'macOS-arm64', 'macOS-x64')


def api(path, *, method=None, pages=False):
    command = ['gh', 'api', path]
    if method:
        command += ['--method', method]
    if pages:
        command += ['--paginate', '--slurp']
    output = subprocess.check_output(command, text=True, encoding='utf-8', timeout=90)
    return json.loads(output) if output.strip() else None


def local_assets(root):
    files = sorted(root.glob('SubFlow-*.7z.*'))
    groups = {platform: [] for platform in PLATFORMS}
    checksums = []
    result = {}
    for path in files:
        match = re.fullmatch(r'SubFlow-(Windows-x64|macOS-arm64|macOS-x64)\.7z\.(\d{3})', path.name)
        if not match or not path.is_file() or not 0 < path.stat().st_size < 2 * 1024**3:
            raise ValueError(f'Invalid release volume: {path.name}')
        groups[match[1]].append(int(match[2]))
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result[path.name] = {'size': path.stat().st_size, 'digest': 'sha256:' + digest}
        checksums.append(f'{digest}  {path.name}\n')
    for platform, volumes in groups.items():
        if not volumes or volumes != list(range(1, len(volumes) + 1)):
            raise ValueError(f'Missing or noncontiguous volumes: {platform}')
    checksum_file = root / 'SHA256SUMS'
    checksum_file.write_text(''.join(checksums), encoding='utf-8', newline='\n')
    result['SHA256SUMS'] = {'size': checksum_file.stat().st_size,
                          'digest': 'sha256:' + hashlib.sha256(checksum_file.read_bytes()).hexdigest()}
    return result


def asset_plan(expected, release, *, complete=False):
    existing = {asset['name']: asset for asset in (release or {}).get('assets', [])}
    incomplete = []
    for name, fingerprint in expected.items():
        asset = existing.get(name)
        if asset is None:
            if complete:
                raise ValueError(f'Missing uploaded asset: {name}')
            continue
        if asset['state'] != 'uploaded':
            if complete or not release['draft']:
                raise ValueError(f'Incomplete uploaded asset: {name}')
            incomplete.append(asset['id'])
        elif any(asset.get(key) != value for key, value in fingerprint.items()):
            raise ValueError(f'Existing asset differs; refusing to overwrite: {name}')
    return incomplete


def validate_source(repo, run_id, tag):
    if not re.fullmatch(r'\d+', run_id):
        raise ValueError('Source run must be a numeric workflow run ID')
    run = api(f'repos/{repo}/actions/runs/{run_id}')
    commit = api(f'repos/{repo}/commits/{tag}')['sha']
    if run['head_sha'] != commit or run['path'] != '.github/workflows/release-clients.yml':
        raise ValueError('Source run must build the selected tag with the client release workflow')
    pages = api(f'repos/{repo}/actions/runs/{run_id}/jobs?per_page=100', pages=True)
    jobs = [job for page in pages for job in page['jobs']]
    for platform in PLATFORMS:
        matching = [job for job in jobs if job['name'].startswith('clients (') and f', {platform},' in job['name']]
        if len(matching) != 1 or matching[0]['conclusion'] != 'success':
            raise ValueError(f'Client acceptance has not passed: {platform}')
    if not any(job['name'] == 'linux-process-lifecycle' and job['conclusion'] == 'success' for job in jobs):
        raise ValueError('Linux lifecycle acceptance has not passed')
    package = api(f'repos/{repo}/contents/pyproject.toml?ref={commit}')
    version = tomllib.loads(base64.b64decode(package['content']).decode())['project']['version']
    if tag != 'v' + version:
        raise ValueError('Release tag and package version differ')
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
        output.write(f'sha={commit}\nversion={version}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('source', 'preflight', 'verify'))
    parser.add_argument('--tag', required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--assets', type=Path, default=Path('release-assets'))
    args = parser.parse_args()
    if not re.fullmatch(r'v\d+\.\d+\.\d+', args.tag):
        parser.error('Tag must use vMAJOR.MINOR.PATCH')
    repo = os.environ['GITHUB_REPOSITORY']
    if args.phase == 'source':
        validate_source(repo, args.run_id or '', args.tag)
        return
    expected = local_assets(args.assets)
    pages = api(f'repos/{repo}/releases?per_page=100', pages=True)
    release = next((release for page in pages for release in page if release['tag_name'] == args.tag), None)
    if args.phase == 'verify' and release is None:
        raise ValueError('Release has not been created')
    incomplete = asset_plan(expected, release, complete=args.phase == 'verify')
    # Validate every existing asset before removing only unfinished draft uploads.
    for asset_id in incomplete:
        api(f'repos/{repo}/releases/assets/{asset_id}', method='DELETE')
    if args.phase == 'preflight':
        published = bool(release and not release['draft'])
        if published:
            asset_plan(expected, release, complete=True)
        with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
            output.write(f'already_published={str(published).lower()}\n')
    print(f'{len(expected)} release assets verified ({args.phase})')


if __name__ == '__main__':
    main()
