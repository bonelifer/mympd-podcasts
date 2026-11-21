#!/usr/bin/env python3
"""Search podcasts, keep favorites, and resolve episodes for myMPD."""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ITUNES_URL = "https://itunes.apple.com/search"
PODCASTINDEX_URL = "https://api.podcastindex.org/api/1.0/search/byterm"
USER_AGENT = "mympd-podcasts/1.0"
ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"

SEARCH_LIMIT = 25
EPISODE_LIMIT = 25
FEED_TTL = 300  # seconds a downloaded feed is reused
FEED_CACHE_SIZE = 64
MAX_FEED_BYTES = 8 * 1024 * 1024
MAX_ART_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024

PODCAST_ID = re.compile(r"p[0-9a-f]{12}")
EPISODE_ID = re.compile(r"e[0-9a-f]{12}")


def make_id(prefix: str, value: str) -> str:
    """Return a short stable ID such as p0123456789ab for a URL."""
    return prefix + hashlib.sha1(value.encode()).hexdigest()[:12]


def clip(text: str, limit: int) -> str:
    """Collapse whitespace and shorten text for a picker label."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def public_url(url: str) -> bool:
    """Accept HTTP(S) URLs whose host resolves only to public addresses."""
    target = urlsplit(url)
    if (target.scheme not in {"http", "https"} or not target.hostname
            or target.username or target.password):
        return False
    port = target.port or (443 if target.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(
            target.hostname, port, type=socket.SOCK_STREAM
        )
        return bool(addresses) and all(
            ipaddress.ip_address(item[4][0]).is_global for item in addresses
        )
    except (OSError, ValueError):
        return False


class PublicRedirects(HTTPRedirectHandler):
    """Refuse redirects that lead to loopback, private, or link-local hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_url(urljoin(req.full_url, newurl)):
            raise URLError("Redirect to a non-public address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = build_opener(PublicRedirects)


def fetch(url: str, limit: int, headers: dict | None = None) -> bytes:
    """Download a public URL, refusing responses larger than limit bytes."""
    if not public_url(url):
        raise ValueError("Refusing to fetch a non-public address")
    request = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with OPENER.open(request, timeout=10) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Response too large")
    return body


def http_url(value) -> str:
    """Return value if it is an HTTP(S) URL with a host, else an empty string."""
    if not isinstance(value, str):
        return ""
    target = urlsplit(value.strip())
    ok = target.scheme in {"http", "https"} and target.hostname
    return value.strip() if ok else ""


def search_itunes(query: str) -> list[dict]:
    """Search Apple's iTunes directory (no account or key needed)."""
    params = urlencode({
        "media": "podcast", "entity": "podcast",
        "term": query, "limit": SEARCH_LIMIT,
    })
    data = json.loads(fetch(f"{ITUNES_URL}?{params}", MAX_JSON_BYTES))
    results = []
    for item in data.get("results", []):
        feed = http_url(item.get("feedUrl"))
        name = item.get("collectionName")
        if feed and isinstance(name, str) and name:
            results.append({
                "id": make_id("p", feed),
                "name": clip(name, 120),
                "author": clip(str(item.get("artistName") or ""), 80),
                "feed": feed,
                "artUrl": http_url(item.get("artworkUrl600")),
            })
    return results


def search_podcastindex(query: str, key: str, secret: str) -> list[dict]:
    """Search Podcast Index using the caller's free API credentials."""
    stamp = str(int(time.time()))
    headers = {
        "X-Auth-Date": stamp,
        "X-Auth-Key": key,
        "Authorization": hashlib.sha1((key + secret + stamp).encode()).hexdigest(),
    }
    params = urlencode({"q": query, "max": SEARCH_LIMIT})
    data = json.loads(
        fetch(f"{PODCASTINDEX_URL}?{params}", MAX_JSON_BYTES, headers)
    )
    results = []
    for item in data.get("feeds", []):
        feed = http_url(item.get("url"))
        name = item.get("title")
        if feed and isinstance(name, str) and name:
            results.append({
                "id": make_id("p", feed),
                "name": clip(name, 120),
                "author": clip(str(item.get("author") or ""), 80),
                "feed": feed,
                "artUrl": http_url(item.get("artwork") or item.get("image")),
            })
    return results


def parse_feed(data: bytes) -> dict:
    """Parse an RSS podcast feed into its title, artwork, and episodes."""
    if b"<!ENTITY" in data:
        raise ValueError("Feeds with entity declarations are refused")
    channel = ET.fromstring(data).find("channel")
    if channel is None:
        raise ValueError("Not an RSS podcast feed")
    image = channel.find(ITUNES_NS + "image")
    art = image.get("href") if image is not None else None
    if not art:
        art = channel.findtext("image/url")
    episodes = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        url = http_url(enclosure.get("url")) if enclosure is not None else ""
        if not url:
            continue
        published = ""
        try:
            published = parsedate_to_datetime(
                (item.findtext("pubDate") or "").strip()
            ).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pass
        episodes.append({
            "id": make_id("e", url),
            "title": clip(item.findtext("title") or "Untitled episode", 120),
            "published": published,
            "url": url.split("#", 1)[0],
        })
    return {
        "title": clip(channel.findtext("title") or "", 120),
        "image": http_url(art),
        "episodes": episodes,
    }


def cache_artwork(podcast_id: str, art_url: str, directory: Path | None) -> str:
    """Make a podcast's cover available to the local myMPD web server."""
    if directory is None or not art_url:
        return ""
    for extension in (".jpg", ".png"):
        cached = directory / (podcast_id + extension)
        if cached.is_file():
            return cached.name
    try:
        image = fetch(art_url, MAX_ART_BYTES)
        if image.startswith(b"\x89PNG\r\n\x1a\n"):
            extension = ".png"
        elif image.startswith(b"\xff\xd8\xff") and image.endswith(b"\xff\xd9"):
            extension = ".jpg"
        else:
            return ""
        destination = directory / (podcast_id + extension)
        with NamedTemporaryFile(dir=directory, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(image)
                output.close()
                temporary.chmod(0o644)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return destination.name
    except (OSError, ValueError):
        return ""


class Favorites:
    """Favorite podcasts kept in a JSON file, written atomically."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def load(self) -> dict[str, dict]:
        """Return favorites by ID; a missing file means none yet."""
        try:
            entries = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        return {entry["id"]: entry for entry in entries}

    def change(self, update) -> None:
        """Apply update(favorites_by_id) and save the result."""
        with self.lock:
            favorites = self.load()
            update(favorites)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                "w", dir=self.path.parent, delete=False, encoding="utf-8"
            ) as output:
                temporary = Path(output.name)
                try:
                    json.dump(list(favorites.values()), output, indent=2)
                    output.close()
                    temporary.chmod(0o644)
                    os.replace(temporary, self.path)
                finally:
                    temporary.unlink(missing_ok=True)


class PodcastServer(ThreadingHTTPServer):
    """HTTP server that carries the bridge's shared state."""

    daemon_threads = True

    def __init__(self, address, favorites: Favorites,
                 artwork_dir: Path | None, index_credentials):
        super().__init__(address, Handler)
        self.favorites = favorites
        self.artwork_dir = artwork_dir
        self.index_credentials = index_credentials
        self.results: dict[str, dict] = {}
        self.feeds: dict[str, tuple[float, dict]] = {}
        self.feed_lock = threading.Lock()

    def sources(self) -> list[dict]:
        """List the directories that can be searched."""
        sources = [{"id": "itunes", "name": "Apple iTunes"}]
        if self.index_credentials:
            sources.append({"id": "podcastindex", "name": "Podcast Index"})
        return sources

    def feed(self, url: str) -> dict:
        """Return a parsed feed, reusing a recent download."""
        with self.feed_lock:
            cached = self.feeds.get(url)
            if cached and time.monotonic() - cached[0] < FEED_TTL:
                return cached[1]
        parsed = parse_feed(fetch(url, MAX_FEED_BYTES))
        with self.feed_lock:
            if len(self.feeds) >= FEED_CACHE_SIZE:
                self.feeds.pop(min(self.feeds, key=lambda k: self.feeds[k][0]))
            self.feeds[url] = (time.monotonic(), parsed)
        return parsed


class Handler(BaseHTTPRequestHandler):
    """Serve favorites, search, and episodes to the myMPD picker."""

    server: PodcastServer

    def do_GET(self) -> None:
        """Return picker data or a playable episode as JSON."""
        server = self.server
        request = urlsplit(self.path)
        path = request.path
        query = parse_qs(request.query)
        try:
            if path == "/sources":
                self.respond(200, server.sources())
            elif path == "/favorites":
                self.respond(200, [
                    {"id": item["id"], "name": item["name"],
                     "author": item.get("author", "")}
                    for item in server.favorites.load().values()
                ])
            elif path == "/search":
                self.search(query)
            elif match := re.fullmatch(r"/episodes/(p[0-9a-f]{12})", path):
                podcast = self.favorite(match[1])
                if podcast:
                    episodes = server.feed(podcast["feed"])["episodes"]
                    self.respond(200, [
                        {key: item[key] for key in ("id", "title", "published")}
                        for item in episodes[:EPISODE_LIMIT]
                    ])
            elif match := re.fullmatch(
                r"/play/(p[0-9a-f]{12})/(e[0-9a-f]{12})", path
            ):
                self.play(match[1], match[2])
            elif match := re.fullmatch(r"/latest/(p[0-9a-f]{12})", path):
                self.play(match[1], None)
            else:
                self.respond(404, {"error": "Unknown request"})
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
            self.respond(502, {"error": "Podcast request failed"})

    def do_POST(self) -> None:
        """Save or remove a favorite; only local myMPD may do this."""
        match = re.fullmatch(r"/favorites/(add|remove)/(p[0-9a-f]{12})", self.path)
        if not match:
            self.respond(404, {"error": "Unknown favorite action"})
            return
        if (self.client_address[0] != "127.0.0.1"
                or self.headers.get("Content-Type") != "application/json"
                or self.headers.get("Origin")):
            self.respond(403, {"error": "Favorite changes require local myMPD"})
            return
        action, podcast_id = match.groups()
        server = self.server
        try:
            if action == "add":
                found = server.results.get(podcast_id)
                if not found:
                    self.respond(404, {"error": "Search again before saving"})
                    return
                server.feed(found["feed"])  # proves the feed is readable
                server.favorites.change(
                    lambda items: items.setdefault(podcast_id, found)
                )
            else:
                server.favorites.change(lambda items: items.pop(podcast_id, None))
            self.respond(200, {"ok": True})
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
            self.respond(502, {"error": "Podcast request failed"})

    def favorite(self, podcast_id: str) -> dict | None:
        """Look up a favorite, answering 404 itself when it is unknown."""
        podcast = self.server.favorites.load().get(podcast_id)
        if podcast is None:
            self.respond(404, {"error": "Unknown favorite podcast"})
        return podcast

    def search(self, query: dict) -> None:
        """Search the chosen directory and remember the results for saving."""
        server = self.server
        text = query.get("q", [""])[0].strip()
        source = query.get("source", ["itunes"])[0]
        if not 1 <= len(text) <= 100:
            self.respond(400, {"error": "Enter a podcast name"})
        elif source == "itunes":
            self.send_results(search_itunes(text))
        elif source == "podcastindex" and server.index_credentials:
            self.send_results(search_podcastindex(text, *server.index_credentials))
        else:
            self.respond(400, {"error": "Unknown search source"})

    def send_results(self, results: list[dict]) -> None:
        """Remember search results by ID and send the picker-sized view."""
        self.server.results = {item["id"]: item for item in results}
        self.respond(200, [
            {"id": item["id"], "name": item["name"], "author": item["author"]}
            for item in results
        ])

    def play(self, podcast_id: str, episode_id: str | None) -> None:
        """Resolve one episode (or the newest) of a favorite for playback."""
        server = self.server
        podcast = self.favorite(podcast_id)
        if podcast is None:
            return
        feed = server.feed(podcast["feed"])
        episodes = feed["episodes"]
        episode = next(
            (item for item in episodes if episode_id in {None, item["id"]}), None
        )
        if episode is None:
            self.respond(404, {"error": "Unknown episode"})
            return
        art_url = podcast.get("artUrl") or feed["image"]
        self.respond(200, {
            "url": episode["url"],
            "name": podcast["name"],
            "title": episode["title"],
            "artFile": cache_artwork(podcast_id, art_url, server.artwork_dir),
        })

    def respond(self, status: int, payload: dict | list) -> None:
        """Send a JSON response."""
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    """Run the bridge until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-l", "--listen", default="127.0.0.1")
    parser.add_argument("-p", "--port", type=int, default=18774)
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="Folder that holds favorites.json")
    parser.add_argument("--artwork-dir", type=Path,
                        help="myMPD pics/podcasts folder for cached covers")
    args = parser.parse_args()
    key = os.environ.get("PODCASTINDEX_API_KEY", "").strip()
    secret = os.environ.get("PODCASTINDEX_API_SECRET", "").strip()
    credentials = (key, secret) if key and secret else None
    socket.setdefaulttimeout(10)
    favorites = Favorites(args.data_dir / "favorites.json")
    with PodcastServer((args.listen, args.port), favorites,
                       args.artwork_dir, credentials) as server:
        print(f"Podcasts is listening on {server.server_address}.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
