import functools
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from bilingual_sub.adapters import ytdlp
from bilingual_sub.adapters.ffmpeg import find_ffmpeg, probe_video, remux_to_mp4, run_cmd
from bilingual_sub.core.control import JobControl


def test_real_http_download_and_atomic_publish(tmp_path, monkeypatch):
    served = tmp_path / "served"
    served.mkdir()
    media = served / "clip.mp4"
    run_cmd([find_ffmpeg(), "-y", "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=0.5",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(media)])
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(served)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    # A local file server has no YouTube/Bilibili format listing. Exercise the
    # real HTTP transfer, callbacks, media probing and commit with its sole file.
    script = tmp_path / "local_http_worker.py"
    script.write_text('''import sys
from pathlib import Path
from bilingual_sub.adapters import ytdlp, download_worker
ytdlp.download_attempts = lambda url: iter([{"impersonate": False}])
ytdlp.format_for_height = lambda *args: "best"
ytdlp.prefer_audio_format = lambda *args: "best"
raise SystemExit(download_worker.main(Path(sys.argv[1])))
''', encoding="utf-8")
    monkeypatch.setattr("bilingual_sub.adapters.download_worker.worker_command",
                        lambda job: [sys.executable, str(script), str(job)])
    progress = []
    dest = tmp_path / "download's [中文]"
    dest.mkdir()
    (dest / "source.mp4").write_bytes(b"previous video")
    try:
        result = ytdlp.download(f"http://127.0.0.1:{server.server_port}/clip.mp4", dest,
                                control=JobControl(), on_progress=lambda s, p: progress.append(p))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
    assert result == dest / "source.mp4"
    assert result.read_bytes() == media.read_bytes()
    assert probe_video(result)["has_audio"]
    assert progress[-1] == 0.2
    assert not list(dest.glob(".subflow-download-*"))


def test_real_remux_transcodes_incompatible_audio(tmp_path):
    source = tmp_path / "source's.avi"
    target = tmp_path / "finished's.mp4"
    run_cmd([find_ffmpeg(), "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=0.5",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", "-c:v", "mpeg4",
             "-c:a", "pcm_s16le", "-shortest", str(source)])
    # PCM in this input requires transcoding when the MP4 muxer rejects copy.
    target.write_bytes(b"old export")
    assert remux_to_mp4(source, target, control=JobControl()) == target
    meta = probe_video(target)
    assert meta["width"] == 320 and meta["has_audio"]
    assert source.is_file()
    assert not list(tmp_path.glob(".subflow-remux-*"))
