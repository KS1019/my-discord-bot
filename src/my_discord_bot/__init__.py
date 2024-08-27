import sys
import os
import random
import time
import datetime
from enum import Enum
from datetime import timezone
from dataclasses import dataclass
import sqlite3
import requests
import feedparser


class MODE(Enum):
    DEVELOPMENT = 1
    PRODUCTION = 2


# Dataclass for the duplicate entries information
@dataclass
class DuplicateEntry:
    url: str
    delivered: datetime.datetime
    sqlError: str


def main() -> int:
    # Check if `MODE` environment variable is set to `PRODUCTION`
    running_mode = os.getenv("MODE")
    if running_mode is None:
        # Default to PRODUCTION
        running_mode = MODE.PRODUCTION
    else:
        running_mode = int(running_mode)
        # Assert that running_mode can be an instance of MODE
        # and it is within the range of MODE
        assert running_mode in [
            mode.value for mode in MODE
        ], "MODE must be set within the range of MODE."
        # Parse the value to Enum
        running_mode = MODE(int(running_mode))

    # Read a file name containing the links
    if len(sys.argv) < 3:
        print("Usage: uv run my_discord_bot <rss_links_file> <discord_webhook_url>")
        sys.exit(1)

    rss_links_file = sys.argv[1]
    # Open the file and put the links to list
    with open(rss_links_file, "r", encoding="utf-8") as f:
        rss_links = f.readlines()

    # Check if rss_links is not empty
    if not rss_links:
        print("The file is empty.")
        sys.exit(1)

    # Read MAX_ENTRIES_PER_RSS from the environment variable
    # If not found, set the default value to 5
    MAX_ENTRIES_PER_RSS = int(os.getenv("MAX_ENTRIES_PER_RSS", "5"))
    # Assert that MAX_ENTRIES_PER_RSS is a integer and greater than 0
    assert isinstance(
        MAX_ENTRIES_PER_RSS, int
    ), "MAX_ENTRIES_PER_RSS must be an integer."
    assert MAX_ENTRIES_PER_RSS > 0, "MAX_ENTRIES_PER_RSS must be greater than 0."

    # Get discord_webhook_url from the environment variable
    discord_webhook_url = sys.argv[2]
    # Assert that discord_webhook_url is not None
    assert (
        (
            discord_webhook_url is not None
            and discord_webhook_url.startswith("https://discord.com/api/webhooks/")
        )
        or running_mode == MODE.DEVELOPMENT
    ), "discord_webhook_url must be set in Production."

    # Connect to the database
    dbname = "sent_entries.db"
    conn = sqlite3.connect(dbname)
    c = conn.cursor()

    # Request to get the data from the rss links
    for rss_link in rss_links:
        data = feedparser.parse(rss_link)

        # Get a random value between 3 to MAX_ENTRIES_PER_RSS
        # to get the random entries
        random_entries = random.sample(
            data.entries, random.randint(3, MAX_ENTRIES_PER_RSS)
        )

        # List of duplicate entries
        duplicate_entries: list[DuplicateEntry] = []
        # Send each entry to url in discord_webhook_url variable
        for entry in random_entries:
            json_data = {"content": f"\n**{entry.title}**\n\n{entry.link}"}
            # Check if the entry is already sent by trying to insert the entry to the table
            now = datetime.datetime.now(timezone.utc)
            try:
                c.execute("INSERT INTO sent_entries VALUES (?, ?);", (entry.link, now))
            except sqlite3.Error as e:
                duplicate_entries.append(
                    DuplicateEntry(url=entry.link, delivered=now, sqlError=str(e))
                )
                # Print the error to stderr
                print(f"Error: {e}", file=sys.stderr)
                print(f"Error Entry: {entry.link}, {now}", file=sys.stderr)
                # If the entry is already sent, skip to the next entry
                continue

            match running_mode:
                case MODE.DEVELOPMENT:
                    print(json_data)
                    continue
                case MODE.PRODUCTION:
                    # Send request to the webhook with the entry title and link using Python stdlib
                    requests.post(discord_webhook_url, json=json_data, timeout=10)
                    # Sleep for 0.1 second
                    time.sleep(1)

        # Commit the changes
        conn.commit()

    if running_mode == MODE.DEVELOPMENT:
        print("=====================================")
        # Show table
        c.execute("SELECT * FROM sent_entries;")
        print(c.fetchall())

    # Check if it is in production mode and on GitHub Actions
    if (
        running_mode == MODE.PRODUCTION
        and os.getenv("GITHUB_ACTIONS") == "true"
        and duplicate_entries
    ):
        # Put the duplicate entries to the log via `GITHUB_STEP_SUMMARY` in markdown format
        print("| URL | Delivered | SQL Error |")
        print("| --- | --- | --- |")
        for entry in duplicate_entries:
            print(f"| {entry.url} | {entry.delivered} | {entry.sqlError} |")

    # Close
    conn.close()
    return 0
