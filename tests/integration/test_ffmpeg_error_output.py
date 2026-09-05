import sys

import pytest

from bilingual_sub.adapters.ffmpeg import FfmpegError, run_cmd
from bilingual_sub.core.control import JobControl


@pytest.mark.parametrize("controlled", [False, True])
def test_repeated_ffmpeg_errors_do_not_expand_exception_without_bound(controlled):
    script = "import sys; sys.stderr.write('warning\\n' * 100000 + 'final diagnostic'); sys.exit(7)"
    with pytest.raises(FfmpegError) as error:
        run_cmd([sys.executable, "-c", script], control=JobControl() if controlled else None)
    assert len(str(error.value)) <= 8192
    assert str(error.value).endswith("final diagnostic")
