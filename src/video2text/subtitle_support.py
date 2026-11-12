"""仅依赖标准库的字幕轨道选择、安全下载与解析。"""

import html
import http.cookiejar
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request


class SubtitleFetchError(Exception):
    """字幕获取失败；消息不含请求地址或凭据。"""


class SubtitleParseError(Exception):
    """字幕格式不支持或内容损坏。"""


_FORMATS = ("json", "json3", "srt", "vtt")
_LANGUAGES = ("ai-zh", "zh", "zh-CN", "zh-Hans", "zh-TW", "zh-Hant", "en", "ai-en")


def _https_url(url):
    if not isinstance(url, str):
        raise SubtitleFetchError("字幕地址无效")
    if url.startswith("//"):
        url = "https:" + url
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError
        parts.port
    except ValueError:
        raise SubtitleFetchError("字幕地址必须为无凭据的 HTTPS 地址") from None
    return url


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = _https_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            # 不复制来源请求的凭据；CookieProcessor 会按目标域重新匹配。
            for name in ("Cookie", "Cookie2", "Authorization", "Proxy-Authorization"):
                redirected.remove_header(name)
        return redirected


def _cookie_jar(cookiefile):
    policy = http.cookiejar.DefaultCookiePolicy(
        strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrict,
    )
    jar = http.cookiejar.MozillaCookieJar(policy=policy)
    if cookiefile is not None:
        try:
            jar.load(str(cookiefile), ignore_discard=True, ignore_expires=False)
        except (OSError, ValueError, http.cookiejar.LoadError):
            raise SubtitleFetchError("字幕 Cookie 文件无法读取") from None
    return jar


def fetch_subtitle(url, cookiefile=None, retries=2):
    """下载 HTTPS 字幕；retries 为额外重试次数，最多额外重试五次。"""
    url = _https_url(url)
    jar = _cookie_jar(cookiefile)
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), _SafeRedirectHandler(),
    )
    attempts = max(0, min(5, int(retries))) + 1
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": "video2text/1.0"})
        try:
            with opener.open(request, timeout=30) as response:
                _https_url(response.geturl())
                return response.read()
        except urllib.error.HTTPError as exc:
            retryable = exc.code in (408, 429) or 500 <= exc.code < 600
            exc.close()
            if not retryable or attempt == attempts - 1:
                raise SubtitleFetchError("字幕获取失败（HTTP 错误）") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            if attempt == attempts - 1:
                raise SubtitleFetchError("字幕获取失败（网络错误）") from None
    raise SubtitleFetchError("字幕获取失败")


def _eligible(item):
    if not isinstance(item, dict):
        return False
    # 不把弹幕或评论轨道误当成字幕；未知格式不列入候选。
    descriptor = " ".join(str(item.get(key, "")) for key in ("name", "ext", "url", "format_id"))
    if re.search(r"danmaku|comments?|弹幕|评论", descriptor, re.I):
        return False
    return str(item.get("ext") or "").lower() in _FORMATS + ("",)


def pick_track(subtitles, auto, prefer=None):
    """优先选择指定语言或中英文字幕，过滤非字幕及不支持的格式。"""
    tables = [table if isinstance(table, dict) else {} for table in (subtitles, auto)]
    languages = [prefer] if prefer else list(_LANGUAGES)
    if not prefer:
        languages += [lang for table in tables for lang in table if lang not in languages]
    for lang in languages:
        if re.search(r"danmaku|comments?|弹幕|评论", str(lang), re.I):
            continue
        for table in tables:
            items = [item for item in (table.get(lang) or []) if _eligible(item)]
            if items:
                return lang, items
    return None


def _number(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError
    return result


def _segment(start, end, text):
    start, end = _number(start), _number(end)
    if end < start or not isinstance(text, str):
        raise ValueError
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
    return (start, end, text) if text else None


def _json_segments(text):
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError
    out = []
    if "events" in data:
        events = data["events"]
        if not isinstance(events, list):
            raise ValueError
        for event in events:
            if not isinstance(event, dict):
                raise ValueError
            if "segs" not in event:
                continue
            start = _number(event.get("tStartMs", 0)) / 1000
            duration = _number(event.get("dDurationMs", 0)) / 1000
            content = "".join(seg.get("utf8", "") for seg in event["segs"])
            segment = _segment(start, start + duration, content)
            if segment:
                out.append(segment)
    else:
        key = "body" if "body" in data else "subtitles"
        if key not in data or not isinstance(data[key], list):
            raise ValueError
        for item in data[key]:
            start = item.get("from", item.get("start", 0))
            segment = _segment(start, item.get("to", item.get("end", start)),
                               item.get("content", item.get("text", "")))
            if segment:
                out.append(segment)
    return out


def _seconds(timestamp):
    parts = timestamp.replace(",", ".").split(":")
    if len(parts) not in (2, 3):
        raise ValueError
    seconds = float(parts[-1])
    minutes = int(parts[-2])
    if not 0 <= seconds < 60 or (len(parts) == 3 and not 0 <= minutes < 60):
        raise ValueError
    return _number((int(parts[0]) * 3600 if len(parts) == 3 else 0) + minutes * 60 + seconds)


def _timed_segments(text, vtt):
    out = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    pattern = r"((?:\d+:)?\d{2}:\d{2}[.,]\d+)\s*-->\s*((?:\d+:)?\d{2}:\d{2}[.,]\d+)"
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if vtt and lines and re.match(r"^(NOTE(?:\s|$)|STYLE$|REGION$)", lines[0]):
            continue
        index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if index is None:
            # 部分平台的 SRT 含孤立序号块；只忽略纯数字，不吞掉任意损坏正文。
            if not vtt and block.strip() and not block.strip().isdigit():
                raise ValueError
            continue
        match = re.match(pattern, lines[index].strip())
        if not match:
            # 上游可能生成 NaN/undefined 时间轴；跳过这一条，不丢整集字幕。
            if not vtt and re.search(r"(?i)\b(?:NaN|undefined)\b", lines[index]):
                continue
            raise ValueError
        # 异常时间行有时与上一条粘成同一块，不能把坏 cue 文本拼入上一条。
        content_lines = lines[index + 1:]
        bad_line = next((i for i, line in enumerate(content_lines) if "-->" in line), None)
        if bad_line is not None:
            content_lines = content_lines[:bad_line]
            if content_lines and content_lines[-1].strip().isdigit():
                content_lines.pop()
        segment = _segment(_seconds(match[1]), _seconds(match[2]), " ".join(content_lines))
        # 仅消除完全相同的 cue；不按文本去重，以保留真实重复句。
        if segment and (not out or segment != out[-1]):
            out.append(segment)
    return out


def _parse(raw, ext):
    try:
        text = raw.decode("utf-8-sig").strip()
        if not text:
            return []
        if ext in ("json", "json3") or text.startswith("{"):
            return _json_segments(text)
        if ext == "vtt" or text.startswith("WEBVTT"):
            if "-->" not in text and not text.startswith("WEBVTT"):
                raise ValueError
            return _timed_segments(text, True)
        if ext == "srt" or "-->" in text:
            return _timed_segments(text, False)
    except (ValueError, TypeError, AttributeError, KeyError, UnicodeError):
        raise SubtitleParseError("字幕内容损坏或格式不支持") from None
    raise SubtitleParseError("字幕格式不支持")


def parse_track_items(items, cookiefile=None, retries=2):
    """依次尝试支持的轨道；合法空字幕与下载/解析失败分别报告。"""
    empty = False
    fetched_error = parse_error = None
    for item in items:
        if not _eligible(item):
            parse_error = SubtitleParseError("字幕格式不支持")
            continue
        try:
            if "data" in item and item["data"] is not None:
                raw = item["data"]
                if isinstance(raw, str):
                    raw = raw.encode("utf-8")
                if not isinstance(raw, bytes):
                    raise SubtitleParseError("字幕内嵌内容格式不支持")
            elif item.get("url"):
                raw = fetch_subtitle(item["url"], cookiefile, retries)
            else:
                raise SubtitleFetchError("字幕轨道没有内容或下载地址")
            segments = _parse(raw, str(item.get("ext") or "").lower())
            if segments:
                return segments, "字幕解析成功"
            empty = True
        except SubtitleFetchError as exc:
            fetched_error = exc
        except SubtitleParseError as exc:
            parse_error = exc
    if empty or not items:
        return [], "字幕为空"
    if parse_error:
        raise parse_error
    if fetched_error:
        raise fetched_error
    raise SubtitleParseError("没有可解析的字幕轨道")
