#!/usr/bin/env python3
"""List favorite podcasts or start playing a podcast's latest episode in myMPD.

Purpose:
    --list prints every favorite podcast as "<id>  <name>".
    With a podcast id, the script asks the bridge for the latest episode and
    queues it in myMPD with play enabled, so it starts immediately. The queue
    entry carries the same metadata as the Podcasts picker, so Now Playing
    shows the episode title, podcast name, and cover.

Inputs:
    PODCAST_ID           id from --list (for example pf2c6595bb47c)
    --list               print the favorites and exit
    --mympd URL          myMPD base URL (default http://127.0.0.1:8081)
    --service URL        bridge URL (default http://127.0.0.1:18774)
    --partition NAME     myMPD partition (default "default")
    MYMPD_SESSION        environment variable: session token for a
                         PIN-protected myMPD instance

Output:
    The episode that was started, or an error message and exit status 1.
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

DEFAULT_MYMPD = "http://127.0.0.1:8081"
DEFAULT_SERVICE = "http://127.0.0.1:18774"
PODCAST_ID = re.compile(r"p[0-9a-f]{12}")


def check_url(url: str) -> str:
    """Return the URL without a trailing slash, or raise ValueError."""
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.query or parsed.fragment
            or not url.isascii() or any(ord(char) <= 32 for char in url)):
        raise ValueError("URLs must be HTTP(S) without credentials or queries")
    return url.rstrip("/")


def get_json(url: str):
    """Fetch a URL from the bridge and return its decoded JSON body."""
    with urlopen(url, timeout=30) as response:
        return json.load(response)


def call_mympd(endpoint: str, headers: dict[str, str], method: str,
               params: dict) -> dict:
    """Send one JSON-RPC request to myMPD and return its result."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    request = Request(endpoint, json.dumps(payload).encode(), headers)
    with urlopen(request, timeout=15) as response:
        data = json.load(response)
    if "result" not in data or "error" in data:
        raise ValueError(f"myMPD rejected {method}: {data.get('error')}")
    return data["result"]


def episode_uri(episode: dict, podcast_id: str) -> str:
    """Build the queue URI the Now Playing display script understands."""
    def encode(value: str) -> str:
        return quote(value or "", safe="-_.~")

    return (episode["url"].split("#", 1)[0]
            + "#mympd-podcasts=" + podcast_id
            + "&name=" + encode(episode.get("name", ""))
            + "&title=" + encode(episode.get("title", ""))
            + "&art=" + encode(episode.get("artFile", "")))


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("podcast_id", nargs="?",
                        help="podcast id shown by --list")
    parser.add_argument("--list", action="store_true",
                        help="print favorite podcasts as '<id>  <name>'")
    parser.add_argument("--mympd", default=DEFAULT_MYMPD,
                        help="myMPD base URL")
    parser.add_argument("--service", default=DEFAULT_SERVICE,
                        help="bridge URL")
    parser.add_argument("--partition", default="default",
                        help="myMPD partition")
    return parser


def main() -> int:
    """Run the command line; return the process exit status."""
    parser = build_parser()
    args = parser.parse_args()
    if args.list == (args.podcast_id is not None):
        parser.error("give a podcast id, or use --list")
    if (args.podcast_id is not None
            and not PODCAST_ID.fullmatch(args.podcast_id)):
        parser.error("podcast ids look like pf2c6595bb47c; "
                     "run --list to see them")
    try:
        service = check_url(args.service)
        mympd = check_url(args.mympd)
        if args.list:
            for favorite in get_json(service + "/favorites"):
                print(f"{favorite['id']}  {favorite['name']}")
            return 0
        episode = get_json(f"{service}/latest/{args.podcast_id}")
        headers = {"Content-Type": "application/json"}
        if session := os.environ.get("MYMPD_SESSION"):
            headers["X-myMPD-Session"] = session
        endpoint = mympd + "/api/" + quote(args.partition, safe="")
        call_mympd(endpoint, headers, "MYMPD_API_QUEUE_APPEND_URIS", {
            "uris": [episode_uri(episode, args.podcast_id)],
            "play": True,
        })
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"podcast-play: {error}", file=sys.stderr)
        return 1
    print(f"Playing: {episode.get('name', '')} - {episode.get('title', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
