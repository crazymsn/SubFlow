import json
import re

import pytest

from bilingual_sub.config import load_style_preset
from bilingual_sub.core.render import render_ass_srt
from bilingual_sub.core.speech import prepare_dub_script, speech_phrases
from bilingual_sub.models import Cue


@pytest.mark.parametrize('mode', ['bilingual', 'enzh', 'single:en'])
@pytest.mark.parametrize('resolution', [(3456, 2160), (1920, 1080), (1080, 1920), (640, 360)])
def test_long_and_short_captions_have_constant_type(mode, resolution):
    cues = [Cue(0, 1, '大家好', 'Hello everyone'),
            Cue(1, 9, '今天分享网页分析工具的实际使用方法和操作过程。',
                'Today I will show you how to use the web analysis tool and walk through the entire process step by step.')]
    ass, srt = render_ass_srt(cues, load_style_preset('no-plate-large'), play_res=resolution,
                            mode=mode, target_lang='en', source_lang='zh')
    assert '\\fsc' not in ass
    fonts = {}
    for line in ass.splitlines():
        if line.startswith('Dialogue:'):
            style = line.split(',')[3]
            fonts.setdefault(style, set()).add(int(re.search(r'\\fs(\d+)', line)[1]))
    assert all(len(values) == 1 for values in fonts.values())
    assert 'step by step' in srt or 'stepbystep' in re.sub(r'\s+', '', srt)
    assert '00:00:09,000' in srt
    assert ass.count('Dialogue:') > (4 if mode != 'single:en' else 2)


def test_phrase_planning_keeps_text_and_respects_real_pauses():
    cues = [Cue(0, 1, '你好', 'Hello'), Cue(1, 2, '欢迎', 'Welcome'),
            Cue(4, 6, '继续', 'Continue')]
    phrases = speech_phrases(cues, 'en')
    assert [(c.start, c.end, c.en) for c in phrases] == [(0, 2, 'Hello Welcome'), (4, 6, 'Continue')]


def test_narration_rewrite_keeps_captions_in_sync_and_uses_time_budget():
    class Client:
        def chat_json(self, **kwargs):
            data = json.loads(kwargs['user'].split('Input data:\n', 1)[1])
            assert data[0]['seconds'] == 2 and data[0]['budget'] == 4
            return {'lines': ['Welcome back.']}
    source = Cue(0, 2, '欢迎回来', 'Welcome back to this video.')
    result, calls = prepare_dub_script([source], target_lang='en', source_lang='zh', model='fake', client=Client())
    assert calls == 1 and result[0].en == result[0].spoken == result[0].language_texts['en'] == 'Welcome back.'
    assert source.en == 'Welcome back to this video.'


def test_bad_spoken_draft_does_not_replace_original():
    class Client:
        def chat_json(self, **kwargs):return {'lines': ['看一下 this']}
    cue = Cue(0, 2, '看一下', 'Take a look.')
    result, _ = prepare_dub_script([cue], target_lang='en', source_lang='zh', model='fake', client=Client())
    assert result[0].spoken == 'Take a look.'
    assert cue.en == 'Take a look.'


def test_narration_splits_invalid_batches_and_preserves_order():
    sizes = []
    class Client:
        def chat_json(self, **kwargs):
            data = json.loads(kwargs['user'].split('Input data:\n', 1)[1])
            sizes.append(len(data))
            return {'lines': [] if len(data) > 1 else [data[0]['translation']]}
    cues = [Cue(i * 3, i * 3 + 1, str(i), f'Line {i}.') for i in range(10)]
    result, calls = prepare_dub_script(cues, target_lang='en', source_lang='zh', model='fake', client=Client())
    assert max(sizes) == 8 and calls == len(sizes)
    assert [c.spoken for c in result] == [c.en for c in cues]


def test_optional_narration_service_failure_keeps_completed_translation():
    from bilingual_sub.adapters.meding import MedingServiceError
    class Client:
        def chat_json(self, **kwargs):
            raise MedingServiceError('temporary outage')
    result, calls = prepare_dub_script([Cue(0, 2, '你好', 'Hello.')],
        target_lang='en', source_lang='zh', model='fake', client=Client())
    assert result[0].spoken == 'Hello.' and calls == 1
