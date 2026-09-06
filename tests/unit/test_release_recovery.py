import base64
import runpy
from pathlib import Path

import pytest


@pytest.fixture
def recovery():
    return runpy.run_path(str(Path(__file__).parents[2] / '.github/scripts/verify-release.py'))


def test_complete_volumes_generate_verifiable_checksums(recovery, tmp_path):
    import hashlib

    for platform in recovery['PLATFORMS']:
        (tmp_path / f'SubFlow-{platform}.7z.001').write_bytes(platform.encode())
    expected = recovery['local_assets'](tmp_path)
    assert len(expected) == 4
    for name, fingerprint in expected.items():
        assert fingerprint['digest'] == 'sha256:' + hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
    assert len((tmp_path / 'SHA256SUMS').read_text().splitlines()) == 3


@pytest.mark.parametrize('change', ['missing_platform', 'gap', 'empty', 'unknown_platform'])
def test_invalid_volume_sets_cannot_be_published(recovery, tmp_path, change):
    for platform in recovery['PLATFORMS']:
        (tmp_path / f'SubFlow-{platform}.7z.001').write_bytes(b'volume')
    target = tmp_path / 'SubFlow-Windows-x64.7z.001'
    if change == 'missing_platform':
        target.unlink()
    elif change == 'gap':
        target.rename(target.with_suffix('.002'))
    elif change == 'empty':
        target.write_bytes(b'')
    else:
        (tmp_path / 'SubFlow-unknown.7z.001').write_bytes(b'volume')
    with pytest.raises(ValueError):
        recovery['local_assets'](tmp_path)
    assert not (tmp_path / 'SHA256SUMS').exists()


def test_resume_keeps_identical_uploads_and_repairs_only_unfinished_draft_assets(recovery):
    expected = {'one': {'size': 10, 'digest': 'sha256:one'}, 'two': {'size': 20, 'digest': 'sha256:two'}}
    good = {'id': 1, 'name': 'one', 'state': 'uploaded', **expected['one']}
    partial = {'id': 2, 'name': 'two', 'state': 'starter', 'size': 0, 'digest': None}
    release = {'draft': True, 'assets': [good, partial]}
    assert recovery['asset_plan'](expected, release) == [2]
    with pytest.raises(ValueError, match='Incomplete'):
        recovery['asset_plan'](expected, release, complete=True)
    release['draft'] = False
    with pytest.raises(ValueError, match='Incomplete'):
        recovery['asset_plan'](expected, release)
    partial.update(state='uploaded', **expected['two'])
    assert recovery['asset_plan'](expected, release, complete=True) == []
    good['digest'] = 'sha256:changed'
    with pytest.raises(ValueError, match='refusing to overwrite'):
        recovery['asset_plan'](expected, release)


def test_missing_upload_cannot_pass_final_verification(recovery):
    with pytest.raises(ValueError, match='Missing uploaded asset'):
        recovery['asset_plan']({'one': {'size': 1, 'digest': 'sha256:x'}}, {'draft': True, 'assets': []}, complete=True)


@pytest.mark.parametrize('failure', [None, 'different_commit', 'failed_client', 'wrong_version'])
def test_source_must_be_the_accepted_build_of_the_exact_version(recovery, monkeypatch, tmp_path, failure):
    function = recovery['validate_source']
    jobs = [{'name': f'clients (os, {platform}, cpu)', 'conclusion': 'success'} for platform in recovery['PLATFORMS']]
    jobs.append({'name': 'linux-process-lifecycle', 'conclusion': 'success'})
    if failure == 'failed_client':
        jobs[0]['conclusion'] = 'failure'
    def fake_api(path, **kwargs):
        if '/jobs?' in path:
            return [{'jobs': jobs}]
        if '/actions/runs/' in path:
            return {'head_sha': 'different' if failure == 'different_commit' else 'commit',
                    'path': '.github/workflows/release-clients.yml'}
        if '/commits/' in path:
            return {'sha': 'commit'}
        version = '1.3.59' if failure == 'wrong_version' else '1.3.60'
        return {'content': base64.b64encode(f'[project]\nversion="{version}"\n'.encode()).decode()}
    monkeypatch.setitem(function.__globals__, 'api', fake_api)
    output = tmp_path / 'outputs'
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    if failure:
        with pytest.raises(ValueError):
            function('owner/repo', '123', 'v1.3.60')
        assert not output.exists()
    else:
        function('owner/repo', '123', 'v1.3.60')
        assert output.read_text() == 'sha=commit\nversion=1.3.60\n'
