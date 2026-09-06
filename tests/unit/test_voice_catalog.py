import httpx
import pytest

from bilingual_sub.adapters.tts.base import TtsRequest
from bilingual_sub.adapters.tts.qwen import (
    DESIGNED_VOICES,
    STANDARD_VOICES,
    QwenNativeTts,
    native_speaker,
    standard_voices,
)
from bilingual_sub.adapters.tts.qwen_runtime import runtime_device


def test_catalog_contains_real_model_speakers_with_gender():
    assert {v.name for v in STANDARD_VOICES if v.gender == 'female'} == {'Serena', 'Vivian', 'Ono_Anna', 'Sohee'}
    assert {v.name for v in STANDARD_VOICES if v.gender == 'male'} == {'Aiden', 'Ryan', 'Uncle_Fu', 'Dylan', 'Eric'}
    for language in ('zh', 'zh-Hant', 'en', 'ja', 'es', 'ru', 'fr', 'de'):
        assert len(standard_voices(language)) == 23
    assert standard_voices('zh-Hant')[0].language == 'zh'
    assert standard_voices('ja')[0].name == 'Ono_Anna'


def test_designed_assets_cover_every_target_without_aliasing_official_speakers():
    import hashlib
    import json
    import wave
    from pathlib import Path

    folder = Path(__file__).parents[2] / 'src/bilingual_sub/_data/bootstrap/voices'
    data = json.loads((folder / 'voices.json').read_text(encoding='utf-8'))
    assets = {item['id']: item for item in data['voices']}
    assert len(assets) == 14 and set(assets) == {v.name for v in DESIGNED_VOICES}
    assert set(assets).isdisjoint(v.name for v in STANDARD_VOICES)
    assert len({item['sha256'] for item in assets.values()}) == 14
    for language in ('zh', 'zh-Hant', 'en', 'ja', 'es', 'fr', 'de', 'ru'):
        voices = standard_voices(language)
        assert native_speaker(language) in {v.name for v in voices}
        family = language.split('-')[0]
        assert {v.gender for v in voices if v.designed and v.language == family} == {'male', 'female'}
    for name, item in assets.items():
        path = folder / item['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], name
        with wave.open(str(path)) as audio:
            assert 3 <= audio.getnframes() / audio.getframerate() <= 10
            assert audio.getnchannels() == 1 and audio.getsampwidth() == 2


@pytest.mark.parametrize('engine,device,expected', [
    ('qwen3-native', 'cuda:0', 'cuda:0'), ('qwen3', 'mps', 'mps'),
    ('qwen3-native', 'cpu', 'cpu'), ('other', 'cuda:0', ''),
    ('qwen3-native', 'unexpected device description', ''),
])
def test_device_status_reports_only_actual_qwen_runtime(monkeypatch, engine, device, expected):
    client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'engine': engine, 'device': device}))
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client(transport=transport, **kwargs))
    assert runtime_device('http://127.0.0.1:19882') == expected


@pytest.mark.parametrize('voice', STANDARD_VOICES, ids=lambda v: v.name)
def test_all_voice_ids_reach_synthesis_payload(tmp_path, monkeypatch, pcm_wav, voice):
    seen = []
    async def post(url, payload, control):
        seen.append(payload)
        return httpx.Response(200, content=pcm_wav(), headers={'Content-Type': 'audio/wav'})
    monkeypatch.setattr('bilingual_sub.adapters.tts.gptsovits._post_audio', post)
    QwenNativeTts().synth(TtsRequest('Hello.', 'en', voice.name, tmp_path/'voice.wav'))
    assert seen[0]['speaker'] == voice.name
    assert seen[0]['text_lang'] == 'English'


def test_gui_lists_both_genders_in_every_target_and_preserves_choice():
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.i18n import tr
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        for language in ('zh', 'zh-Hant', 'en', 'ja', 'es', 'ru', 'fr', 'de'):
            win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData(language))
            assert win.tts_voice_edit.count() == 24
            for voice in STANDARD_VOICES:
                index = win.tts_voice_edit.findData(voice.name)
                assert index > 0
                assert tr('tts_' + voice.gender) in win.tts_voice_edit.itemText(index)
            win.tts_voice_edit.setCurrentIndex(win.tts_voice_edit.findData('Serena'))
            assert win._preview_request().voice == 'Serena'
        for device, label in [('cuda:0', 'NVIDIA GPU'), ('mps', 'Apple GPU'), ('cpu', 'CPU')]:
            win._on_sovits_probe(True, device)
            assert label in win.tts_sovits_status.text()
    finally:
        win.close()
        app.processEvents()
