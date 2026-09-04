import pytest

from bilingual_sub.i18n import set_locale


@pytest.fixture(autouse=True)
def _reset_ui_locale():
    set_locale("zh-Hans")
    yield
    set_locale("zh-Hans")
