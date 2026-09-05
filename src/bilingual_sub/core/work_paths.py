"""Names reserved for pipeline artifacts, logs, locks and scratch directories."""
from pathlib import Path

from bilingual_sub.core.cache_records import FILES
from bilingual_sub.core.output_guard import path_comparison_key, paths_conflict, same_file

WORK_FILES = tuple(dict.fromkeys((
    "source.mp4", "job_state.json", "job_input.json", "report.json", ".job.lock",
    "source.url.txt", "source.download.json", "source.download.mp4",
    "source.download.pending.json", "sovits_ref.wav", "whisper.log", "whisperx.log",
    *(name for names in FILES.values() for name in names),
)))
WORK_TREES = ("tts", "downloads")


def validate_work_inputs(work: Path, video: Path, inputs: list[Path], *, downloaded: bool) -> None:
    """Reject input collisions before the task lock or state can overwrite them."""
    source = work / "source.mp4"
    for index, path in enumerate([video, *inputs]):
        for name in WORK_FILES:
            destination = work / name
            if not paths_conflict(path, destination):
                continue
            # Existing work copies are valid local sources and resume inputs.
            # A download is allowed to replace its source, not a reference or glossary.
            if name == "source.mp4" and index == 0 and same_file(path, source):
                continue
            if name == "source.mp4" and not downloaded and same_file(path, video) and same_file(video, source):
                continue
            raise ValueError(f"工作文件会覆盖输入：{path}；请选择其他输入路径或工作目录")
        key = Path(path_comparison_key(str(path.resolve())))
        for name in WORK_TREES:
            tree = Path(path_comparison_key(str((work / name).resolve())))
            if key.is_relative_to(tree):
                raise ValueError(f"输入位于工作临时目录：{path}；请选择其他输入路径或工作目录")
