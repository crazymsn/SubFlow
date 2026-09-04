from bilingual_sub.gui.progress import should_log_stage, stage_text
from bilingual_sub.i18n import set_locale


def test_transcribe_and_burn_stay_off_the_log():
    assert should_log_stage("transcribe", None) is False
    assert should_log_stage("transcribe", "extract") is False
    assert should_log_stage("burn", None) is False
    assert should_log_stage("done", "render") is False


def test_other_stages_log_once():
    assert should_log_stage("extract", None) is True
    assert should_log_stage("extract", "extract") is False
    assert should_log_stage("translate", "extract") is True
    set_locale("zh-Hans")
    assert stage_text("transcribe") == "语音识别"
    assert stage_text("burn") == "烧录视频"
    assert stage_text("ingest") == "下载视频"
    assert stage_text("dub") == "配音"
