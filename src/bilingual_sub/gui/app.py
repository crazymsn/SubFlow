"""语幕 SubFlow desktop client."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QWidget,
    QVBoxLayout,
)

from bilingual_sub.brand import (
    API_PORTAL_URL,
    APP_USER_MODEL_ID,
    COMPANY_ZH,
    GITHUB_URL,
    PRODUCT_EN,
    PRODUCT_ZH,
    WINDOW_TITLE,
)
from bilingual_sub.config import load_ui_theme, save_user_overrides
from bilingual_sub.core.control import JobControl
from bilingual_sub.gui.assets import GITHUB_MARK_PX, HEADER_MARK_PX, load_app_icon, load_brand_mark, load_github_mark
from bilingual_sub.gui.model_choice import merge_model_list, preferred_model
from bilingual_sub.gui.output_path import (
    DEFAULT_STEM_SUFFIX,
    copy_finished_outputs,
    next_output_path,
    relocate_output,
    resolve_output_mp4,
    sidecar_ass,
    sidecar_dub,
    sidecar_srt,
)
from bilingual_sub.gui.progress import format_pct, should_log_stage, stage_text
from bilingual_sub.gui.styles import app_qss
from bilingual_sub.gui.theme import tokens_for, type_font
from bilingual_sub.gui.widgets.action_bar import build_action_bar
from bilingual_sub.gui.widgets.deck import apply_deck_width, build_deck
from bilingual_sub.gui.widgets.field import SCROLL_FLOOR, hairline
from bilingual_sub.gui.widgets.header import build_header
from bilingual_sub.gui.widgets.source_strip import build_source
from bilingual_sub.gui.widgets.stage import build_stage
from bilingual_sub.gui.workers import DownloadWorker, ModelsWorker, PipelineWorker
from bilingual_sub.i18n import set_locale, tr
from bilingual_sub.logging_util import redact_api_key
from bilingual_sub.models import JobConfig, JobResult
from bilingual_sub.secrets.store import delete_api_key, get_api_key, set_api_key


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1280, 860)
        self.setMinimumSize(1200, 760)
        self._worker: PipelineWorker | None = None
        self._models_worker: ModelsWorker | None = None
        self._dl_worker: DownloadWorker | None = None
        self._last_output: Path | None = None
        self._last_result: JobResult | None = None
        self._last_signature: tuple | None = None
        self._last_log_stage: str | None = None
        self._video: Path | None = None
        self._control: JobControl | None = None
        self._section_labels: dict[str, QLabel] = {}
        self._theme = load_ui_theme()

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(8)
        outer.addLayout(build_header(self))
        outer.addWidget(hairline("headerRule"))
        outer.addWidget(build_source(self))
        outer.addWidget(build_deck(self))
        outer.addWidget(build_action_bar(self))
        outer.addWidget(hairline("stageRule", 2))
        outer.addWidget(build_stage(self), 1)

        icon = load_app_icon(self)
        if not icon.isNull():
            self.setWindowIcon(icon)
        self._apply_theme(persist=False)
        self._hydrate()
        self.retranslateUi()

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _section(self, key: str, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        self._section_labels[key] = label
        return label

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        apply_deck_width(self, self.width() >= 1200)
        self._relayout_deck()

    def _chrome_except_deck(self, layout, deck: QWidget, *, stage_floor: int) -> int:
        margins = layout.contentsMargins()
        used = margins.top() + margins.bottom()
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is deck:
                used += layout.spacing()
                continue
            used += self._chrome_item_height(item, widget, stage_floor=stage_floor) + layout.spacing()
        return used

    def _chrome_item_height(self, item, widget: QWidget | None, *, stage_floor: int) -> int:
        if widget is None:
            return max(item.sizeHint().height(), 0)
        if widget.objectName() == "stage":
            return stage_floor
        if 0 < widget.maximumHeight() <= 4:
            return max(widget.minimumHeight(), widget.height(), 1)
        hint = widget.sizeHint().height()
        if hint < 0:
            return max(widget.height(), widget.minimumHeight(), 0)
        return max(hint, 0)

    def _relayout_deck(self) -> None:
        scroll = getattr(self, "form_scroll", None)
        if scroll is not None:
            scroll.updateGeometry()
        deck = self.findChild(QWidget, "deck")
        stage = self.findChild(QWidget, "stage")
        root = self.centralWidget()
        layout = root.layout() if root is not None else None
        if deck is None or root is None or layout is None:
            return
        more_open = self.more_box.isVisible()
        more_need = self.more_box.sizeHint().height() if more_open else 0
        if more_open:
            self.more_box.setMinimumHeight(more_need)
            self.more_box.setMaximumHeight(more_need)
        else:
            self.more_box.setMinimumHeight(0)
            self.more_box.setMaximumHeight(16777215)
        foot = self.more_btn.parentWidget()
        foot_need = self.more_btn.sizeHint().height() + more_need + 18
        if foot is not None:
            if more_open:
                foot.setMinimumHeight(foot_need)
                foot.setMaximumHeight(foot_need)
            else:
                foot.setMinimumHeight(0)
                foot.setMaximumHeight(16777215)
        if scroll is not None:
            scroll.set_floor(0 if more_open else SCROLL_FLOOR)
        deck_floor = foot_need if more_open else SCROLL_FLOOR + foot_need
        stage_floor = 96
        if more_open:
            for floor in (96, 72, 48):
                stage_floor = floor
                room = root.height() - self._chrome_except_deck(layout, deck, stage_floor=floor)
                if room >= foot_need:
                    break
        else:
            stage_floor = max(stage.minimumSizeHint().height() if stage is not None else 96, 96)
        if stage is not None:
            stage.setMinimumHeight(stage_floor if more_open else 0)
        room = max(deck_floor, root.height() - self._chrome_except_deck(layout, deck, stage_floor=stage_floor))
        hint = max(deck_floor, deck.sizeHint().height())
        deck.setMinimumHeight(min(max(deck_floor, hint if more_open else 0), room))
        deck.setMaximumHeight(room if hint > room or more_open else 16777215)
        deck.updateGeometry()
        layout.invalidate()
        layout.activate()

    def _set_key_status(self, text: str) -> None:
        self.key_status.setText(text)
        self.key_status.setVisible(bool(text))

    def _hydrate(self) -> None:
        if get_api_key():
            self.key_edit.setPlaceholderText(tr("token_kept"))

    def _apply_logo(self) -> None:
        pix = load_brand_mark(HEADER_MARK_PX, self, self._theme)
        if not pix.isNull():
            self.logo_mark.setPixmap(pix)
            self.logo_mark.setFixedSize(HEADER_MARK_PX, HEADER_MARK_PX)

    def _apply_github(self) -> None:
        pix = load_github_mark(GITHUB_MARK_PX, self, self._theme)
        if not pix.isNull():
            self.github_btn.setIcon(QIcon(pix))
            self.github_btn.setIconSize(QSize(GITHUB_MARK_PX, GITHUB_MARK_PX))

    def _open_api_portal(self) -> None:
        QDesktopServices.openUrl(QUrl(API_PORTAL_URL))

    def _open_github(self) -> None:
        QDesktopServices.openUrl(QUrl(GITHUB_URL))

    def _clear_key(self) -> None:
        delete_api_key()
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(tr("token_ph"))
        self._set_key_status(tr("token_cleared"))

    def _apply_theme(self, persist: bool = True) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(app_qss(self._theme))
        self._apply_logo()
        self._apply_github()
        self._refresh_drop()
        for widget in (self.run_btn, self.download_btn, self.burn_check, self.refine_check, self.glossary_gen_check, self.dub_check):
            apply = getattr(widget, "apply_theme", None)
            if callable(apply):
                apply(self._theme)
        if persist:
            save_user_overrides({"ui": {"theme": self._theme}})

    def _on_theme(self) -> None:
        self._theme = str(self.theme_combo.currentData() or "light")
        self._apply_theme(persist=True)

    def _toggle_more(self, checked: bool) -> None:
        self.more_box.setVisible(checked)
        self.more_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self._relayout_deck()

    def _refresh_drop(self) -> None:
        tones = tokens_for(self._theme)
        if self._video:
            self.drop.set_prompt(self._video.name, title_color=tones.ink, hint_color=tones.muted)
            self.video_name.setText(str(self._video))
        else:
            self.drop.set_prompt(tr("drop"), title_color=tones.ink, hint_color=tones.muted)
            self.video_name.clear()

    def _set_video(self, path: Path) -> None:
        out = next_output_path(self.out_edit.text(), self._video, path)
        self._video = path
        self._refresh_drop()
        self.out_edit.setText(str(out))

    def _sync_download(self) -> None:
        busy = bool(self._dl_worker and self._dl_worker.isRunning())
        self.download_btn.setEnabled(bool(self.url_edit.text().strip()) and not busy)

    def _download(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_url"))
            return
        if self._dl_worker and self._dl_worker.isRunning():
            return
        dest = Path.home() / "Downloads" / "SubFlow"
        self.download_btn.setEnabled(False)
        self.stage_label.setText(tr("ingest"))
        self._set_stage_failed(False)
        self._dl_worker = DownloadWorker(url, dest)
        self._dl_worker.ok.connect(self._on_downloaded)
        self._dl_worker.fail.connect(self._on_download_fail)
        self._dl_worker.start()

    def _on_downloaded(self, path: str) -> None:
        self._sync_download()
        self._set_video(Path(path))
        self._log_line(f"{tr('ingest')}  {path}")

    def _on_download_fail(self, msg: str) -> None:
        self._sync_download()
        self.stage_label.setText(tr("waiting"))
        QMessageBox.warning(self, PRODUCT_ZH, msg)

    def _job_signature(self) -> tuple:
        video = ""
        if self._video is not None:
            try:
                video = str(self._video.resolve())
            except OSError:
                video = str(self._video)
        return (
            video,
            self.whisper_combo.currentText(),
            self.model_combo.currentText().strip(),
            str(self.source_lang_combo.currentData() or "zh"),
            str(self.target_lang_combo.currentData() or "en"),
            str(self.mode_combo.currentData() or "bilingual"),
            str(self.asr_backend_combo.currentData() or "whisper"),
            bool(self.refine_check.isChecked()),
            bool(self.burn_check.isChecked()),
            self.glossary_edit.text().strip(),
            bool(self.glossary_gen_check.isChecked()),
            bool(self.dub_check.isChecked()),
        )

    def _reuse_sources(self) -> tuple[Path | None, Path | None, Path | None, Path | None] | None:
        result = self._last_result
        if result is None or self._last_signature != self._job_signature() or self._job_busy():
            return None
        mp4, srt, ass, dub = result.output_mp4, result.output_srt, result.output_ass, result.output_dub
        if not any(path is not None and path.is_file() for path in (mp4, srt, ass)):
            return None
        return mp4, srt, ass, dub

    def _patch_report_outputs(self, dest_mp4: Path, dest_srt: Path) -> None:
        result = self._last_result
        if result is None or not result.report_path.is_file():
            return
        try:
            data = json.loads(result.report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        data["output_mp4"] = str(dest_mp4)
        data["output_srt"] = str(dest_srt)
        try:
            result.report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return

    def _try_relocate_outputs(self, dest_mp4: Path, *, log: bool = False) -> bool:
        sources = self._reuse_sources()
        if sources is None:
            return False
        src_mp4, src_srt, src_ass, src_dub = sources
        same_mp4 = src_mp4 is not None and src_mp4.resolve() == dest_mp4.resolve()
        same_srt = src_srt is not None and src_srt.resolve() == sidecar_srt(dest_mp4).resolve()
        if same_mp4 and same_srt:
            return True
        try:
            copied = copy_finished_outputs(
                dest_mp4,
                src_mp4=src_mp4,
                src_srt=src_srt,
                src_ass=src_ass,
                src_dub=src_dub,
            )
        except OSError as exc:
            QMessageBox.warning(self, PRODUCT_ZH, tr("out_mkdir").format(exc=exc))
            return False
        if not copied:
            return False
        dest_srt = sidecar_srt(dest_mp4)
        dest_ass = sidecar_ass(dest_mp4)
        dest_dub = sidecar_dub(dest_mp4) if src_dub else None
        self._last_result = replace(
            self._last_result,
            output_mp4=dest_mp4 if dest_mp4.is_file() else src_mp4,
            output_srt=dest_srt if dest_srt.is_file() else src_srt,
            output_ass=dest_ass if dest_ass.is_file() else src_ass,
            output_dub=dest_dub if dest_dub is not None and dest_dub.is_file() else src_dub,
            reused=True,
        )
        self._last_output = dest_mp4 if dest_mp4.is_file() else dest_srt
        self.open_btn.setEnabled(True)
        self._patch_report_outputs(dest_mp4, dest_srt)
        self.out_edit.setText(str(dest_mp4))
        if log and self._last_result is not None:
            self._log_line(tr("reused_log").format(n=self._last_result.cue_count))
            self.stage_label.setText(tr("done_stage").format(n=self._last_result.cue_count))
            self.progress.setValue(100)
            self.pct_label.setText(format_pct(100))
            self._set_stage_failed(False)
        return True

    def _on_out_path_committed(self) -> None:
        if self._job_busy() or self._last_result is None:
            return
        try:
            dest = resolve_output_mp4(self.out_edit.text(), self._video)
        except ValueError:
            return
        if self._video and dest.resolve() == self._video.resolve():
            return
        self._try_relocate_outputs(dest, log=True)

    def _browse_output(self) -> None:
        start = self.out_edit.text().strip()
        if start:
            start_path = Path(start).expanduser()
            start = str(start_path if start_path.is_dir() else start_path.parent)
        elif self._video:
            start = str(self._video.parent)
        else:
            start = str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, tr("select_out"), start)
        if not folder:
            return
        chosen = relocate_output(self.out_edit.text(), Path(folder), self._video)
        self.out_edit.setText(str(chosen))
        self._try_relocate_outputs(chosen, log=True)
        self.out_edit.setFocus()

    def _save_key(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_token"))
            return
        set_api_key(key)
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(tr("token_kept"))
        self._set_key_status(tr("token_saved"))

    def _refresh_models(self) -> None:
        if self._models_worker and self._models_worker.isRunning():
            return
        if not get_api_key() and not self.key_edit.text().strip():
            self._set_key_status(tr("need_token"))
            return
        if self.key_edit.text().strip():
            set_api_key(self.key_edit.text().strip())
            self.key_edit.clear()
            self.key_edit.setPlaceholderText(tr("token_kept"))
        self.fetch_models_btn.setEnabled(False)
        self._set_key_status(tr("fetching_models"))
        self._models_worker = ModelsWorker()
        self._models_worker.ok.connect(self._on_models)
        self._models_worker.fail.connect(self._on_models_fail)
        self._models_worker.start()

    def _on_models(self, models: list) -> None:
        self.fetch_models_btn.setEnabled(True)
        current = self.model_combo.currentText().strip()
        items = merge_model_list([str(m) for m in models], current)
        pick = preferred_model(items, current)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        if items:
            self.model_combo.addItems(items)
            if pick:
                self.model_combo.setCurrentText(pick)
            else:
                self.model_combo.setCurrentIndex(-1)
            self._set_key_status(tr("models_loaded").format(n=len(models)))
            QTimer.singleShot(0, self.model_combo.showPopup)
        else:
            self._set_key_status(tr("models_empty"))
        self.model_combo.blockSignals(False)

    def _on_models_fail(self, msg: str) -> None:
        self.fetch_models_btn.setEnabled(True)
        self._set_key_status(tr("models_fail").format(msg=msg))

    def _persist_model(self, *_args: object) -> None:
        model = self.model_combo.currentText().strip()
        if model:
            save_user_overrides({"translate": {"model": model}})

    def _on_locale(self) -> None:
        code = str(self.locale_combo.currentData() or "zh-Hans")
        set_locale(code)
        self.retranslateUi()

    def retranslateUi(self) -> None:
        self.lbl_ui_lang.setText(tr("ui_lang"))
        self.locale_combo.setAccessibleName(tr("ui_lang"))
        self.theme_combo.setItemText(0, tr("theme_light"))
        self.theme_combo.setItemText(1, tr("theme_dark"))
        self.more_btn.setText(tr("more"))
        self.lbl_api.setText(tr("api"))
        self.asr_help.setText(tr("asr_help"))
        self.tts_help.setText(tr("tts_help"))
        for key, i18n_key in {
            "models": "models",
            "glossary": "glossary",
            "dub": "dub",
            "out": "out",
        }.items():
            label = self._section_labels.get(key)
            if label:
                label.setText(tr(i18n_key))
        self.url_edit.setPlaceholderText(tr("url_ph"))
        self.download_btn.setText(tr("download"))
        self.lbl_source_file.setText(tr("source_file"))
        self.lbl_source_url.setText(tr("source_url"))
        self._refresh_drop()
        self.lbl_out.setText(tr("out"))
        self.lbl_source.setText(tr("source"))
        self.lbl_target.setText(tr("target"))
        self.lbl_mode.setText(tr("mode"))
        self.mode_combo.setItemText(0, tr("mode_bi"))
        self.mode_combo.setItemText(1, tr("mode_nf"))
        if get_api_key() and not self.key_edit.text().strip():
            self.key_edit.setPlaceholderText(tr("token_kept"))
        else:
            self.key_edit.setPlaceholderText(tr("token_ph"))
        self.save_btn.setText(tr("save_token"))
        self.clear_key_btn.setText(tr("clear_token"))
        self.api_portal_btn.setText(tr("api_portal"))
        self.github_btn.setToolTip(tr("github"))
        self.model_combo.setPlaceholderText(tr("model_ph"))
        self.glossary_edit.setPlaceholderText(tr("glossary_ph"))
        self.out_edit.setPlaceholderText(tr("out_ph"))
        self.fetch_models_btn.setText(tr("fetch_models"))
        self.rec_lab.setText(tr("asr"))
        self.lbl_asr.setText(tr("engine"))
        self.asr_backend_combo.setItemText(0, tr("engine_whisper"))
        self.asr_backend_combo.setItemText(1, tr("engine_whisperx"))
        self.lbl_model.setText(tr("models"))
        self.burn_check.setText(tr("burn"))
        self.refine_check.setText(tr("refine"))
        self.glossary_gen_check.setText(tr("glossary_gen"))
        self.glossary_browse_btn.setText(tr("browse"))
        self.dub_check.setText(tr("dub"))
        self.lbl_tts.setText(tr("tts_provider"))
        self.lbl_voice.setText(tr("tts_voice"))
        self.lbl_endpoint.setText(tr("tts_endpoint"))
        if self.tts_endpoint_edit.placeholderText() == "":
            self.tts_endpoint_edit.setPlaceholderText("http://127.0.0.1:9880")
        self.browse_out_btn.setText(tr("browse"))
        self.run_btn.setText(tr("start"))
        self.pause_btn.setText(tr("pause"))
        self.resume_btn.setText(tr("resume"))
        self.stop_btn.setText(tr("stop"))
        self.open_btn.setText(tr("open"))
        if self._worker is None or not self._worker.isRunning():
            self.stage_label.setText(tr("waiting"))
        self.log.setPlaceholderText(tr("log_ph"))
        self.drop.setAccessibleName(tr("drop"))

    def _toggle_dub(self, checked: bool) -> None:
        self.dub_box.setVisible(checked)
        self._sync_tts_fields()

    def _sync_tts_fields(self) -> None:
        on = self.dub_check.isChecked()
        sovits = str(self.tts_combo.currentData() or "openai") == "gptsovits"
        self.tts_combo.setEnabled(on)
        self.tts_voice_edit.setEnabled(on and not sovits)
        self.tts_endpoint_edit.setEnabled(on and sovits)
        self._slot_voice.setVisible(on and not sovits)
        self._slot_endpoint.setVisible(on and sovits)
        if self.more_box.isVisible():
            self._toggle_more(True)

    def _browse_glossary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("glossary"), "", "YAML/JSON (*.yaml *.yml *.json)")
        if path:
            self.glossary_edit.setText(path)

    def _job_busy(self) -> bool:
        return bool(self._worker is not None and self._worker.isRunning())

    def _set_running_ui(self, running: bool, paused: bool = False, stopping: bool = False) -> None:
        busy = bool(running or stopping)
        self.run_btn.setEnabled(not busy)
        self.pause_btn.setEnabled(bool(running) and not paused and not stopping)
        self.resume_btn.setEnabled(bool(running) and paused and not stopping)
        self.stop_btn.setEnabled(bool(running) and not stopping)
        self.run_btn.update()

    def _release_job(self) -> None:
        self._worker = None
        self._control = None
        self._set_running_ui(False)

    def _is_current_worker(self) -> bool:
        worker = self.sender()
        return worker is None or worker is self._worker

    def _on_worker_finished(self) -> None:
        if not self._is_current_worker():
            return
        if not self._job_busy():
            self._release_job()

    def _set_stage_failed(self, failed: bool) -> None:
        self.stage_label.setProperty("failed", failed)
        self.stage_label.style().unpolish(self.stage_label)
        self.stage_label.style().polish(self.stage_label)

    def _pause(self) -> None:
        if self._control is None or self._control.is_stopped():
            return
        self._control.pause()
        self._set_running_ui(True, paused=True)
        self._log_line(tr("pause"))

    def _resume(self) -> None:
        if self._control is None or self._control.is_stopped():
            return
        self._control.resume()
        self._set_running_ui(True, paused=False)
        self._log_line(tr("resume"))

    def _stop(self) -> None:
        if self._control is not None:
            self._control.stop()
        self.stage_label.setText(tr("stop"))
        self._set_stage_failed(False)
        if tr("stop") not in self.log.toPlainText().splitlines()[-3:]:
            self._log_line(tr("stop"))
        if self._job_busy():
            self._set_running_ui(True, stopping=True)
            return
        self._release_job()

    def _start(self) -> None:
        if self._job_busy():
            return
        url = self.url_edit.text().strip()
        if (not self._video or not self._video.is_file()) and not url:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_video"))
            return
        if not get_api_key() and not self.key_edit.text().strip():
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_token"))
            return
        if self.key_edit.text().strip():
            set_api_key(self.key_edit.text().strip())

        model = self.model_combo.currentText().strip()
        if not model:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_model"))
            return
        save_user_overrides({"translate": {"model": model}})

        if not self.out_edit.text().strip() and url and not self._video:
            self.out_edit.setText(str(Path.home() / "Downloads" / f"source{DEFAULT_STEM_SUFFIX}.mp4"))
        try:
            out_mp4 = resolve_output_mp4(self.out_edit.text(), self._video)
        except ValueError:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_out"))
            return
        if self._video and out_mp4.resolve() == self._video.resolve():
            QMessageBox.warning(self, PRODUCT_ZH, tr("out_same"))
            return
        try:
            out_mp4.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, PRODUCT_ZH, tr("out_mkdir").format(exc=exc))
            return
        self.out_edit.setText(str(out_mp4))
        if self._try_relocate_outputs(out_mp4, log=True):
            return
        self._last_log_stage = None
        gloss = self.glossary_edit.text().strip()
        tts = str(self.tts_combo.currentData() or "openai") if self.dub_check.isChecked() else "none"
        cfg = JobConfig(
            input_video=self._video or Path(url),
            output_video=out_mp4 if self.burn_check.isChecked() else None,
            output_srt=out_mp4.with_name(out_mp4.stem + ".bilingual.srt"),
            work_dir=Path("auto"),
            whisper_model=self.whisper_combo.currentText(),
            translate_model=model,
            burn=self.burn_check.isChecked(),
            source_lang=str(self.source_lang_combo.currentData() or "zh"),
            target_lang=str(self.target_lang_combo.currentData() or "en"),
            subtitle_mode=str(self.mode_combo.currentData() or "bilingual"),
            asr_backend=str(self.asr_backend_combo.currentData() or "whisper"),
            refine_translate=self.refine_check.isChecked(),
            source_url=url or None,
            glossary_path=Path(gloss) if gloss else None,
            glossary_generate=self.glossary_gen_check.isChecked(),
            enable_dub=self.dub_check.isChecked() and tts != "none",
            tts_provider=tts,  # type: ignore[arg-type]
            tts_voice="" if tts != "openai" else str(self.tts_voice_edit.currentData() or "alloy"),
            tts_endpoint="" if tts != "gptsovits" else self.tts_endpoint_edit.text().strip(),
            ui_locale=str(self.locale_combo.currentData() or "zh-Hans"),
        )
        if self._video and self._video.is_file():
            cfg.source_url = None
        self.log.clear()
        self.progress.setValue(0)
        self.pct_label.setText(format_pct(0))
        self.stage_label.setText(tr("starting"))
        self._set_stage_failed(False)
        self._control = JobControl()
        self._set_running_ui(True, paused=False)
        self._worker = PipelineWorker(cfg, self._control)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_progress(self, stage: str, pct: float) -> None:
        label = stage_text(stage)
        shown = max(0, min(100, int(pct * 100)))
        self.progress.setValue(shown)
        self.pct_label.setText(format_pct(shown))
        self.stage_label.setText(label)
        self._set_stage_failed(False)
        if should_log_stage(stage, self._last_log_stage):
            self._log_line(label)
            self._last_log_stage = stage

    def _on_done(self, result: object) -> None:
        if not self._is_current_worker():
            return
        assert isinstance(result, JobResult)
        self._set_running_ui(False)
        self.progress.setValue(100)
        self.pct_label.setText(format_pct(100))
        self.stage_label.setText(tr("done_stage").format(n=result.cue_count))
        self._set_stage_failed(False)
        folder = result.output_mp4 or result.output_srt
        self._last_output = folder
        self._last_result = result
        self._last_signature = self._job_signature()
        self.open_btn.setEnabled(True)
        if result.reused:
            self._log_line(tr("reused_log").format(n=result.cue_count))
        else:
            self._log_line(tr("done_log").format(n=result.cue_count))
        if result.missing_en:
            self._log_line(tr("missing_en_log").format(n=len(result.missing_en)))

    def _log_line(self, text: str) -> None:
        self.log.appendPlainText(redact_api_key(text, get_api_key()))

    def _on_fail(self, msg: str) -> None:
        if not self._is_current_worker():
            return
        self._set_running_ui(False)
        stopped = msg in {tr("stop"), "job stopped"} or bool(self._control and self._control.is_stopped())
        safe = redact_api_key(msg, get_api_key())
        self.stage_label.setText(tr("stop") if stopped else tr("fail"))
        self._set_stage_failed(not stopped)
        if stopped:
            if tr("stop") not in self.log.toPlainText().splitlines()[-5:]:
                self._log_line(tr("stop"))
        else:
            self._log_line(tr("error_prefix").format(msg=safe))
            QMessageBox.critical(self, PRODUCT_ZH, safe)

    def _open_folder(self) -> None:
        if not self._last_output:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output.parent)))


def _install_app_icon(app: QApplication) -> QIcon:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    return icon


def main() -> None:
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(PRODUCT_EN)
    app.setOrganizationName(COMPANY_ZH)
    icon = _install_app_icon(app)
    app.setFont(type_font(size=14))
    app.setStyleSheet(app_qss(load_ui_theme()))
    win = MainWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
