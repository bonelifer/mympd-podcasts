# Podcasts for myMPD

Search for podcasts, keep a list of favorites, and play or queue episodes
from the myMPD Scripts menu, the Home screen, or the player. Podcasts work
like the stations in the other myMPD pickers: choose a favorite, then pick an
episode. MPD plays the episode's audio directly.

## Docker Compose

Compose pulls the published image from `ghcr.io/bonelifer/mympd-podcasts:latest`.

Create the data and artwork folders once, then set the user the bridge runs as.
`data/` holds `favorites.json`. Point `artwork` at myMPD's `pics/podcasts/`
folder if you want podcast covers in the player (see below).

```sh
mkdir -p data artwork
export PODCASTS_UID="$(id -u)" PODCASTS_GID="$(id -g)"
```

If myMPD uses host networking, start the bridge on loopback.

```sh
docker compose -f compose.yaml -f compose.host.yaml up --pull always -d
```

If myMPD uses a private Docker network, start the bridge on that network
and pass `--service http://podcasts:18774` to the installer.

```sh
export MPD_NETWORK=your-existing-mpd-network
docker compose up --pull always -d
```

Set `PODCASTS_DATA` and `PODCASTS_ARTWORK` to absolute paths to use other
folders. Saving and removing favorites requires myMPD to reach the bridge
through loopback, so use the host-network setup if you want to change favorites
from the picker.

## Run without Docker

With Python 3.10 or later, run `python3 bridge.py` in the same network
namespace as myMPD. It listens on `127.0.0.1:18774` and keeps favorites in
`data/favorites.json`. Use `--data-dir` and `--artwork-dir` to change the
folders.

## Search sources

Search uses the Apple iTunes directory, which needs no account. To also search
Podcast Index, create a free key at [podcastindex.org](https://podcastindex.org)
and start the bridge with `PODCASTINDEX_API_KEY` and `PODCASTINDEX_API_SECRET`
set. The search dialog then offers both directories.

## Install the picker

Enable Lua scripting in myMPD, then install the picker.

```sh
python3 install-picker.py --mympd http://127.0.0.1:8081 --workdir /path/to/mympd/workdir
```

Pass `--workdir` to also add the Podcasts tile and its icon to the Home screen;
omit it to install only the script. For a shared Docker network, pass
`--service http://podcasts:18774`. For a PIN-protected instance, set
`MYMPD_SESSION` to a valid session token. Use `--partition` for a different
partition or `--replace` to update an existing picker. You can also paste
`podcasts.lua` into the myMPD script editor as **Podcasts** with menu order 7.

Open **Podcasts** and choose what to do with the selected favorite:

- **Choose an episode** lists the latest episodes. Play one now or add it to the queue.
- **Play latest episode** starts the newest episode.
- **Find and save a podcast** searches the directory and saves a result.
- **Remove selected podcast** removes a favorite after confirming.

## Now Playing display

Copy `podcasts-display.js` to myMPD's `pics/` directory and append
`podcasts-loader.js` to `config/custom_js` once. Restart myMPD and reload
the web app. Choose the episode again from the picker to add its display
metadata to the queue entry.

While a podcast episode is playing, the player shows the podcast and episode
name, and a **Open Podcasts picker** button opens the same popup as the Home
tile.

For covers, create `pics/podcasts/` in myMPD's work directory, make it writable
by the bridge user, and mount it as the artwork folder (`PODCASTS_ARTWORK`, or
`--artwork-dir` without Docker). Covers must be PNG or JPEG files up to 4 MB.

## Privacy and safety

The bridge only downloads feeds and covers from public internet addresses and
refuses redirects to loopback, private, or link-local hosts. It reads feeds
as XML without entity declarations and limits download sizes. Episode audio
is fetched by MPD, not by the bridge.

## Contributing

- **Bug reports** can go in [Issues](https://github.com/bonelifer/mympd-podcasts/issues).
- **Questions and feature ideas** belong in [Discussions](https://github.com/bonelifer/mympd-podcasts/discussions).
- Pull requests are welcome for bug fixes and discussed features.

## License

This project is licensed under the **GNU General Public License v3.0**.

See [LICENSE](LICENSE) for more information. The icon in `assets/` is CC0.
