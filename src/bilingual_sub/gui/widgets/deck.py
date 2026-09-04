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
from bilingual_sub.core.langs import SOURCE_LANGS, SUB_LANGS
from bilingual_sub.gui.widgets.brand_check import BrandCheck
from bilingual_sub.gui.widgets.field import FitScroll, expanding, field_col, path_row
from bilingual_sub.i18n import tr

OPENAI_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")


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
    win.source_lang_combo.setCurrentIndex(1)
    win.target_lang_combo = QComboBox()
    for code, label in SUB_LANGS:
        win.target_lang_combo.addItem(label, code)
    win.target_lang_combo.setCurrentIndex(2)
    win.mode_combo = QComboBox()
    win.mode_combo.addItem(tr("mode_bi"), "bilingual")
    win.mode_combo.addItem(tr("mode_nf"), "netflix_single")

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

    scroll.setWidget(inner)
    shell.addWidget(scroll, 1)

    foot = QWidget()
    foot.setObjectName("formInner")
    foot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    foot_l = QVBoxLayout(foot)
    foot_l.setContentsMargins(18, 0, 18, 10)
    foot_l.setSpacing(8)

    win.more_btn = QToolButton()
    win.more_btn.setObjectName("moreToggle")
    win.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.more_btn.setCheckable(True)
    win.more_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    win.more_btn.setArrowType(Qt.ArrowType.RightArrow)
    win.more_btn.setText(tr("more"))
    win.more_btn.toggled.connect(win._toggle_more)
    foot_l.addWidget(win.more_btn)
    foot_l.addWidget(build_more_drawer(win))
    shell.addWidget(foot, 0)
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

    win.refine_check = BrandCheck(tr("refine"))
    win.refine_check.setChecked(False)
    win.glossary_gen_check = BrandCheck(tr("glossary_gen"))
    win.glossary_gen_check.setChecked(False)
    win.dub_check = BrandCheck(tr("dub"))
    win.dub_check.setChecked(False)
    win.dub_check.toggled.connect(win._toggle_dub)
    more.addWidget(win.refine_check, 1, 0, 1, 2)
    more.addWidget(win.glossary_gen_check, 1, 2, 1, 2)
    more.addWidget(win.dub_check, 1, 4, 1, 2)

    win.glossary_edit = QLineEdit()
    win.glossary_edit.setPlaceholderText(tr("glossary_ph"))
    win.glossary_browse_btn = QPushButton(tr("browse"))
    win.glossary_browse_btn.setObjectName("ghost")
    win.glossary_browse_btn.setMinimumHeight(36)
    win.glossary_browse_btn.clicked.connect(win._browse_glossary)
    more.addWidget(field_col(win._section("glossary", tr("glossary")), path_row(win.glossary_edit, win.glossary_browse_btn)), 2, 0, 1, 6)

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
    hidden_dub = win._section("dub", tr("dub"))
    hidden_dub.hide()
    win.tts_combo = QComboBox()
    win.tts_combo.addItem("OpenAI", "openai")
    win.tts_combo.addItem("GPT-SoVITS", "gptsovits")
    win.tts_combo.currentIndexChanged.connect(win._sync_tts_fields)
    win.tts_voice_edit = QComboBox()
    win.tts_voice_edit.setEditable(False)
    for voice in OPENAI_VOICES:
        win.tts_voice_edit.addItem(voice, voice)
    win.tts_voice_edit.setCurrentIndex(0)
    win.tts_endpoint_edit = QLineEdit()
    win.tts_endpoint_edit.setPlaceholderText("http://127.0.0.1:9880")
    win.tts_help = QLabel(tr("tts_help"))
    win.tts_help.setObjectName("help")
    win.tts_help.hide()
    win._slot_tts = field_col(win.lbl_tts, expanding(win.tts_combo))
    win._slot_voice = field_col(win.lbl_voice, expanding(win.tts_voice_edit))
    win._slot_endpoint = field_col(win.lbl_endpoint, expanding(win.tts_endpoint_edit))
    win._slot_endpoint.hide()
    track = QHBoxLayout()
    track.setContentsMargins(0, 0, 0, 0)
    track.setSpacing(12)
    track.addWidget(win._slot_tts, 2)
    track.addWidget(win._slot_voice, 2)
    track.addWidget(win._slot_endpoint, 3)
    dub.addLayout(track)
    win.dub_box.setVisible(False)
    more.addWidget(win.dub_box, 3, 0, 1, 6)
    for col in range(6):
        more.setColumnStretch(col, 1)
    drawer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    drawer.hide()
    win.more_box = drawer
    return drawer
