/* Show the podcast and episode name and cover for episodes queued by the Podcasts picker. */
(() => {
    function infoLine(anchor, tag) {
        const line = document.createElement(tag);
        line.hidden = true;
        anchor.after(line);
        return line;
    }

    const infoLines = [
        infoLine(document.getElementById("PlaybackTitle"), "p"),
        infoLine(document.getElementById("footerTitle"), "div")
    ];
    const covers = ["PlaybackCover", "footerCover"].map(id => {
        const cover = document.createElement("img");
        cover.alt = "";
        cover.hidden = true;
        cover.classList.add("position-absolute", "top-0", "start-0", "w-100",
            "h-100", "object-fit-contain", "pe-none", "bg-body");
        cover.addEventListener("error", () => { cover.hidden = true; });
        document.getElementById(id).append(cover);
        return cover;
    });
    const assetBase = new URL(".", document.currentScript.src);
    const picker = document.createElement("button");
    picker.type = "button";
    picker.className = "btn px-2 mi rounded-2 d-none";
    picker.textContent = "podcasts";
    picker.title = "Open Podcasts picker";
    picker.setAttribute("aria-label", picker.title);
    picker.addEventListener("click", () => {
        execScriptFromOptions("Podcasts", [""]);
    });
    document.getElementById("footerNextBtn")?.after(picker);

    function update() {
        const fragment = (currentSongObj?.uri ?? "").split("#")[1] ?? "";
        const metadata = new URLSearchParams(fragment);
        const id = metadata.get("mympd-podcasts") ?? "";
        const isPodcast = /^p[0-9a-f]{12}$/.test(id);
        picker.classList.toggle("d-none", !isPodcast);
        const show = metadata.get("name") ?? "";
        const artist = document.getElementById("footerArtist")?.textContent ?? "";
        const text = artist.includes(show) ? "" : show;
        for (const line of infoLines) {
            line.hidden = !isPodcast || text === "";
            if (!line.hidden) {
                line.textContent = text;
            }
        }
        const artwork = metadata.get("art") ?? "";
        const hasArtwork = isPodcast && (artwork === id + ".jpg" || artwork === id + ".png");
        for (const cover of covers) {
            if (!hasArtwork) {
                cover.hidden = true;
                cover.removeAttribute("src");
            } else {
                const src = new URL("podcasts/" + artwork, assetBase).href;
                if (cover.src !== src) {
                    cover.src = src;
                    cover.hidden = false;
                }
            }
        }
    }

    const observer = new MutationObserver(update);
    for (const id of ["PlaybackTitle", "footerTitle", "footerArtist"]) {
        const element = document.getElementById(id);
        if (element) {
            observer.observe(element, {childList: true, characterData: true, subtree: true});
        }
    }
    update();
})();
