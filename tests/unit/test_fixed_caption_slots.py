import re

import pytest

from bilingual_sub.config import load_style_preset
from bilingual_sub.core.render import (
    _page_parts,
    fixed_type_pages,
    render_ass_srt,
    resolve_play_layout,
)
from bilingual_sub.models import Cue


@pytest.mark.parametrize('mode', ['enzh', 'bilingual'])
def test_language_baseline_does_not_jump_when_counterpart_is_absent(mode):
    cues = [Cue(0, 2, '欢迎回来', 'Welcome back'), Cue(2, 4, '只有中文', ''), Cue(4, 6, '', 'Only English')]
    ass, _ = render_ass_srt(cues, load_style_preset('no-plate-large'), mode=mode, play_res=(1920, 1080))
    positions = {}
    sizes = {}
    for line in ass.splitlines():
        if line.startswith('Dialogue:'):
            fields = line.split(',', 9)
            positions.setdefault(fields[3], set()).add(re.search(r'\\pos\(([^)]+)\)', fields[9])[1])
            sizes.setdefault(fields[3], set()).add(re.search(r'\\fs(\d+)', fields[9])[1])
            assert r'\N' not in fields[9]
    assert all(len(values) == 1 for values in positions.values())
    assert all(len(values) == 1 for values in sizes.values())
    assert positions['CN'] != positions['EN']


def test_short_counterpart_stays_complete_across_long_translation_pages():
    cue = Cue(0, 8, '欢迎回来', 'Welcome back. Today we will explore the web crawler and its performance across several different websites.')
    preset = load_style_preset('no-plate-large')
    geo = resolve_play_layout(preset.style, (1920, 1080))
    pages = fixed_type_pages([cue], geo, 'enzh', 'zh', 'en', 'zh')
    assert len(pages) > 1
    assert all(page.zh == cue.zh for page in pages)
    assert ' '.join(page.en for page in pages) == cue.en
    assert pages[0].start == cue.start and pages[-1].end == cue.end
    assert all(a.end == b.start for a, b in zip(pages, pages[1:]))
    assert cue.words == [] and cue.en.endswith('websites.')


def test_balanced_wrapping_keeps_words_and_avoids_short_orphan_page():
    cfg = dict(size=40, bold=False, spacing=0, outline=2)
    text = 'Please open this webpage and read the entire article carefully.'
    lines = _page_parts(text, cfg, 600)
    assert ' '.join(lines) == text
    assert all(len(line.split()) >= 2 for line in lines)
    assert all(line.split()[-1].lower() not in {'the', 'a', 'an', 'and'} for line in lines)


def test_chinese_phrase_spaces_are_preferred_to_cutting_a_word():
    cfg = dict(size=40, bold=False, spacing=0, outline=2)
    text = '填录进来 点击开始对话 大家可以看到就会立即帮助我们整理网页内容'
    lines = _page_parts(text, cfg, 820)
    assert ''.join(''.join(lines).split()) == ''.join(text.split())
    assert all(not line.endswith('立') for line in lines)
