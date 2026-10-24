import unittest
from media_mcp.subtitle.domain.online_subtitle import validate_online_subtitle, validate_online_translation_source


def srt(chinese_count, english_count):
    texts=['这是中文对白内容。']*chinese_count+['This is English dialogue.']*english_count
    return ''.join(f'{i}\n00:{i//60:02d}:{i%60:02d},000 --> 00:{i//60:02d}:{i%60:02d},900\n{text}\n\n' for i,text in enumerate(texts,1)).encode()


class SubtitleContentTests(unittest.TestCase):
    def test_sparse_chinese_credits_do_not_make_english_subtitles_chinese(self):
        with self.assertRaisesRegex(ValueError,'coverage too low'):
            validate_online_subtitle(srt(2,1999),'claimed.zh-CN.srt')

    def test_chinese_and_bilingual_dialogue_are_accepted(self):
        for chinese,english in ((10,0),(10,10)):
            result=validate_online_subtitle(srt(chinese,english),'movie.srt')
            self.assertGreaterEqual(result.profile['chinese_dialogue_coverage'],0.5)

    def test_english_still_valid_as_translation_source(self):
        result=validate_online_translation_source(srt(0,10),'movie.en.srt')
        self.assertEqual(result.profile['chinese_dialogue_coverage'],0)

    def test_ass_headers_and_style_names_are_not_dialogue(self):
        header='[Script Info]\nTitle: 这是中文字幕制作组测试信息\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        text=header+''.join(f'Dialogue: 0,0:00:{i:02d}.00,0:00:{i:02d}.90,中文样式,,0,0,0,,English dialogue {i}\n' for i in range(10))
        with self.assertRaisesRegex(ValueError,'enough Chinese'):
            validate_online_subtitle(text.encode(),'fake.zh.ass')

    def test_ass_bilingual_separate_tracks_are_accepted(self):
        header='[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        text=header+''.join(f'Dialogue: 0,0:00:{i:02d}.00,0:00:{i:02d}.90,Default,,0,0,0,,这是中文对白。\nDialogue: 0,0:00:{i:02d}.00,0:00:{i:02d}.90,English,,0,0,0,,English dialogue {i}\n' for i in range(10))
        result=validate_online_subtitle(text.encode(),'movie.ass')
        self.assertGreaterEqual(result.profile['chinese_dialogue_coverage'],0.5)
