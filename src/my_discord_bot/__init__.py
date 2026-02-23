from __future__ import annotations

import sys
import os
import re
import html
import random
import time
import calendar
import logging
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

import requests
import feedparser


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


class Mode(Enum):
    DEVELOPMENT = 1
    PRODUCTION = 2


@dataclass
class DuplicateEntry:
    url: str
    delivered: datetime
    sql_error: str


@dataclass
class FeedStats:
    feed_name: str
    available: int = 0
    selected: int = 0
    new: int = 0
    duplicate: int = 0
    posted: int = 0
    failed: int = 0
    duplicates: list[DuplicateEntry] = field(default_factory=list)


def strip_html(text: str) -> str:
    """Strip HTML tags and unescape HTML entities."""
    cleaned = re.sub(r"<[^>]+>", "", html.unescape(text))
    return cleaned.strip()


def entry_to_embed(
    entry: Any,
    feed_title: str,
    color: int,
) -> dict[str, object]:
    """Convert a feedparser entry to a Discord embed dict."""
    # Build description from summary, stripped of HTML
    raw_desc: str = str(entry.get("summary", "") or "")
    description = strip_html(raw_desc)[:300]

    embed: dict[str, object] = {
        "title": (entry.get("title", "Untitled") or "Untitled")[:256],
        "url": entry.get("link", ""),
        "description": description,
        "color": color,
        "footer": {"text": feed_title[:2048]},
    }

    # Add timestamp if publication date is available
    published_parsed: Any = entry.get("published_parsed")
    if published_parsed:
        try:
            ts: int = calendar.timegm(tuple(published_parsed))
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            embed["timestamp"] = dt.isoformat()
        except (ValueError, OSError, OverflowError):
            pass

    # Add author if available
    author = entry.get("author")
    if author:
        embed["author"] = {"name": str(author)[:256]}

    return embed


def feed_title_to_color(title: str) -> int:
    """Generate a deterministic color from a feed title."""
    return hash(title) & 0xFFFFFF


def main() -> int:
    # Parse mode from environment
    running_mode_str: str | None = os.getenv("MODE")
    if running_mode_str is None:
        running_mode = Mode.PRODUCTION
    else:
        try:
            running_mode_val = int(running_mode_str)
        except ValueError:
            logger.error(
                "MODE must be an integer (1=DEVELOPMENT, 2=PRODUCTION), got: %s",
                running_mode_str,
            )
            return 1

        valid_values = [mode.value for mode in Mode]
        if running_mode_val not in valid_values:
            logger.error(
                "MODE must be one of %s, got: %d", valid_values, running_mode_val
            )
            return 1
        running_mode = Mode(running_mode_val)

    # Read CLI arguments
    if len(sys.argv) < 3:
        print(
            "Usage: my-discord-bot <rss_links_file> <discord_webhook_url>",
            file=sys.stderr,
        )
        return 1

    rss_links_file: str = sys.argv[1]
    discord_webhook_url: str = sys.argv[2]

    # Read RSS links from file (strip whitespace, skip blank lines and comments)
    try:
        with open(rss_links_file, "r", encoding="utf-8") as f:
            rss_links: list[str] = [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    except FileNotFoundError:
        logger.error("RSS links file not found: %s", rss_links_file)
        return 1

    if not rss_links:
        logger.error("No RSS links found in %s", rss_links_file)
        return 1

    # Read MAX_ENTRIES_PER_RSS from environment (default: 5)
    try:
        max_entries_per_rss: int = int(os.getenv("MAX_ENTRIES_PER_RSS", "5"))
    except ValueError:
        logger.error("MAX_ENTRIES_PER_RSS must be an integer")
        return 1

    if max_entries_per_rss <= 0:
        logger.error(
            "MAX_ENTRIES_PER_RSS must be greater than 0, got: %d", max_entries_per_rss
        )
        return 1

    # Validate webhook URL in production
    if running_mode == Mode.PRODUCTION:
        if not discord_webhook_url.startswith("https://discord.com/api/webhooks/"):
            logger.error(
                "discord_webhook_url must start with https://discord.com/api/webhooks/"
            )
            return 1

    # Connect to database with context manager
    dbname: str = "sent_entries.db"
    all_feed_stats: list[FeedStats] = []

    with sqlite3.connect(dbname) as conn:
        c = conn.cursor()

        # Create table if it doesn't exist (PRIMARY KEY implies UNIQUE)
        c.execute(
            "CREATE TABLE IF NOT EXISTS sent_entries"
            " (url TEXT PRIMARY KEY, delivered TIMESTAMP)"
        )
        conn.commit()

        # Process each RSS feed
        for rss_link in rss_links:
            data: Any = feedparser.parse(rss_link)
            feed_title: str = str(
                data.feed.get("title", rss_link) if data.feed else rss_link
            )

            stats = FeedStats(feed_name=feed_title)
            all_feed_stats.append(stats)

            # Check for feed parse errors
            if data.bozo and not data.entries:
                logger.warning(
                    "Failed to parse feed %s: %s",
                    rss_link,
                    data.bozo_exception,
                )
                continue

            stats.available = len(data.entries)

            if not data.entries:
                logger.info("No entries in feed: %s", rss_link)
                continue

            # Safely sample entries (clamp to feed size)
            sample_count: int = min(
                len(data.entries),
                random.randint(1, max(1, max_entries_per_rss)),
            )
            random_entries = random.sample(data.entries, sample_count)
            stats.selected = len(random_entries)

            color: int = feed_title_to_color(feed_title)

            for entry in random_entries:
                entry_link: str = str(entry.get("link", ""))
                if not entry_link:
                    logger.warning(
                        "Skipping entry with no link in feed: %s", feed_title
                    )
                    continue

                # Deduplicate using INSERT OR IGNORE
                now = datetime.now(timezone.utc)
                c.execute(
                    "INSERT OR IGNORE INTO sent_entries (url, delivered) VALUES (?, ?)",
                    (entry_link, now.isoformat()),
                )

                if c.rowcount == 0:
                    # Entry already exists in DB — it's a duplicate
                    stats.duplicate += 1
                    stats.duplicates.append(
                        DuplicateEntry(
                            url=entry_link, delivered=now, sql_error="duplicate"
                        )
                    )
                    logger.debug("Duplicate entry: %s", entry_link)
                    continue

                stats.new += 1

                if running_mode == Mode.DEVELOPMENT:
                    embed = entry_to_embed(entry, feed_title, color)
                    logger.info("Would post embed: %s", embed)
                    continue

                # Production: send Discord embed
                json_data: dict[str, object] = {
                    "embeds": [entry_to_embed(entry, feed_title, color)]
                }

                try:
                    resp = requests.post(
                        discord_webhook_url, json=json_data, timeout=10
                    )
                    if resp.status_code == 429:
                        try:
                            retry_after = resp.json().get("retry_after", 5)
                        except (ValueError, KeyError):
                            retry_after = 5
                        logger.warning("Rate limited, sleeping %ss", retry_after)
                        time.sleep(float(retry_after))
                        # Retry once
                        resp = requests.post(
                            discord_webhook_url, json=json_data, timeout=10
                        )
                    resp.raise_for_status()
                    stats.posted += 1
                except requests.RequestException as e:
                    logger.error("Failed to post entry %s: %s", entry_link, e)
                    stats.failed += 1
                    # Delete the DB row so this entry gets retried next run
                    c.execute("DELETE FROM sent_entries WHERE url = ?", (entry_link,))

                # Sleep for 1 second to respect Discord rate limits
                time.sleep(1)

            conn.commit()

        # Development mode: dump database contents
        if running_mode == Mode.DEVELOPMENT:
            logger.info("=== Database contents ===")
            c.execute("SELECT * FROM sent_entries")
            for row in c.fetchall():
                logger.info("  %s", row)

    # GitHub Actions step summary
    if running_mode == Mode.PRODUCTION and os.getenv("GITHUB_ACTIONS") == "true":
        # Per-feed summary table
        print("## RSS Feed Summary\n")
        print("| Feed | Available | Selected | New | Duplicate | Posted | Failed |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for stats in all_feed_stats:
            print(
                f"| {stats.feed_name} | {stats.available} | {stats.selected} "
                f"| {stats.new} | {stats.duplicate} | {stats.posted} | {stats.failed} |"
            )

        # Duplicate entries detail
        all_duplicates = [d for s in all_feed_stats for d in s.duplicates]
        if all_duplicates:
            print("\n## Duplicate Entries\n")
            print("| URL | Delivered |")
            print("| --- | --- |")
            for entry in all_duplicates:
                print(f"| {entry.url} | {entry.delivered} |")

    return 0
