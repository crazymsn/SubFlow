import runpy
from pathlib import Path

import pytest

check_links = runpy.run_path(str(Path(__file__).parents[2] / 'scripts/check-macos-links.py'))['check_links']


def test_framework_parent_links_are_relocatable(tmp_path):
    app = tmp_path / 'SubFlow.app'
    resources = app / 'Contents/Resources'
    frameworks = app / 'Contents/Frameworks'
    resources.mkdir(parents=True)
    frameworks.mkdir()
    (frameworks / 'ffmpeg').write_text('binary')
    (resources / 'ffmpeg').symlink_to('../Frameworks/ffmpeg')
    assert check_links(app) == 1


@pytest.mark.parametrize('kind', ['escape', 'absolute', 'missing', 'cycle'])
def test_archive_rejects_unsafe_or_nonportable_links(tmp_path, kind):
    app = tmp_path / 'SubFlow.app'
    app.mkdir()
    (tmp_path / 'external').write_text('outside')
    (app / 'binary').write_text('inside')
    targets = {'escape': '../external', 'absolute': str(app / 'binary'),
               'missing': 'absent', 'cycle': 'link'}
    (app / 'link').symlink_to(targets[kind])
    with pytest.raises((ValueError, FileNotFoundError, RuntimeError)):
        check_links(app)
