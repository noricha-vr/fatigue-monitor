"""check.py のユニットテスト"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# check.py はルートにあるためパスを通す
sys.path.insert(0, str(Path(__file__).parent.parent))
import check


def _mock_audio_file(exists: bool) -> MagicMock:
    """ALERT_AUDIO_FILE の差し替え用モックを返す。"""
    m = MagicMock(spec=Path)
    m.exists.return_value = exists
    m.__str__ = lambda self: "/mock/alert.wav"
    return m


class TestNotifyTts(unittest.TestCase):
    def test_returns_false_when_file_missing(self):
        with patch("check.ALERT_AUDIO_FILE", _mock_audio_file(exists=False)):
            result = check.notify_tts()
        self.assertFalse(result)

    def test_returns_true_on_successful_playback(self):
        mock_file = _mock_audio_file(exists=True)
        with (
            patch("check.ALERT_AUDIO_FILE", mock_file),
            patch("check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = check.notify_tts()
        self.assertTrue(result)
        mock_run.assert_called_once_with(
            ["afplay", str(mock_file)], check=True, timeout=60
        )

    def test_returns_false_on_playback_error(self):
        with (
            patch("check.ALERT_AUDIO_FILE", _mock_audio_file(exists=True)),
            patch("check.subprocess.run", side_effect=Exception("afplay not found")),
        ):
            result = check.notify_tts()
        self.assertFalse(result)


class TestNotifyDiscord(unittest.TestCase):
    _stats = {
        "message_count": 10,
        "avg_prompt_length": 200,
        "session_duration_min": 30,
        "is_late_night": False,
        "sources": ["claude-code"],
    }

    def test_returns_false_when_url_not_set(self):
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": ""}):
            result = check.notify_discord(7.5, "tired", self._stats)
        self.assertFalse(result)

    def test_returns_false_when_url_invalid_prefix(self):
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": "https://example.com/hook"}):
            result = check.notify_discord(7.5, "tired", self._stats)
        self.assertFalse(result)

    def test_returns_true_on_success(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        valid_url = "https://discord.com/api/webhooks/123/abc"
        with (
            patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": valid_url}),
            patch("check.request.urlopen", return_value=mock_resp),
        ):
            result = check.notify_discord(7.5, "tired", self._stats)
        self.assertTrue(result)

    def test_returns_false_on_network_error(self):
        from urllib.error import URLError
        valid_url = "https://discord.com/api/webhooks/123/abc"
        with (
            patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": valid_url}),
            patch("check.request.urlopen", side_effect=URLError("timeout")),
        ):
            result = check.notify_discord(7.5, "tired", self._stats)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
