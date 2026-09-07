import pytest

from bilingual_sub.adapters.ytdlp import cookie_has_site_login, youtube_cookie_is_guest


@pytest.mark.parametrize(('site', 'session'), [('youtube.com', 'SID'), ('bilibili.com', 'SESSDATA')])
def test_netscape_httponly_session_is_recognized(tmp_path, site, session):
    jar = tmp_path/'cookies.txt'
    jar.write_text('# Netscape HTTP Cookie File\n'
                   f'#HttpOnly_.{site}\tTRUE\t/\tTRUE\t0\t{session}\tsynthetic-session\n'
                   f'.{site}\tTRUE\t/\tTRUE\t0\tPREF\tsynthetic-preference\n')
    assert cookie_has_site_login(jar, f'https://www.{site}/')
    if site == 'youtube.com':
        assert not youtube_cookie_is_guest(jar)


def test_plain_comment_cannot_impersonate_session(tmp_path):
    jar = tmp_path/'cookies.txt'
    jar.write_text('# .youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsynthetic-session\n'
                   '.youtube.com\tTRUE\t/\tTRUE\t0\tPREF\tsynthetic-preference\n')
    assert not cookie_has_site_login(jar, 'https://www.youtube.com/')
    assert youtube_cookie_is_guest(jar)
