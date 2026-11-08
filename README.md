# my-discord-bot

An RSS-to-Discord webhook bot. Entries are tracked in `sent_entries.db` to avoid
posting duplicates.

Requires Python 3.15 or newer. Development and CI use Python 3.15.2 and uv 0.13.7;
the versions are pinned in `.python-version` and `pyproject.toml` respectively.

```sh
uv python install
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked pyrefly check
```

Run the bot with an RSS URL list and a Discord webhook URL:

```sh
uv run --locked my-discord-bot rss_links.txt "$DISCORD_WEBHOOK_URL"
```

Set `MODE=1` for development mode, which logs embeds instead of sending them.
Development mode still records entries in the database; use a temporary working
directory to keep the production database untouched.

`uv.lock` is the dependency lockfile used locally and in GitHub Actions.
