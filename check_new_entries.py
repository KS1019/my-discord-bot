# `rss_links.txt` contains the links to the RSS feeds that we want to check for new entries, separated by newline.
# Read the file and put each link to a list.

# import the feedparser library
import feedparser

# Read the file
with open('rss_links.txt', 'r') as f:
    rss_links = f.read().splitlines()
    # Get RSS feed from each link
    for link in rss_links:
        print(link)
        # Get the feed
        feed = feedparser.parse(link)
        # Get the title of the feed
        print(feed.feed.title)
        # Get the entries
        for entry in feed.entries:
            # Check if the title property exists
            if 'title' in entry:
                # Get the title of the entry

            print(entry.title)
            # Get the link of the entry
            print(entry.link)

# Dataclass `RSSEntry` to store the feed data
@dataclass
class RSSEntry:
    title: str
    link: str