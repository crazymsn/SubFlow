from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QToolButton, QWidget

from bilingual_sub.brand import PRODUCT_FULL, WINDOW_TITLE
from bilingual_sub.core.langs import UI_LOCALES
from bilingual_sub.gui.assets import HEADER_MARK_PX
from bilingual_sub.i18n import DEFAULT_LOCALE, set_locale, tr


def build_header(win) -> QHBoxLayout:
    header = QHBoxLayout()
    header.setSpacing(12)
    header.setContentsMargins(0, 0, 0, 0)

    win.logo_mark = QLabel()
    win.logo_mark.setObjectName("logoMark")
    win.logo_mark.setFixedSize(HEADER_MARK_PX, HEADER_MARK_PX)
    win.logo_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.logo_mark.setAccessibleName(WINDOW_TITLE)
    header.addWidget(win.logo_mark, alignment=Qt.AlignmentFlag.AlignVCenter)

    titles = QWidget()
    titles.setObjectName("headerTitles")
    title_col = QHBoxLayout(titles)
    title_col.setContentsMargins(0, 0, 0, 0)
    title_col.setSpacing(0)
    title = QLabel(PRODUCT_FULL)
    title.setObjectName("brandTitle")
    title_col.addWidget(title)
    header.addWidget(titles, alignment=Qt.AlignmentFlag.AlignVCenter)
    header.addStretch(1)

    win.theme_combo = QComboBox()
    win.theme_combo.setObjectName("themeCombo")
    win.theme_combo.setMinimumWidth(108)
    win.theme_combo.addItem(tr("theme_light"), "light")
    win.theme_combo.addItem(tr("theme_dark"), "dark")
    win.theme_combo.setCurrentIndex(0 if win._theme == "light" else 1)
    win.theme_combo.currentIndexChanged.connect(win._on_theme)

    win.locale_combo = QComboBox()
    win.locale_combo.setObjectName("localeCombo")
    win.locale_combo.setMinimumWidth(148)
    win.locale_combo.setAccessibleName(tr("ui_lang"))
    for code, label in UI_LOCALES:
        win.locale_combo.addItem(label, code)
    index = win.locale_combo.findData(DEFAULT_LOCALE)
    win.locale_combo.setCurrentIndex(index if index >= 0 else 0)
    set_locale(str(win.locale_combo.currentData() or DEFAULT_LOCALE))
    win.locale_combo.currentIndexChanged.connect(win._on_locale)

    cluster = QWidget()
    cluster.setObjectName("localeCluster")
    tools = QHBoxLayout(cluster)
    tools.setSpacing(8)
    tools.setContentsMargins(0, 0, 0, 0)
    tools.addWidget(win.theme_combo)
    tools.addWidget(win.locale_combo)
    header.addWidget(cluster, 0, Qt.AlignmentFlag.AlignVCenter)

    win.github_btn = QToolButton()
    win.github_btn.setObjectName("githubBtn")
    win.github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.github_btn.setAutoRaise(True)
    win.github_btn.setFixedSize(40, 40)
    win.github_btn.setToolTip("GitHub")
    win.github_btn.setAccessibleName("GitHub")
    win.github_btn.clicked.connect(win._open_github)
    header.addWidget(win.github_btn, 0, Qt.AlignmentFlag.AlignVCenter)
    return header
