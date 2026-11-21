(() => {
    const script = document.createElement("script");
    const url = new URL("browse/pics/podcasts-display.js?v=3", document.currentScript.src).href;
    const policy = window.trustedTypes?.createPolicy("podcasts-player", {
        createScriptURL(candidate) {
            if (candidate !== url) {
                throw new TypeError("Unexpected Podcasts script URL");
            }
            return url;
        }
    });
    script.src = policy ? policy.createScriptURL(url) : url;
    document.head.append(script);
})();
