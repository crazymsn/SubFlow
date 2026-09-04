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
from bilingual_sub.gui.output_path import default_output_mp4, next_output_path, resolve_output_mp4
from bilingual_sub.gui.styles import app_qss
from bilingual_sub.models import JobConfig, JobResult
from bilingual_sub.secrets.store import get_api_key, set_api_key

VIDEO_FILTER = "Video (*.mp4 *.mkv *.mov *.avi *.webm *.m4v)"


class PipelineWorker(QThread):
    progress = Signal(str, float)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, config: JobConfig) -> None:
        super().__init__()
        self.config = config

    def run(self) -> None:
        try:
            from bilingual_sub.pipeline import run as run_job

            result = run_job(self.config, on_progress=lambda s, p: self.progress.emit(s, p))
            self.finished_ok.emit(result)
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
        self._video: Path | None = None

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
        return header

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        return label

    def _build_left(self) -> QWidget:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        layout.addWidget(self._section("上传视频"))
        self.drop = DropCard()
        self.drop.file_dropped.connect(self._set_video)
        layout.addWidget(self.drop)
        self.video_name = QLabel("尚未选择视频")
        self.video_name.setObjectName("tagline")
        self.video_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.video_name)

        layout.addWidget(self._section("API 令牌"))
        key_row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("填入后点击保存令牌")
        self.key_edit.setClearButtonEnabled(True)
        save_btn = QPushButton("保存令牌")
        save_btn.setObjectName("ghost")
        save_btn.setMinimumWidth(108)
        save_btn.clicked.connect(self._save_key)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(save_btn)
        layout.addLayout(key_row)
        self.key_status = QLabel("")
        self.key_status.setObjectName("tagline")
        layout.addWidget(self.key_status)

        layout.addWidget(self._section("翻译模型"))
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
        rec_lab = QLabel("识别模型")
        rec_lab.setObjectName("tagline")
        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(["tiny", "base", "small", "medium", "large"])
        self.whisper_combo.setCurrentText("medium")
        self.burn_check = QCheckBox("烧录到视频")
        self.burn_check.setChecked(True)
        rec_row.addWidget(rec_lab)
        rec_row.addWidget(self.whisper_combo, 1)
        rec_row.addWidget(self.burn_check)
        layout.addLayout(rec_row)

        layout.addWidget(self._section("输出路径"))
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(False)
        self.out_edit.setEnabled(True)
        self.out_edit.setClearButtonEnabled(True)
        self.out_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.out_edit.setPlaceholderText("可输入或点浏览选择保存位置")
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
        self.open_btn = QPushButton("打开文件夹")
        self.open_btn.setObjectName("ghost")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_folder)
        btns.addWidget(self.run_btn, 1)
        btns.addWidget(self.open_btn)
        layout.addLayout(btns)
        layout.addStretch()
        return card

    def _build_right(self) -> QWidget:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(self._section("处理进度"))
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
        if not start and self._video:
            start = str(default_output_mp4(self._video))
        elif not start:
            start = str(Path.home())
        path, _ = QFileDialog.getSaveFileName(self, "选择输出视频", start, "Video (*.mp4)")
        if not path:
            return
        chosen = Path(path)
        if chosen.suffix.lower() != ".mp4":
            chosen = chosen.with_suffix(".mp4")
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

    def _start(self) -> None:
        if not self._video or not self._video.is_file():
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

        try:
            out_mp4 = resolve_output_mp4(self.out_edit.text(), self._video)
        except ValueError:
            QMessageBox.warning(self, PRODUCT_ZH, "请填写输出路径")
            return
        if out_mp4.resolve() == self._video.resolve():
            QMessageBox.warning(self, PRODUCT_ZH, "输出路径不能和原片相同")
            return
        try:
            out_mp4.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, PRODUCT_ZH, f"无法创建输出目录：{exc}")
            return
        self.out_edit.setText(str(out_mp4))
        cfg = JobConfig(
            input_video=self._video,
            output_video=out_mp4 if self.burn_check.isChecked() else None,
            output_srt=out_mp4.with_name(out_mp4.stem + ".bilingual.srt"),
            work_dir=Path("auto"),
            whisper_model=self.whisper_combo.currentText(),
            translate_model=model,
            burn=self.burn_check.isChecked(),
        )
        self.log.clear()
        self.progress.setValue(0)
        self.stage_label.setText("启动中…")
        self.run_btn.setEnabled(False)
        self._worker = PipelineWorker(cfg)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_progress(self, stage: str, pct: float) -> None:
        self.progress.setValue(int(pct * 100))
        self.stage_label.setText(f"{stage}  ·  {pct * 100:.0f}%")
        self.log.appendPlainText(f"{stage} ({pct * 100:.0f}%)")

    def _on_done(self, result: object) -> None:
        assert isinstance(result, JobResult)
        self.run_btn.setEnabled(True)
        self.stage_label.setText(f"完成  ·  {result.cue_count} 条字幕")
        folder = result.output_mp4 or result.output_srt
        self._last_output = folder
        self.open_btn.setEnabled(True)
        extra = ""
        if result.missing_en:
            extra = f"\n英文缺失 {len(result.missing_en)} 条，见 report.json"
        QMessageBox.information(self, PRODUCT_ZH, f"已生成 {result.cue_count} 条字幕{extra}")

    def _on_fail(self, msg: str) -> None:
        self.run_btn.setEnabled(True)
        self.stage_label.setText("失败")
        self.log.appendPlainText(f"错误: {msg}")
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
    win.show()
    sys.exit(app.exec())
