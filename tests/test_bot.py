import contextlib
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

import my_discord_bot as bot


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous_cwd = Path.cwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, previous_cwd)
        self.environment = patch.dict(os.environ, {"MAX_ENTRIES_PER_RSS": "1"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        Path("feed.xml").write_text(
            '<?xml version="1.0"?><rss version="2.0"><channel>'
            '<title>Test feed</title><link>https://example.com</link>'
            '<description>Test</description><item><title>Article</title>'
            '<link>https://example.com/article</link>'
            '<description>&lt;p&gt;Hello &amp;amp; goodbye&lt;/p&gt;</description>'
            '<pubDate>Tue, 24 Feb 2026 12:00:00 GMT</pubDate>'
            '</item></channel></rss>',
            encoding="utf-8",
        )
        Path("feeds.txt").write_text("# comment\n\nfeed.xml\n", encoding="utf-8")

    def run_bot(self, **environment):
        with (
            patch.dict(os.environ, environment),
            patch.object(sys, "argv", ["my-discord-bot", "feeds.txt", "https://discord.com/api/webhooks/test"]),
        ):
            return bot.main()

    def entries(self):
        with contextlib.closing(sqlite3.connect("sent_entries.db")) as conn:
            return conn.execute("SELECT url FROM sent_entries").fetchall()

    def test_embed_preserves_clean_text_and_utc_timestamp(self):
        entry = bot.feedparser.parse("feed.xml").entries[0]
        embed = bot.entry_to_embed(entry, "Test feed", 42)
        self.assertEqual(embed["title"], "Article")
        self.assertEqual(embed["description"], "Hello & goodbye")
        self.assertEqual(embed["timestamp"], "2026-02-24T12:00:00+00:00")
        self.assertEqual(embed["footer"], {"text": "Test feed"})

    def test_development_mode_records_entry_without_posting(self):
        with patch.object(bot.requests, "post") as post:
            self.assertEqual(self.run_bot(MODE="1"), 0)
        post.assert_not_called()
        self.assertEqual(self.entries(), [("https://example.com/article",)])

    def test_production_posts_once_and_reports_duplicate_on_second_run(self):
        output = io.StringIO()
        with (
            patch.object(bot.requests, "post", return_value=Mock(status_code=204)) as post,
            patch.object(bot.time, "sleep"),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(self.run_bot(GITHUB_ACTIONS="true"), 0)
            self.assertEqual(self.run_bot(GITHUB_ACTIONS="true"), 0)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["timeout"], 10)
        self.assertEqual(post.call_args.kwargs["json"]["embeds"][0]["title"], "Article")
        self.assertIn("| Test feed | 1 | 1 | 1 | 0 | 1 | 0 |", output.getvalue())
        self.assertIn("| Test feed | 1 | 1 | 0 | 1 | 0 | 0 |", output.getvalue())
        self.assertIn("## Duplicate Entries", output.getvalue())

    def test_rate_limit_retries_then_records_success(self):
        limited = Mock(status_code=429)
        limited.json.return_value = {"retry_after": 2}
        with (
            patch.object(bot.requests, "post", side_effect=[limited, Mock(status_code=204)]) as post,
            patch.object(bot.time, "sleep") as sleep,
        ):
            self.assertEqual(self.run_bot(), 0)
        self.assertEqual(post.call_count, 2)
        sleep.assert_any_call(2.0)
        self.assertEqual(self.entries(), [("https://example.com/article",)])

    def test_delivery_failure_leaves_entry_available_for_retry(self):
        with (
            patch.object(bot.requests, "post", side_effect=requests.RequestException("unavailable")),
            patch.object(bot.time, "sleep"),
        ):
            self.assertEqual(self.run_bot(), 0)
        self.assertEqual(self.entries(), [])

    def test_invalid_modes_are_rejected_before_database_creation(self):
        for mode in ("invalid", "0", "3"):
            with self.subTest(mode=mode), self.assertLogs(bot.logger, level="ERROR"):
                self.assertEqual(self.run_bot(MODE=mode), 1)
        self.assertFalse(Path("sent_entries.db").exists())

    def test_invalid_entry_limit_is_rejected(self):
        for limit in ("invalid", "0", "-1"):
            with self.subTest(limit=limit), self.assertLogs(bot.logger, level="ERROR"):
                self.assertEqual(self.run_bot(MAX_ENTRIES_PER_RSS=limit), 1)
        self.assertFalse(Path("sent_entries.db").exists())

    def test_database_connection_is_closed_after_processing(self):
        connect = sqlite3.connect
        connections = []

        def capture_connection(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connections.append(connection)
            self.addCleanup(connection.close)
            return connection

        with patch.object(bot.sqlite3, "connect", side_effect=capture_connection):
            self.assertEqual(self.run_bot(MODE="1"), 0)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
