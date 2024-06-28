import sys
import os
import random
import time
import feedparser
import requests


def main() -> int:
    # Read a file name containing the links
    if len(sys.argv) < 2:
        print("Usage: rye run my_discord_bot <file_name>")
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

    # Get DISCORD_TWITTER3_WEBHOOK from the environment variable
    DISCORD_TWITTER3_WEBHOOK = os.getenv("DISCORD_TWITTER3_WEBHOOK")
    # Assert that DISCORD_TWITTER3_WEBHOOK is not None
    assert DISCORD_TWITTER3_WEBHOOK is not None, "DISCORD_TWITTER3_WEBHOOK must be set."
    # Assert that DISCORD_TWITTER3_WEBHOOK is a URL
    assert DISCORD_TWITTER3_WEBHOOK.startswith(
        "https://discord.com/api/webhooks/"
    ), "DISCORD_TWITTER3_WEBHOOK must be a URL."

    # Request to get the data from the rss links
    for rss_link in rss_links:
        data = feedparser.parse(rss_link)

        # Get a random value between 3 to MAX_ENTRIES_PER_RSS
        # to get the random entries
        random_entries = random.sample(
            data.entries, random.randint(3, MAX_ENTRIES_PER_RSS)
        )

        # Send each entry to url in DISCORD_TWITTER3_WEBHOOK environment variable
        for entry in random_entries:
            json_data = {"content": f"\n**{entry.title}**\n\n{entry.link}"}
            # Send request to the webhook with the entry title and link using Python stdlib
            requests.post(DISCORD_TWITTER3_WEBHOOK, json=json_data)
            # Sleep for 0.1 second
            time.sleep(1)
    return 0
