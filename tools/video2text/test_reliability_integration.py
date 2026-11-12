"""主入口可靠性回归；不接触实际数据或网络。"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('integration_v2t', Path(__file__).with_name('video2text.py'))
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)


class Reliability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cp = v.load_conf()
        self.options = dict(cp=self.cp, nocookie=True, force_whisper=False,
                            lang=None, model=None, outdir=self.root, keep_audio=True)
        self.probe = {'info': {'id': 'one', 'title': '课程', 'duration': 5},
                      'subtitles': {}, 'auto': {}}

    def test_default_no_subtitles_never_downloads(self):
        with patch.object(v, 'probe_subtitles', return_value=self.probe), patch.object(v, 'download_audio') as audio:
            result = v.convert('https://example.test/watch', **self.options)
        self.assertEqual(result['error_code'], 'no_subtitles')
        audio.assert_not_called()

    def test_parser_failure_auto_never_falls_back(self):
        from subtitle_support import SubtitleFetchError
        self.probe['subtitles'] = {'zh': [{'ext': 'srt', 'url': 'https://example.test/sub'}]}
        with patch.object(v, 'probe_subtitles', return_value=self.probe), \
                patch('subtitle_support.parse_track_items', side_effect=SubtitleFetchError('network')), \
                patch.object(v, 'download_audio') as audio:
            result = v.convert('https://example.test/watch', mode='auto', **self.options)
        self.assertEqual(result['error_code'], 'subtitle_fetch_failed')
        audio.assert_not_called()

    def test_probe_bounded_retry(self):
        with patch.object(v, 'probe_subtitles', side_effect=RuntimeError('private')) as probe:
            result = v.convert('https://example.test/watch', **self.options)
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(result['error_code'], 'probe_failed')
        self.assertNotIn('private', result['error'])

    def test_atomic_text_failure_keeps_old(self):
        target = self.root / 'transcript.txt'
        v.write_text(target, 'original')
        with patch.object(v.os, 'replace', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                v.write_text(target, 'replacement')
        self.assertEqual(target.read_text(), 'original')
        self.assertFalse(list(self.root.glob('.text-*.tmp')))

    def test_force_transcription_flag_reaches_convert(self):
        collection = {'id': 'test', 'title': '课程', 'episodes': [
            {'id': 'url-' + 'c' * 32, 'title': '一', 'url': 'https://example.test/1'}]}
        def convert(url, **kwargs):
            self.assertTrue(kwargs['refresh_transcription'])
            target = kwargs['target_dir'] / 'transcript.txt'
            v.write_text(target, '[00:00:01] 新转写\n')
            return {'ok': True, 'path': target}
        with patch.object(v, 'discover', return_value=collection), patch.object(v, 'convert', side_effect=convert):
            self.assertTrue(v.process('https://example.test/list', refresh=True, **self.options)['ok'])

    def test_only_failed_not_new(self):
        collection = {'id': 'test', 'title': '课程', 'episodes': [
            {'id': 'url-' + 'a' * 32, 'title': '一', 'url': 'https://example.test/1'}]}
        opts = dict(self.options)
        def convert(url, **kwargs):
            target = kwargs['target_dir'] / 'transcript.txt'
            v.write_text(target, '[00:00:01] 好\n')
            return {'ok': True, 'path': target}
        with patch.object(v, 'discover', return_value=collection), patch.object(v, 'convert', side_effect=convert):
            self.assertEqual(v.process('https://example.test/list', **opts)['completed'], 1)
            collection['episodes'].append({'id': 'url-' + 'b' * 32, 'title': '二', 'url': 'https://example.test/2'})
            self.assertEqual(v.process('https://example.test/list', only_failed=True, **opts)['completed'], 0)
            self.assertEqual(v.process('https://example.test/list', only_failed=True, **opts)['completed'], 0)
            self.assertEqual(v.process('https://example.test/list', **opts)['completed'], 1)


if __name__ == '__main__':
    unittest.main()
