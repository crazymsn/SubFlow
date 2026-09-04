"""语幕 SubFlow desktop client."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bilingual_sub.adapters.meding import MedingAuthError, create_client
from bilingual_sub.brand import (
    APP_USER_MODEL_ID,
    COMPANY_ZH,
    PRODUCT_EN,
    PRODUCT_FULL,
    PRODUCT_ZH,
    WINDOW_TITLE,
    mark_path,
)
from bilingual_sub.config import save_user_overrides
from bilingual_sub.gui.assets import HEADER_MARK_PX, load_app_icon, load_pixmap
from bilingual_sub.gui.model_choice import merge_model_list, preferred_model
from bilingual_sub.adapters.whisper_backend import default_whisper_model, has_nvidia_gpu
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.core.langs import SOURCE_LANGS, SUB_LANGS, UI_LOCALES
from bilingual_sub.gui.output_path import next_output_path, relocate_output, resolve_output_mp4
from bilingual_sub.gui.progress import should_log_stage, stage_text
from bilingual_sub.gui.styles import app_qss
from bilingual_sub.i18n import set_locale, tr
from bilingual_sub.models import JobConfig, JobResult
from bilingual_sub.secrets.store import get_api_key, set_api_key

VIDEO_FILTER = "Video (*.mp4 *.mkv *.mov *.avi *.webm *.m4v)"


class PipelineWorker(QThread):
    progress = Signal(str, float)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, config: JobConfig, control: JobControl) -> None:
        super().__init__()
        self.config = config
        self.control = control

    def run(self) -> None:
        try:
            from bilingual_sub.pipeline import run as run_job

            result = run_job(
                self.config,
                on_progress=lambda s, p: self.progress.emit(s, p),
                control=self.control,
            )
            self.finished_ok.emit(result)
        except JobStopped:
            self.failed.emit(tr("stop"))
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelsWorker(QThread):
    ok = Signal(list)
    fail = Signal(str)

    def run(self) -> None:
        key = get_api_key()
        if not key:
            self.fail.emit("请先保存 API 令牌")
            return
        try:
            models = create_client(key).list_models()
            self.ok.emit(models)
        except MedingAuthError as exc:
            self.fail.emit(str(exc))
        except Exception as exc:
            self.fail.emit(str(exc))


class DropCard(QLabel):
    file_dropped = Signal(Path)

    def __init__(self) -> None:
        super().__init__("将视频拖到这里，或点击选择")
        self.setObjectName("drop")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(104)
        self.setMaximumHeight(120)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("active", False)
        self.setAccessibleName("选择视频")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(self, "选择视频", "", VIDEO_FILTER)
            if path:
                self.file_dropped.emit(Path(path))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            self.setProperty("active", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.is_file():
                self.file_dropped.emit(path)


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1180, 780)
        self.setMinimumSize(1020, 680)
        self._worker: PipelineWorker | None = None
        self._models_worker: ModelsWorker | None = None
        self._last_output: Path | None = None
        self._last_log_stage: str | None = None
        self._video: Path | None = None
        self._control: JobControl | None = None
        self._section_labels: dict[str, QLabel] = {}

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 20, 28, 16)
        outer.setSpacing(16)
        outer.addLayout(self._build_header())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_left())
        split.addWidget(self._build_right())
        split.setChildrenCollapsible(False)
        split.setSizes([400, 560])
        outer.addWidget(split, 1)

        self._hydrate()
        self.retranslateUi()

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(14)
        header.setContentsMargins(0, 0, 0, 4)
        mark = QLabel()
        mark.setObjectName("logoMark")
        pix = load_pixmap(mark_path(), HEADER_MARK_PX, self)
        if not pix.isNull():
            mark.setPixmap(pix)
        mark.setFixedSize(HEADER_MARK_PX, HEADER_MARK_PX)
        mark.setScaledContents(True)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setAccessibleName(WINDOW_TITLE)
        header.addWidget(mark, alignment=Qt.AlignmentFlag.AlignVCenter)
        title = QLabel(PRODUCT_FULL)
        title.setObjectName("brandTitle")
        header.addWidget(title, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        self.locale_combo = QComboBox()
        self.locale_combo.setMinimumWidth(140)
        for code, label in UI_LOCALES:
            self.locale_combo.addItem(label, code)
        self.locale_combo.setCurrentIndex(1)
        self.locale_combo.currentIndexChanged.connect(self._on_locale)
        header.addWidget(self.locale_combo, alignment=Qt.AlignmentFlag.AlignVCenter)
        return header

    def _section(self, key: str, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        self._section_labels[key] = label
        return label

    def _build_left(self) -> QWidget:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        layout.addWidget(self._section("upload", "上传视频"))
        self.drop = DropCard()
        self.drop.file_dropped.connect(self._set_video)
        layout.addWidget(self.drop)
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("YouTube / 视频链接")
        self.download_btn = QPushButton("下载")
        self.download_btn.setObjectName("ghost")
        self.download_btn.clicked.connect(self._start)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.download_btn)
        layout.addLayout(url_row)
        self.video_name = QLabel("尚未选择视频")
        self.video_name.setObjectName("tagline")
        self.video_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.video_name)

        layout.addWidget(self._section("sub_lang", "字幕语言"))
        lang_grid = QGridLayout()
        lang_grid.setHorizontalSpacing(8)
        lang_grid.setVerticalSpacing(6)
        self.lbl_source = QLabel("源语言")
        self.lbl_source.setObjectName("tagline")
        self.lbl_target = QLabel("目标语言")
        self.lbl_target.setObjectName("tagline")
        self.lbl_mode = QLabel("字幕模式")
        self.lbl_mode.setObjectName("tagline")
        self.source_lang_combo = QComboBox()
        for code, label in SOURCE_LANGS:
            self.source_lang_combo.addItem(label, code)
        self.source_lang_combo.setCurrentIndex(1)
        self.target_lang_combo = QComboBox()
        for code, label in SUB_LANGS:
            self.target_lang_combo.addItem(label, code)
        self.target_lang_combo.setCurrentIndex(2)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("中英双语", "bilingual")
        self.mode_combo.addItem("单行 Netflix", "netflix_single")
        lang_grid.addWidget(self.lbl_source, 0, 0)
        lang_grid.addWidget(self.source_lang_combo, 0, 1)
        lang_grid.addWidget(self.lbl_target, 1, 0)
        lang_grid.addWidget(self.target_lang_combo, 1, 1)
        lang_grid.addWidget(self.lbl_mode, 2, 0)
        lang_grid.addWidget(self.mode_combo, 2, 1)
        layout.addLayout(lang_grid)

        layout.addWidget(self._section("api", "API 令牌"))
        key_row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("填入后点击保存令牌")
        self.key_edit.setClearButtonEnabled(True)
        self.save_btn = QPushButton("保存令牌")
        self.save_btn.setObjectName("ghost")
        self.save_btn.setMinimumWidth(108)
        self.save_btn.clicked.connect(self._save_key)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.save_btn)
        layout.addLayout(key_row)
        self.key_status = QLabel("")
        self.key_status.setObjectName("tagline")
        layout.addWidget(self.key_status)

        layout.addWidget(self._section("models", "翻译模型"))
        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(False)
        self.model_combo.setMaxVisibleItems(18)
        self.model_combo.setMinimumContentsLength(16)
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.model_combo.setPlaceholderText("点击获取模型后选择")
        self.model_combo.activated.connect(self._persist_model)
        self.fetch_models_btn = QPushButton("获取模型")
        self.fetch_models_btn.setObjectName("ghost")
        self.fetch_models_btn.setMinimumWidth(108)
        self.fetch_models_btn.clicked.connect(self._refresh_models)
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.fetch_models_btn)
        layout.addLayout(model_row)

        rec_row = QHBoxLayout()
        rec_row.setSpacing(8)
        self.rec_lab = QLabel("识别模型")
        self.rec_lab.setObjectName("tagline")
        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(["tiny", "base", "small", "medium", "large"])
        whisper_default = default_whisper_model()
        self.whisper_combo.setCurrentText(whisper_default)
        if has_nvidia_gpu():
            self.whisper_combo.setToolTip("有独显时默认 medium。large 更准，但更慢、更吃显存。")
        else:
            self.whisper_combo.setToolTip(
                "未检测到独显，默认 small 并走 CPU。medium/large 仍可选，但会明显更慢。"
            )
        self.burn_check = QCheckBox("烧录到视频")
        self.burn_check.setChecked(True)
        rec_row.addWidget(self.rec_lab)
        rec_row.addWidget(self.whisper_combo, 1)
        rec_row.addWidget(self.burn_check)
        layout.addLayout(rec_row)

        asr_row = QHBoxLayout()
        self.lbl_asr = QLabel("识别引擎")
        self.lbl_asr.setObjectName("tagline")
        self.asr_backend_combo = QComboBox()
        self.asr_backend_combo.addItem("Whisper", "whisper")
        self.asr_backend_combo.addItem("WhisperX", "whisperx")
        self.asr_backend_combo.setCurrentIndex(0)
        self.asr_backend_combo.setToolTip("背景乐大时识别会漂，可先降噪或改用 whisper。wav2vec 对数字较弱。")
        asr_row.addWidget(self.lbl_asr)
        asr_row.addWidget(self.asr_backend_combo, 1)
        layout.addLayout(asr_row)
        self.refine_check = QCheckBox("电影级润色")
        self.refine_check.setChecked(False)
        layout.addWidget(self.refine_check)

        layout.addWidget(self._section("glossary", "术语"))
        gloss_row = QHBoxLayout()
        self.glossary_edit = QLineEdit()
        self.glossary_edit.setPlaceholderText("术语表 JSON / YAML 路径（可选）")
        self.glossary_browse_btn = QPushButton("浏览")
        self.glossary_browse_btn.setObjectName("ghost")
        self.glossary_browse_btn.clicked.connect(self._browse_glossary)
        gloss_row.addWidget(self.glossary_edit, 1)
        gloss_row.addWidget(self.glossary_browse_btn)
        layout.addLayout(gloss_row)
        self.glossary_gen_check = QCheckBox("从视频生成术语")
        self.glossary_gen_check.setChecked(False)
        layout.addWidget(self.glossary_gen_check)

        self.dub_check = QCheckBox("配音")
        self.dub_check.setChecked(False)
        self.dub_check.toggled.connect(self._toggle_dub)
        layout.addWidget(self.dub_check)
        self.dub_box = QWidget()
        dub_grid = QGridLayout(self.dub_box)
        dub_grid.setContentsMargins(0, 0, 0, 0)
        self.lbl_tts = QLabel("配音引擎")
        self.lbl_tts.setObjectName("tagline")
        self.tts_combo = QComboBox()
        self.tts_combo.addItems(["none", "openai", "azure", "gptsovits"])
        self.tts_voice_edit = QLineEdit()
        self.tts_voice_edit.setPlaceholderText("音色")
        self.tts_endpoint_edit = QLineEdit()
        self.tts_endpoint_edit.setPlaceholderText("GPT-SoVITS 地址")
        dub_grid.addWidget(self.lbl_tts, 0, 0)
        dub_grid.addWidget(self.tts_combo, 0, 1)
        dub_grid.addWidget(self.tts_voice_edit, 1, 0, 1, 2)
        dub_grid.addWidget(self.tts_endpoint_edit, 2, 0, 1, 2)
        self.dub_box.setVisible(False)
        layout.addWidget(self.dub_box)

        layout.addWidget(self._section("out", "输出路径"))
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(False)
        self.out_edit.setEnabled(True)
        self.out_edit.setClearButtonEnabled(True)
        self.out_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.out_edit.setPlaceholderText("可输入完整路径，或点浏览只换导出文件夹")
        self.browse_out_btn = QPushButton("浏览")
        self.browse_out_btn.setObjectName("ghost")
        self.browse_out_btn.setMinimumWidth(108)
        self.browse_out_btn.clicked.connect(self._browse_output)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(self.browse_out_btn)
        layout.addLayout(out_row)

        btns = QHBoxLayout()
        self.run_btn = QPushButton("开始处理")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._start)
        self.start_btn = self.run_btn
        self.pause_btn = QPushButton("暂停")
        self.resume_btn = QPushButton("继续")
        self.stop_btn = QPushButton("停止")
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._pause)
        self.resume_btn.clicked.connect(self._resume)
        self.stop_btn.clicked.connect(self._stop)
        self.open_btn = QPushButton("打开文件夹")
        self.open_btn.setObjectName("ghost")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_folder)
        btns.addWidget(self.run_btn, 1)
        btns.addWidget(self.pause_btn)
        btns.addWidget(self.resume_btn)
        btns.addWidget(self.stop_btn)
        btns.addWidget(self.open_btn)
        layout.addLayout(btns)
        layout.addStretch()
        return card

    def _build_right(self) -> QWidget:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(self._section("progress", "处理进度"))
        self.stage_label = QLabel("等待开始")
        self.stage_label.setObjectName("tagline")
        layout.addWidget(self.stage_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("处理日志会显示在这里")
        layout.addWidget(self.log, 1)
        return card

    def _hydrate(self) -> None:
        if get_api_key():
            self.key_edit.setPlaceholderText("已保存（留空沿用）")
            self.key_status.setText("本机已保存 API 令牌，点击获取模型后选择")

    def _set_video(self, path: Path) -> None:
        out = next_output_path(self.out_edit.text(), self._video, path)
        self._video = path
        self.video_name.setText(path.name)
        self.drop.setText(path.name)
        self.out_edit.setText(str(out))

    def _browse_output(self) -> None:
        start = self.out_edit.text().strip()
        if start:
            start_path = Path(start).expanduser()
            start = str(start_path if start_path.is_dir() else start_path.parent)
        elif self._video:
            start = str(self._video.parent)
        else:
            start = str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择导出位置", start)
        if not folder:
            return
        chosen = relocate_output(self.out_edit.text(), Path(folder), self._video)
        self.out_edit.setText(str(chosen))
        self.out_edit.setFocus()

    def _save_key(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, PRODUCT_ZH, "请输入 API 令牌")
            return
        set_api_key(key)
        self.key_edit.clear()
        self.key_edit.setPlaceholderText("已保存（留空沿用）")
        self.key_status.setText("令牌已保存，点击获取模型后选择")

    def _refresh_models(self) -> None:
        if self._models_worker and self._models_worker.isRunning():
            return
        if not get_api_key() and not self.key_edit.text().strip():
            self.key_status.setText("请先保存 API 令牌，再获取模型")
            return
        if self.key_edit.text().strip():
            set_api_key(self.key_edit.text().strip())
            self.key_edit.clear()
            self.key_edit.setPlaceholderText("已保存（留空沿用）")
        self.fetch_models_btn.setEnabled(False)
        self.key_status.setText("正在获取模型列表…")
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
            self.key_status.setText(f"已加载 {len(models)} 个模型，请选择")
            QTimer.singleShot(0, self.model_combo.showPopup)
        else:
            self.key_status.setText("未返回模型列表")
        self.model_combo.blockSignals(False)

    def _on_models_fail(self, msg: str) -> None:
        self.fetch_models_btn.setEnabled(True)
        self.key_status.setText(f"获取模型失败：{msg}")

    def _persist_model(self, *_args: object) -> None:
        model = self.model_combo.currentText().strip()
        if model:
            save_user_overrides({"translate": {"model": model}})

    def _on_locale(self) -> None:
        code = str(self.locale_combo.currentData() or "zh-Hans")
        set_locale(code)
        self.retranslateUi()

    def retranslateUi(self) -> None:
        self._section_labels.get("upload") and self._section_labels["upload"].setText(tr("upload"))
        self._section_labels.get("sub_lang") and self._section_labels["sub_lang"].setText(tr("sub_lang"))
        self._section_labels.get("api") and self._section_labels["api"].setText(tr("api"))
        self._section_labels.get("models") and self._section_labels["models"].setText(tr("models"))
        self._section_labels.get("glossary") and self._section_labels["glossary"].setText(tr("glossary"))
        self._section_labels.get("out") and self._section_labels["out"].setText(tr("out"))
        self._section_labels.get("progress") and self._section_labels["progress"].setText(tr("progress"))
        self.url_edit.setPlaceholderText(tr("url_ph"))
        self.download_btn.setText(tr("download"))
        if not self._video:
            self.video_name.setText(tr("no_video"))
            self.drop.setText(tr("drop"))
        self.lbl_source.setText(tr("source"))
        self.lbl_target.setText(tr("target"))
        self.lbl_mode.setText(tr("mode"))
        self.mode_combo.setItemText(0, tr("mode_bi"))
        self.mode_combo.setItemText(1, tr("mode_nf"))
        self.fetch_models_btn.setText(tr("fetch_models"))
        self.rec_lab.setText(tr("asr"))
        self.lbl_asr.setText(tr("engine"))
        self.burn_check.setText(tr("burn"))
        self.refine_check.setText(tr("refine"))
        self.glossary_gen_check.setText(tr("glossary_gen"))
        self.glossary_browse_btn.setText(tr("browse"))
        self.dub_check.setText(tr("dub"))
        self.lbl_tts.setText(tr("tts_provider"))
        self.tts_voice_edit.setPlaceholderText(tr("tts_voice"))
        self.tts_endpoint_edit.setPlaceholderText(tr("tts_endpoint"))
        self.browse_out_btn.setText(tr("browse"))
        self.run_btn.setText(tr("start"))
        self.pause_btn.setText(tr("pause"))
        self.resume_btn.setText(tr("resume"))
        self.stop_btn.setText(tr("stop"))
        self.open_btn.setText(tr("open"))
        self.stage_label.setText(tr("waiting"))
        self.log.setPlaceholderText(tr("progress"))

    def _toggle_dub(self, checked: bool) -> None:
        self.dub_box.setVisible(checked)
        self.tts_combo.setEnabled(checked)
        self.tts_voice_edit.setEnabled(checked)
        self.tts_endpoint_edit.setEnabled(checked)

    def _browse_glossary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("glossary"), "", "YAML/JSON (*.yaml *.yml *.json)")
        if path:
            self.glossary_edit.setText(path)

    def _set_running_ui(self, running: bool, paused: bool = False) -> None:
        self.run_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running and not paused)
        self.resume_btn.setEnabled(running and paused)
        self.stop_btn.setEnabled(running)

    def _pause(self) -> None:
        if self._control:
            self._control.pause()
            self._set_running_ui(True, paused=True)
            self.log.appendPlainText(tr("pause"))

    def _resume(self) -> None:
        if self._control:
            self._control.resume()
            self._set_running_ui(True, paused=False)
            self.log.appendPlainText(tr("resume"))

    def _stop(self) -> None:
        if self._control:
            self._control.stop()
            self.log.appendPlainText(tr("stop"))

    def _start(self) -> None:
        url = self.url_edit.text().strip()
        if (not self._video or not self._video.is_file()) and not url:
            QMessageBox.warning(self, PRODUCT_ZH, "请先选择视频")
            return
        if not get_api_key() and not self.key_edit.text().strip():
            QMessageBox.warning(self, PRODUCT_ZH, "请先填写并保存 API 令牌")
            return
        if self.key_edit.text().strip():
            set_api_key(self.key_edit.text().strip())

        model = self.model_combo.currentText().strip()
        if not model:
            QMessageBox.warning(self, PRODUCT_ZH, "请先获取并选择翻译模型")
            return
        save_user_overrides({"translate": {"model": model}})

        if not self.out_edit.text().strip() and url and not self._video:
            self.out_edit.setText(str(Path.home() / "Downloads" / "source-中英字幕.mp4"))
        try:
            out_mp4 = resolve_output_mp4(self.out_edit.text(), self._video)
        except ValueError:
            QMessageBox.warning(self, PRODUCT_ZH, "请填写输出路径")
            return
        if self._video and out_mp4.resolve() == self._video.resolve():
            QMessageBox.warning(self, PRODUCT_ZH, "输出路径不能和原片相同")
            return
        try:
            out_mp4.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, PRODUCT_ZH, f"无法创建输出目录：{exc}")
            return
        self.out_edit.setText(str(out_mp4))
        self._last_log_stage = None
        gloss = self.glossary_edit.text().strip()
        tts = self.tts_combo.currentText() if self.dub_check.isChecked() else "none"
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
            tts_voice=self.tts_voice_edit.text().strip(),
            tts_endpoint=self.tts_endpoint_edit.text().strip(),
            ui_locale=str(self.locale_combo.currentData() or "zh-Hans"),
        )
        if self._video and self._video.is_file():
            cfg.source_url = None
        self.log.clear()
        self.progress.setValue(0)
        self.stage_label.setText("启动中…")
        self._control = JobControl()
        self._set_running_ui(True, paused=False)
        self._worker = PipelineWorker(cfg, self._control)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_progress(self, stage: str, pct: float) -> None:
        label = stage_text(stage)
        self.progress.setValue(int(pct * 100))
        self.stage_label.setText(f"{label}  ·  {pct * 100:.0f}%")
        if should_log_stage(stage, self._last_log_stage):
            self.log.appendPlainText(label)
            self._last_log_stage = stage

    def _on_done(self, result: object) -> None:
        assert isinstance(result, JobResult)
        self._set_running_ui(False)
        self.progress.setValue(100)
        self.stage_label.setText(f"完成  ·  {result.cue_count} 条字幕")
        folder = result.output_mp4 or result.output_srt
        self._last_output = folder
        self.open_btn.setEnabled(True)
        if result.reused:
            self.log.appendPlainText(f"已按新路径导出，{result.cue_count} 条字幕")
        else:
            self.log.appendPlainText(f"完成，{result.cue_count} 条字幕")
        if result.missing_en:
            self.log.appendPlainText(f"英文缺失 {len(result.missing_en)} 条")

    def _on_fail(self, msg: str) -> None:
        self._set_running_ui(False)
        stopped = msg in {tr("stop"), "job stopped"}
        self.stage_label.setText(tr("stop") if stopped else "失败")
        self.log.appendPlainText(msg if stopped else f"错误: {msg}")
        if not stopped:
            QMessageBox.critical(self, PRODUCT_ZH, msg)

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
    font = QFont("Segoe UI", 11)
    app.setFont(font)
    app.setStyleSheet(app_qss())
    win = MainWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.showMaximized()
    sys.exit(app.exec())
