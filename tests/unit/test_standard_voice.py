import httpx
import pytest

from bilingual_sub.adapters.tts.base import TtsRequest, select_tts
from bilingual_sub.adapters.tts.gptsovits import tts_job_fingerprint
from bilingual_sub.adapters.tts.qwen import QwenNativeTts, native_speaker


@pytest.mark.parametrize('language', ['zh', 'zh-Hant', 'en', 'ja', 'es', 'ru', 'fr', 'de'])
def test_standard_voice_ignores_missing_reference_and_sends_target(tmp_path, monkeypatch, pcm_wav, language):
    monkeypatch.setenv('SUBFLOW_GPTSOVITS_REF', str(tmp_path / 'deleted-reference.wav'))
    monkeypatch.setenv('SUBFLOW_GPTSOVITS_PROMPT', 'Chinese reference transcript')
    seen = []
    async def post(url, payload, control):
        seen.append(payload)
        return httpx.Response(200, content=pcm_wav(), headers={'Content-Type': 'audio/wav'})
    monkeypatch.setattr('bilingual_sub.adapters.tts.gptsovits._post_audio', post)
    provider = select_tts('qwen3-native', ref_audio=str(tmp_path / 'missing.wav'), prompt_text='old')
    provider.synth(TtsRequest('Hello.', language, '', tmp_path / 'voice.wav'))
    assert isinstance(provider, QwenNativeTts)
    assert provider.ref_audio == provider.prompt_text == ''
    assert seen[0]['ref_audio_path'] == seen[0]['prompt_text'] == ''
    assert seen[0]['speaker'] == native_speaker(language)
    assert seen[0]['text_lang'] == provider.language(language)


def test_native_cache_ignores_reference_but_distinguishes_voice(tmp_path):
    first = tts_job_fingerprint('qwen3-native', voice='Aiden', ref_audio=str(tmp_path/'missing.wav'))
    assert first == tts_job_fingerprint('qwen3-native', voice='Aiden')
    assert first != tts_job_fingerprint('qwen3-native', voice='Ryan')
    assert first != tts_job_fingerprint('qwen3', voice='Aiden')


def test_standard_preview_keeps_custom_endpoint_without_reference(tmp_path, monkeypatch, pcm_wav):
    from bilingual_sub.core.voice_preview import synth_voice_preview
    received = []
    monkeypatch.setattr('bilingual_sub.adapters.tts.qwen_runtime.ensure_running',
                        lambda endpoint, **kw: received.append((endpoint, kw)))
    monkeypatch.setattr(QwenNativeTts, 'synth', lambda self, req, **kw: req.dest.write_bytes(pcm_wav()))
    path = synth_voice_preview(provider='qwen3-native', lang='en', voice='Ryan',
        endpoint='http://127.0.0.1:19999', ref_audio=str(tmp_path/'missing.wav'), dest=tmp_path/'voice.wav')
    assert path.is_file()
    assert received[0][0] == 'http://127.0.0.1:19999'
    assert received[0][1]['native'] is True


def test_language_and_locale_switch_keep_valid_standard_speaker():
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.i18n import set_locale
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData('en'))
        win.tts_voice_edit.setCurrentIndex(win.tts_voice_edit.findData('Ryan'))
        assert win._preview_request().voice == 'Ryan'
        win._on_sovits_probe(True, '')
        assert 'Qwen3-TTS' in win.tts_sovits_status.text()
        assert '{engine}' not in win.tts_sovits_status.text()
        set_locale('en')
        win.retranslateUi()
        assert win._preview_request().voice == 'Ryan'
        win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData('ja'))
        assert win._preview_request().voice == 'Ryan'
        assert win.tts_voice_edit.findData('Ono_Anna') >= 0
        win.tts_combo.setCurrentIndex(win.tts_combo.findData('qwen3'))
        win.tts_prompt_edit.setText('参考录音原文')
        assert win._preview_request().prompt_text == '参考录音原文'
    finally:
        win.close()
        app.processEvents()
