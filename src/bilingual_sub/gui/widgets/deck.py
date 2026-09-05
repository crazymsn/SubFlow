from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bilingual_sub.adapters.whisper_backend import default_whisper_model
from bilingual_sub.core.langs import SINGLE_SUB_MODES, SOURCE_LANGS, SUB_LANGS
from bilingual_sub.gui.widgets.brand_check import BrandCheck
from bilingual_sub.gui.widgets.color_chip import ColorChip
from bilingual_sub.gui.widgets.field import FitScroll, expanding, field_col
from bilingual_sub.i18n import tr


def fill_voice_combo(combo: QComboBox) -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.blockSignals(False)


def _select_combo(combo: QComboBox, code: str) -> None:
    index = combo.findData(code)
    combo.setCurrentIndex(index if index >= 0 else 0)


def build_deck(win) -> QWidget:
    frame = QFrame()
    frame.setObjectName("deck")
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    shell = QVBoxLayout(frame)
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(0)

    scroll = FitScroll()
    scroll.setObjectName("formScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    viewport = scroll.viewport()
    viewport.setObjectName("formViewport")
    viewport.setAutoFillBackground(False)

    inner = QWidget()
    inner.setObjectName("formInner")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(18, 16, 18, 12)
    layout.setSpacing(10)

    win.lbl_source = win._field_label(tr("source"))
    win.lbl_target = win._field_label(tr("target"))
    win.lbl_mode = win._field_label(tr("mode"))
    for lab in (win.lbl_source, win.lbl_target, win.lbl_mode):
        lab.setWordWrap(False)

    win.source_lang_combo = QComboBox()
    for code, label in SOURCE_LANGS:
        win.source_lang_combo.addItem(label, code)
    _select_combo(win.source_lang_combo, "zh")
    win.target_lang_combo = QComboBox()
    for code, label in SUB_LANGS:
        win.target_lang_combo.addItem(label, code)
    _select_combo(win.target_lang_combo, "zh")
    win.mode_combo = QComboBox()
    win.mode_combo.addItem(tr("mode_bi"), "bilingual")
    win.mode_combo.addItem(tr("mode_enzh"), "enzh")
    for code, label in SINGLE_SUB_MODES:
        win.mode_combo.addItem(label, code)
    win.mode_combo.addItem(tr("mode_nf"), "netflix_single")
    win.mode_combo.setCurrentIndex(0)

    win.lbl_asr = win._field_label(tr("engine"))
    win.asr_backend_combo = QComboBox()
    win.asr_backend_combo.addItem(tr("engine_whisper"), "whisper")
    win.asr_backend_combo.addItem(tr("engine_whisperx"), "whisperx")
    win.asr_backend_combo.setCurrentIndex(0)
    win.rec_lab = win._field_label(tr("asr"))
    win.whisper_combo = QComboBox()
    win.whisper_combo.addItems(["tiny", "base", "small", "medium", "large"])
    win.whisper_combo.setCurrentText(default_whisper_model())
    win.burn_check = BrandCheck(tr("burn"))
    win.burn_check.setChecked(True)

    win._slot_source = field_col(win.lbl_source, expanding(win.source_lang_combo))
    win._slot_target = field_col(win.lbl_target, expanding(win.target_lang_combo))
    win._slot_mode = field_col(win.lbl_mode, expanding(win.mode_combo))
    win._slot_asr = field_col(win.lbl_asr, expanding(win.asr_backend_combo))
    win._slot_model = field_col(win.rec_lab, expanding(win.whisper_combo))
    burn_wrap = QWidget()
    burn_wrap.setObjectName("fieldCol")
    burn_col = QVBoxLayout(burn_wrap)
    burn_col.setContentsMargins(0, 0, 0, 0)
    burn_col.setSpacing(0)
    burn_col.addStretch(1)
    burn_col.addWidget(win.burn_check, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
    win._slot_burn = burn_wrap
    win._deck_slots = [
        win._slot_source,
        win._slot_target,
        win._slot_mode,
        win._slot_asr,
        win._slot_model,
        win._slot_burn,
    ]

    win.deck_grid = QGridLayout()
    win.deck_grid.setHorizontalSpacing(8)
    win.deck_grid.setVerticalSpacing(8)
    win._deck_wide = True
    apply_deck_width(win, True)
    layout.addLayout(win.deck_grid)

    win.lbl_api = win._field_label(tr("api"))
    win.key_edit = QLineEdit()
    win.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    win.key_edit.setPlaceholderText(tr("token_ph"))
    win.key_edit.setClearButtonEnabled(True)
    win.save_btn = QPushButton(tr("save_token"))
    win.save_btn.setObjectName("brandGhost")
    win.save_btn.setMinimumHeight(36)
    win.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.save_btn.clicked.connect(win._save_key)
    win.clear_key_btn = QPushButton(tr("clear_token"))
    win.clear_key_btn.setObjectName("brandGhost")
    win.clear_key_btn.setMinimumHeight(36)
    win.clear_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.clear_key_btn.clicked.connect(win._clear_key)
    win.api_portal_btn = QPushButton(tr("api_portal"))
    win.api_portal_btn.setObjectName("brandGhost")
    win.api_portal_btn.setMinimumHeight(36)
    win.api_portal_btn.clicked.connect(win._open_api_portal)

    win.model_combo = QComboBox()
    win.model_combo.setEditable(False)
    win.model_combo.setMaxVisibleItems(18)
    win.model_combo.setMinimumContentsLength(16)
    win.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    win.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    win.model_combo.setPlaceholderText(tr("model_ph"))
    win.model_combo.activated.connect(win._persist_model)
    win.fetch_models_btn = QPushButton(tr("fetch_models"))
    win.fetch_models_btn.setObjectName("ghost")
    win.fetch_models_btn.setMinimumHeight(36)
    win.fetch_models_btn.clicked.connect(win._refresh_models)
    win.lbl_model = win._field_label(tr("models"))
    win._section_labels["models"] = win.lbl_model

    key_row = QHBoxLayout()
    key_row.setSpacing(8)
    key_row.addWidget(field_col(win.lbl_api, expanding(win.key_edit)), 3)
    key_row.addWidget(win.save_btn, 0, Qt.AlignmentFlag.AlignBottom)
    key_row.addWidget(win.clear_key_btn, 0, Qt.AlignmentFlag.AlignBottom)
    key_row.addWidget(win.api_portal_btn, 0, Qt.AlignmentFlag.AlignBottom)
    key_row.addWidget(field_col(win.lbl_model, expanding(win.model_combo)), 3)
    key_row.addWidget(win.fetch_models_btn, 0, Qt.AlignmentFlag.AlignBottom)
    layout.addLayout(key_row)

    win.key_status = QLabel("")
    win.key_status.setObjectName("hint")
    win.key_status.setWordWrap(True)
    win.key_status.setVisible(False)
    layout.addWidget(win.key_status)

    win.asr_help = QLabel(tr("asr_help"))
    win.asr_help.setObjectName("help")
    win.asr_help.hide()

    win.more_btn = QToolButton()
    win.more_btn.setObjectName("moreToggle")
    win.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.more_btn.setCheckable(True)
    win.more_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    win.more_btn.setArrowType(Qt.ArrowType.RightArrow)
    win.more_btn.setText(tr("more"))
    win.more_btn.toggled.connect(win._toggle_more)
    layout.addWidget(win.more_btn, 0, Qt.AlignmentFlag.AlignLeft)
    layout.addWidget(build_more_drawer(win))

    scroll.setWidget(inner)
    shell.addWidget(scroll, 1)
    win.form_scroll = scroll
    return frame


def apply_deck_width(win, wide: bool) -> None:
    if getattr(win, "_deck_wide", None) == wide and win.deck_grid.count():
        return
    win._deck_wide = wide
    while win.deck_grid.count():
        win.deck_grid.takeAt(0)
    slots = win._deck_slots
    if wide:
        for index, slot in enumerate(slots):
            win.deck_grid.addWidget(slot, 0, index)
            win.deck_grid.setColumnStretch(index, 1)
        for index in range(6, win.deck_grid.columnCount()):
            win.deck_grid.setColumnStretch(index, 0)
    else:
        for index, slot in enumerate(slots[:3]):
            win.deck_grid.addWidget(slot, 0, index)
        for index, slot in enumerate(slots[3:]):
            win.deck_grid.addWidget(slot, 1, index)
        for index in range(3):
            win.deck_grid.setColumnStretch(index, 1)
        for index in range(3, 6):
            win.deck_grid.setColumnStretch(index, 0)


def build_more_drawer(win) -> QFrame:
    drawer = QFrame()
    drawer.setObjectName("moreBox")
    more = QGridLayout(drawer)
    more.setContentsMargins(0, 4, 0, 4)
    more.setHorizontalSpacing(12)
    more.setVerticalSpacing(10)
    rule = QFrame()
    rule.setObjectName("rule")
    rule.setFixedHeight(1)
    more.addWidget(rule, 0, 0, 1, 6)

    win.color_check = BrandCheck(tr("sub_color"))
    win.color_check.setChecked(False)
    win.color_check.toggled.connect(win._toggle_color)
    win.dub_check = BrandCheck(tr("dub"))
    win.dub_check.setChecked(False)
    win.dub_check.toggled.connect(win._toggle_dub)
    win.refine_check = BrandCheck(tr("refine"))
    win.refine_check.setChecked(False)
    checks = QHBoxLayout()
    checks.setContentsMargins(0, 0, 0, 0)
    checks.setSpacing(20)
    checks.addWidget(win.color_check, 0)
    checks.addWidget(win.dub_check, 0)
    checks.addWidget(win.refine_check, 0)
    checks.addStretch(1)
    more.addLayout(checks, 1, 0, 1, 6)

    win.color_box = QWidget()
    win.color_box.setObjectName("moreTrack")
    color_row = QHBoxLayout(win.color_box)
    color_row.setContentsMargins(0, 2, 0, 0)
    color_row.setSpacing(12)
    win.lbl_zh_color = win._field_label(tr("zh_color"))
    win.lbl_en_color = win._field_label(tr("en_color"))
    win.zh_color_btn = ColorChip("#FFFFFF", object_name="zhColorBtn")
    win.en_color_btn = ColorChip("#F2F2F2", object_name="enColorBtn")
    win.zh_color_btn.color_changed.connect(lambda hex_color: win._persist_sub_color("zh", hex_color))
    win.en_color_btn.color_changed.connect(lambda hex_color: win._persist_sub_color("en", hex_color))
    color_row.addWidget(field_col(win.lbl_zh_color, expanding(win.zh_color_btn)), 1)
    color_row.addWidget(field_col(win.lbl_en_color, expanding(win.en_color_btn)), 1)
    win.color_box.setVisible(False)
    more.addWidget(win.color_box, 2, 0, 1, 6)

    win.dub_box = QWidget()
    win.dub_box.setObjectName("moreTrack")
    dub = QVBoxLayout(win.dub_box)
    dub.setContentsMargins(0, 2, 0, 0)
    dub.setSpacing(8)
    rule = QFrame()
    rule.setObjectName("rule")
    rule.setFixedHeight(1)
    dub.addWidget(rule)
    win.lbl_tts = win._field_label(tr("tts_provider"))
    win.lbl_voice = win._field_label(tr("tts_voice"))
    win.lbl_endpoint = win._field_label(tr("tts_endpoint"))
    win.lbl_ref = win._field_label(tr("tts_ref_audio"))
    win.lbl_prompt = win._field_label(tr("tts_prompt"))
    win.lbl_preview = win._field_label(tr("tts_preview"))
    win.tts_combo = QComboBox()
    win.tts_combo.addItem("GPT-SoVITS", "gptsovits")
    win.tts_combo.currentIndexChanged.connect(win._sync_tts_fields)
    win.tts_voice_edit = QComboBox()
    win.tts_voice_edit.setEditable(False)
    fill_voice_combo(win.tts_voice_edit)
    win.tts_endpoint_edit = QLineEdit()
    win.tts_endpoint_edit.setPlaceholderText("http://127.0.0.1:9880")
    win.tts_endpoint_edit.editingFinished.connect(win._persist_sovits)
    win.tts_help = QLabel(tr("tts_help"))
    win.tts_help.setObjectName("help")
    win.tts_help.hide()
    win.tts_preview_btn = QPushButton(tr("tts_preview"))
    win.tts_preview_btn.setObjectName("ttsPreviewBtn")
    win.tts_preview_btn.setMinimumHeight(36)
    win.tts_preview_btn.setMinimumWidth(88)
    win.tts_preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.tts_preview_btn.clicked.connect(win._preview_voice)
    win.tts_ref_edit = QLineEdit()
    win.tts_ref_edit.setObjectName("ttsRefEdit")
    win.tts_ref_edit.setPlaceholderText("ref.wav")
    win.tts_ref_edit.editingFinished.connect(win._persist_sovits)
    win.tts_ref_btn = QPushButton(tr("browse"))
    win.tts_ref_btn.setObjectName("ghost")
    win.tts_ref_btn.setFixedHeight(36)
    win.tts_ref_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.tts_ref_btn.clicked.connect(win._browse_ref_audio)
    ref_row = QWidget()
    ref_lay = QHBoxLayout(ref_row)
    ref_lay.setContentsMargins(0, 0, 0, 0)
    ref_lay.setSpacing(8)
    ref_lay.addWidget(expanding(win.tts_ref_edit), 1)
    ref_lay.addWidget(win.tts_ref_btn, 0)
    win.tts_prompt_edit = QLineEdit()
    win.tts_prompt_edit.setObjectName("ttsPromptEdit")
    win.tts_prompt_edit.setPlaceholderText(tr("tts_prompt_ph"))
    win.tts_prompt_edit.editingFinished.connect(win._persist_sovits)
    win.tts_sovits_status = QLabel("")
    win.tts_sovits_status.setObjectName("help")
    win.tts_sovits_probe_btn = QPushButton(tr("tts_sovits_probe"))
    win.tts_sovits_probe_btn.setObjectName("ghost")
    win.tts_sovits_probe_btn.setFixedHeight(36)
    win.tts_sovits_probe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.tts_sovits_probe_btn.clicked.connect(win._probe_sovits)
    win.tts_sovits_start_btn = QPushButton(tr("tts_sovits_start"))
    win.tts_sovits_start_btn.setObjectName("ghost")
    win.tts_sovits_start_btn.setFixedHeight(36)
    win.tts_sovits_start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.tts_sovits_start_btn.clicked.connect(win._start_sovits)
    win._slot_tts = field_col(win.lbl_tts, expanding(win.tts_combo))
    win._slot_voice = field_col(win.lbl_voice, expanding(win.tts_voice_edit))
    win._slot_endpoint = field_col(win.lbl_endpoint, expanding(win.tts_endpoint_edit))
    win._slot_preview = field_col(win.lbl_preview, win.tts_preview_btn)
    win._slot_voice.hide()
    track = QHBoxLayout()
    track.setContentsMargins(0, 0, 0, 0)
    track.setSpacing(12)
    track.addWidget(win._slot_tts, 2)
    track.addWidget(win._slot_voice, 3)
    track.addWidget(win._slot_endpoint, 3)
    track.addWidget(win._slot_preview, 0)
    dub.addLayout(track)
    win.sovits_box = QWidget()
    win.sovits_box.setObjectName("moreTrack")
    sovits = QVBoxLayout(win.sovits_box)
    sovits.setContentsMargins(0, 8, 0, 0)
    sovits.setSpacing(8)
    ref_track = QHBoxLayout()
    ref_track.setContentsMargins(0, 0, 0, 0)
    ref_track.setSpacing(12)
    win._slot_ref = field_col(win.lbl_ref, expanding(ref_row))
    win._slot_prompt = field_col(win.lbl_prompt, expanding(win.tts_prompt_edit))
    ref_track.addWidget(win._slot_ref, 3)
    ref_track.addWidget(win._slot_prompt, 3)
    sovits.addLayout(ref_track)
    actions = QHBoxLayout()
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(8)
    actions.addWidget(win.tts_sovits_probe_btn, 0)
    actions.addWidget(win.tts_sovits_start_btn, 0)
    actions.addWidget(win.tts_sovits_status, 1)
    sovits.addLayout(actions)
    dub.addWidget(win.sovits_box)
    win.dub_box.setVisible(False)
    more.addWidget(win.dub_box, 4, 0, 1, 6)
    for col in range(6):
        more.setColumnStretch(col, 1)
    drawer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    drawer.hide()
    win.more_box = drawer
    return drawer
