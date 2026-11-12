"""字幕支持模块的离线安全与解析回归测试。"""

import http.cookiejar
import io
import time
import unittest
import urllib.error
import urllib.request
from email.message import Message
from unittest.mock import patch
from urllib.response import addinfourl

import subtitle_support as support


def cookie(domain, name, path="/", expires=None, domain_cookie=True):
    return http.cookiejar.Cookie(
        0, name, "secret", None, False, domain, domain_cookie,
        domain.startswith("."), path, True, True, expires, False,
        None, None, {}, False,
    )


class FakeHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, routes):
        super().__init__()
        self.routes = routes
        self.requests = []

    def https_open(self, request):
        self.requests.append(request)
        status, location, data = self.routes[request.full_url]
        headers = Message()
        if location:
            headers["Location"] = location
        response = addinfourl(io.BytesIO(data), headers, request.full_url, status)
        response.msg = "离线测试"
        return response


class FetchTests(unittest.TestCase):
    def test_cookie_domain_path_expiry_and_redirect(self):
        jar = support._cookie_jar(None)
        for item in (
            cookie(".bilibili.com", "valid"),
            cookie(".bilibili.com", "wrongpath", "/private"),
            cookie(".bilibili.com", "expired", expires=int(time.time()) - 60),
            cookie("bilibili.com", "hostonly", domain_cookie=False),
        ):
            jar.set_cookie(item)
        transport = FakeHTTPS({
            "https://www.bilibili.com/sub": (302, "https://subtitle.example/sub", b""),
            "https://subtitle.example/sub": (200, None, b"result"),
            "https://bilibili.com.evil.example/sub": (200, None, b"safe"),
        })
        original = urllib.request.build_opener

        def opener(*handlers):
            return original(urllib.request.ProxyHandler({}), transport, *handlers)

        with patch.object(support, "_cookie_jar", return_value=jar), patch.object(
            support.urllib.request, "build_opener", side_effect=opener
        ):
            self.assertEqual(support.fetch_subtitle("https://www.bilibili.com/sub"), b"result")
            support.fetch_subtitle("https://bilibili.com.evil.example/sub")
        self.assertEqual(transport.requests[0].get_header("Cookie"), "valid=secret")
        self.assertIsNone(transport.requests[1].get_header("Cookie"))
        self.assertIsNone(transport.requests[2].get_header("Cookie"))

    def test_mozilla_load_and_policy(self):
        def load(jar, filename, ignore_discard, ignore_expires):
            self.assertEqual(filename, "mock-cookie-file")
            self.assertTrue(ignore_discard)
            self.assertFalse(ignore_expires)

        with patch.object(http.cookiejar.MozillaCookieJar, "load", autospec=True, side_effect=load):
            jar = support._cookie_jar("mock-cookie-file")
        self.assertIsInstance(jar, http.cookiejar.MozillaCookieJar)

    def test_https_and_redirect_downgrade(self):
        for url in ("http://example.com/sub", "https://user:password@example.com/sub", "file:///secret"):
            with self.assertRaises(support.SubtitleFetchError):
                support.fetch_subtitle(url)
        request = urllib.request.Request("https://www.bilibili.com/sub", headers={"Cookie": "secret"})
        handler = support._SafeRedirectHandler()
        result = handler.redirect_request(request, None, 302, "", {}, "https://example.com/sub")
        self.assertIsNone(result.get_header("Cookie"))
        with self.assertRaises(support.SubtitleFetchError):
            handler.redirect_request(request, None, 302, "", {}, "http://example.com/sub")

    def test_bounded_retry_and_sanitized_errors(self):
        with patch.object(support.urllib.request, "build_opener") as build:
            build.return_value.open.side_effect = urllib.error.URLError("token=SECRET")
            with self.assertRaises(support.SubtitleFetchError) as error:
                support.fetch_subtitle("https://example.com/sub?token=SECRET", retries=2)
            self.assertEqual(build.return_value.open.call_count, 3)
            self.assertNotIn("SECRET", str(error.exception))
            build.return_value.open.reset_mock()
            with self.assertRaises(support.SubtitleFetchError):
                support.fetch_subtitle("https://example.com/sub", retries=100)
            self.assertEqual(build.return_value.open.call_count, 6)

    def test_http_client_error_not_retried(self):
        with patch.object(support.urllib.request, "build_opener") as build:
            build.return_value.open.side_effect = urllib.error.HTTPError(
                "https://example.com/?secret", 403, "secret", {}, None,
            )
            with self.assertRaises(support.SubtitleFetchError):
                support.fetch_subtitle("https://example.com/sub")
            self.assertEqual(build.return_value.open.call_count, 1)


class ParseTests(unittest.TestCase):
    def parse(self, ext, data):
        return support.parse_track_items([{"ext": ext, "data": data}])[0]

    def test_bilibili(self):
        self.assertEqual(self.parse("json", '{"body":[{"from":0,"to":2,"content":"你好"}]}'),
                         [(0.0, 2.0, "你好")])

    def test_json3(self):
        data = '{"events":[{"tStartMs":100,"dDurationMs":900,"segs":[{"utf8":"你"},{"utf8":"好"}]}]}'
        self.assertEqual(self.parse("json3", data), [(0.1, 1.0, "你好")])

    def test_srt(self):
        self.assertEqual(self.parse("srt", "1\r\n00:00:01,000 --> 00:00:02,500\r\n<b>你好</b> &amp; 再见\r\n"),
                         [(1.0, 2.5, "你好 & 再见")])

    def test_srt_orphan_sequence_and_invalid_timestamp_cue(self):
        text = ("1\n00:00:01,000 --> 00:00:02,000\n第一句\n\n"
                "2\n00:00:03,000 --> 00:00:NaN,undefined\n坏时间\n\n"
                "3\n00:00:04,000 --> 00:00:05,000\n第三句\n\n4\n")
        self.assertEqual(self.parse("srt", text), [(1.0, 2.0, "第一句"), (4.0, 5.0, "第三句")])
        with self.assertRaises(support.SubtitleParseError):
            self.parse("srt", "1\n00:00:01,000 --> BAD\n不能掩盖未知错误")
        glued = ("1\n00:00:01,000 --> 00:00:02,000\n第一句\n"
                 "2\n00:00:NaN,undefined --> 00:00:04,000\n坏时间\n\n"
                 "3\n00:00:05,000 --> 00:00:06,000\n第三句")
        self.assertEqual(self.parse("srt", glued), [(1.0, 2.0, "第一句"), (5.0, 6.0, "第三句")])

    def test_vtt_short_timestamps_and_repeated_sentence(self):
        text = "WEBVTT\n\ncue\n00:01.000 --> 00:02.000 align:start\n再说一次\n\n00:03.000 --> 00:04.000\n再说一次\n"
        self.assertEqual(self.parse("vtt", text), [(1.0, 2.0, "再说一次"), (3.0, 4.0, "再说一次")])

    def test_empty_supported_formats(self):
        for ext, text in (("json", '{"body":[]}'), ("json3", '{"events":[]}'),
                          ("vtt", "WEBVTT\n\n"), ("srt", "")):
            with self.subTest(ext=ext):
                self.assertEqual(support.parse_track_items([{"ext": ext, "data": text}]), ([], "字幕为空"))

    def test_bad_formats_and_negative_times(self):
        for ext, text in (("json", "{"), ("json", "{}"), ("json3", '{"events":null}'),
                          ("xml", "<xml/>"), ("vtt", "nonsense"), ("srt", "nonsense"),
                          ("json", '{"body":[{"from":-1,"to":2,"content":"坏"}]}')):
            with self.subTest(ext=ext, text=text):
                with self.assertRaises(support.SubtitleParseError):
                    self.parse(ext, text)

    def test_fetch_error_distinct_from_parse_error(self):
        with patch.object(support, "fetch_subtitle", side_effect=support.SubtitleFetchError("字幕获取失败")):
            with self.assertRaises(support.SubtitleFetchError):
                support.parse_track_items([{"ext": "json", "url": "https://example.com/sub"}])

    def test_fallback_after_bad_item(self):
        items = [{"ext": "json", "data": "bad"}, {"ext": "json", "data": '{"body":[]}'},
                 {"ext": "srt", "data": "1\n00:00:00,000 --> 00:00:01,000\n成功"}]
        self.assertEqual(support.parse_track_items(items)[0], [(0.0, 1.0, "成功")])

    def test_pick_language_and_exclude_comments(self):
        comments = [{"ext": "xml", "url": "https://example.com/danmaku"}]
        chinese = [{"ext": "json", "data": '{"body":[]}'}]
        english = [{"ext": "vtt", "data": "WEBVTT"}]
        subtitles = {"danmaku": chinese, "zh": comments, "en": english}
        self.assertEqual(support.pick_track(subtitles, {"ai-zh": chinese}), ("ai-zh", chinese))
        self.assertEqual(support.pick_track(subtitles, {}, "en"), ("en", english))
        self.assertIsNone(support.pick_track(subtitles, {}, "zh"))
        self.assertIsNone(support.pick_track({"comments": chinese}, {}))
        self.assertIsNone(support.pick_track({"zh": [{"ext": "json", "name": "评论"}]}, {}))


if __name__ == "__main__":
    unittest.main()
