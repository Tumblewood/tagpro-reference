document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("import-recent-games-btn");
    const textarea = document.getElementById("eu_urls");
    const statusEl = document.getElementById("import-recent-games-status");

    if (!btn || !textarea) return;

    function extractMatchesUrl(text) {
        const match = text.match(/https:\/\/tagpro\.eu\/\?matches=[^\s]*/);
        return match ? match[0] : null;
    }

    btn.addEventListener("click", function () {
        btn.disabled = true;
        btn.textContent = "Loading...";
        statusEl.textContent = "";

        const customUrl = extractMatchesUrl(textarea.value);
        const seasonFilter = (document.getElementById("season_filter_string") || {}).value || "";
        const params = new URLSearchParams();
        if (customUrl) params.set("url", customUrl);
        if (seasonFilter.trim()) params.set("season", seasonFilter.trim());
        const paramStr = params.toString();
        const endpoint = "/import/recent-games/" + (paramStr ? "?" + paramStr : "");

        fetch(endpoint)
            .then(function (response) {
                return response.json().then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function ({ ok, data }) {
                if (!ok || data.error) {
                    statusEl.textContent = "Error: " + (data.error || "Unknown error");
                    statusEl.className = "import-recent-status error";
                    return;
                }
                if (data.ids.length === 0) {
                    statusEl.textContent = "No recent league games found.";
                    statusEl.className = "import-recent-status";
                    return;
                }
                textarea.value = data.ids.join("\n");
                statusEl.textContent = data.ids.length + " game(s) loaded.";
                statusEl.className = "import-recent-status success";
            })
            .catch(function (err) {
                statusEl.textContent = "Error: " + err.message;
                statusEl.className = "import-recent-status error";
            })
            .finally(function () {
                btn.disabled = false;
                btn.textContent = "Detect Recent Games";
            });
    });
});
