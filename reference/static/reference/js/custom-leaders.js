/**
 * Custom leaderboard builder.
 *
 * All leaderboard math runs here in the browser. The server only ships one compact JSON blob
 * per season (see reference/utils/custom_leaders.py); everything below - filtering, the three
 * formulas, and the derived stats - is computed from that blob, so changing a weight never
 * touches the server.
 */

// Number of leading metadata columns in each row: playerIdx, gameIdx, side, superseded.
const ROW_META_COLUMNS = 4;

// Stat columns stored in ticks (1/60s). Weights for these are expressed per minute, so the
// SCAR preset reads as 0.6 * hold rather than 0.01 * hold.
const TICK_FIELDS = ["time_played", "hold", "prevent", "hold_against"];

const CONFIG_VERSION = 1;

// Must match PAYLOAD_VERSION in reference/utils/custom_leaders.py. Sent with the data request so
// a shape change busts both the browser cache and the server cache.
const PAYLOAD_VERSION = 4;

// Score column indices in the rendered table, used to seed the sorter.
const SCORE_COLUMN_INDEX = 2;

const state = {
    seasonsByLeague: null,
    scarPresetWeights: null,
    gaspPresetWeights: null,
    payloads: new Map(),
    payload: null,
    live: false,
    recomputeTimer: null,
    headerHtml: null,
    blowoutTouched: false,
};


/* ------------------------------------------------------------------ helpers */

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/**
 * Python's round(value, digits), including its round-half-to-even behaviour.
 *
 * Math.round is not a substitute: it rounds halves up, and calculate_rate_stats uses rounded
 * minutes as the denominator of every per-10 stat, so a tie resolved the other way shifts a
 * player's whole rate line.
 */
function pyRound(value, digits) {
    if (!isFinite(value)) {
        return 0;
    }
    const places = digits || 0;
    const magnitude = Math.abs(value);

    // Expand well past the target precision to see what the double actually holds: 6.65 is
    // really 6.65000000000000036, which is above the midpoint rather than a tie. Multiplying
    // by 10^n would round that away and report a tie that isn't one.
    const expanded = magnitude.toFixed(places + 16);
    const tail = expanded.slice(expanded.indexOf(".") + 1 + places);
    const isTie = tail.charAt(0) === "5" && /^0*$/.test(tail.slice(1));

    if (!isTie) {
        return Number(value.toFixed(places));
    }

    // A genuine tie: Python rounds half to even.
    const factor = Math.pow(10, places);
    const lower = Math.floor(magnitude * factor);
    const toEven = lower % 2 === 0 ? lower : lower + 1;
    return (value < 0 ? -toEven : toEven) / factor;
}

/**
 * Port of calculate_blowout_multiplier in reference/utils/stat_collection.py.
 *
 * The first 3 caps of a cap differential count fully, the 4th counts 0.8, the 5th 0.6, the
 * 6th through 9th 0.4 each, and anything beyond that 0.2. The multiplier is the resulting
 * blowout-adjusted cap differential divided by the actual one.
 */
function blowoutMultiplier(capDifferential) {
    if (capDifferential === 0) {
        return 1.0;
    }
    const absCd = Math.abs(capDifferential);
    let bacd;
    if (absCd <= 3) {
        bacd = absCd;
    } else if (absCd === 4) {
        bacd = 3.8;
    } else if (absCd === 5) {
        bacd = 4.4;
    } else if (absCd <= 9) {
        bacd = 2.4 + 0.4 * absCd;
    } else {
        bacd = 4.2 + 0.2 * absCd;
    }
    return bacd / absCd;
}

function weekMatches(weekName, selection) {
    if (selection === "all_season") {
        return true;
    }
    if (selection === "all_regular_season") {
        return weekName.startsWith("Week");
    }
    if (selection === "all_playoffs") {
        return !weekName.startsWith("Week");
    }
    return weekName === selection;
}


/* -------------------------------------------------------------- derived stats */

/**
 * Port of calculate_rate_stats in reference/utils/display_info.py.
 *
 * `totals` is an object keyed by raw stat field name. The unit conversions and rounding match
 * the Python version exactly, so weighting a derived stat by 1.0 reproduces the number shown
 * in that column on the season stats page.
 */
function calculateDerivedStats(totals) {
    const minutes = totals.time_played ? pyRound(totals.time_played / 3600) : 0;
    const holdSec = totals.hold ? pyRound(totals.hold / 60) : 0;
    const preventSec = totals.prevent ? pyRound(totals.prevent / 60) : 0;
    const holdAgainstSec = totals.hold_against ? pyRound(totals.hold_against / 60) : 0;

    const grabs = totals.grabs;
    const captures = totals.captures;
    const tags = totals.tags;
    const pops = totals.pops;
    const returns = totals.returns;
    const handoffs = totals.handoffs;
    const grabsAgainst = totals.grabs_against;
    const outsAgainst = totals.outs_against;

    return {
        hold_per_grab: grabs > 0 ? pyRound(holdSec / grabs, 1) : 0,
        score_percent: grabs > 0 ? pyRound((captures / grabs) * 100, 1) : 0,
        chain_percent: handoffs > 0 ? pyRound((totals.good_handoffs / handoffs) * 100, 1) : 0,
        flaccid_percent: grabs > 0 ? pyRound((totals.flaccids / grabs) * 100, 1) : 0,
        spark_percent:
            captures > 0
                ? pyRound(((captures - totals.caps_off_regrab) / captures) * 100, 1)
                : 0,
        prevent_per_return: returns > 0 ? pyRound(preventSec / returns, 2) : 0,
        prevent_per_hold_against:
            holdAgainstSec > 0 ? pyRound(preventSec / holdAgainstSec, 2) : 0,
        rib_percent: returns > 0 ? pyRound((totals.returns_in_base / returns) * 100, 1) : 0,
        qr_percent: returns > 0 ? pyRound((totals.quick_returns / returns) * 100, 1) : 0,
        plus_minus: totals.caps_for - totals.caps_against,
        kd_ratio: pops > 0 ? pyRound(tags / pops, 2) : 0,
        non_return_tags: tags - returns,
        non_drop_pops: pops - totals.drops,
        pup_percent:
            totals.total_pups_in_game > 0
                ? pyRound((totals.powerups / totals.total_pups_in_game) * 100, 1)
                : 0,
        grabs_per_10: minutes > 0 ? pyRound((grabs / minutes) * 10, 1) : 0,
        caps_per_10: minutes > 0 ? pyRound((captures / minutes) * 10, 1) : 0,
        hold_per_10: minutes > 0 ? pyRound((holdSec / minutes) * 10) : 0,
        ret_per_10: minutes > 0 ? pyRound((returns / minutes) * 10, 1) : 0,
        prev_per_10: minutes > 0 ? pyRound((preventSec / minutes) * 10) : 0,
        ha_per_10: minutes > 0 ? pyRound((holdAgainstSec / minutes) * 10) : 0,
        nrt_per_10: minutes > 0 ? pyRound(((tags - returns) / minutes) * 10, 1) : 0,
        out_pct_off: grabs > 0 ? pyRound((totals.outs / grabs) * 100, 1) : 0,
        prod_pct: grabs > 0 ? pyRound((totals.productive_grabs / grabs) * 100, 1) : 0,
        free_pct: grabs > 0 ? pyRound((totals.grabs_off_regrab / grabs) * 100, 1) : 0,
        apo: grabs > 0 ? pyRound(totals.preventing_opponents / grabs, 2) : 0,
        out_pct_def: grabsAgainst > 0 ? pyRound((outsAgainst / grabsAgainst) * 100, 1) : 0,
        p_oa: outsAgainst > 0 ? pyRound(preventSec / outsAgainst, 1) : 0,
        apt: preventSec > 0 ? pyRound(totals.preventing_teammates / (preventSec * 60), 2) : 0,
    };
}


/* -------------------------------------------------------------- row preparation */

/**
 * Filter the payload's rows down to the current week selection and apply the overtime and
 * blowout settings, producing the working set every formula starts from.
 */
function prepareRows(payload, settings) {
    const fieldCount = payload.fields.length;
    const timeIndex = payload.fields.indexOf("time_played");
    const divisors = payload.fields.map((field) => (TICK_FIELDS.includes(field) ? 3600 : 1));

    const otByRow = new Map();
    if (settings.includeOvertime) {
        for (const delta of payload.ot) {
            otByRow.set(delta[0], delta);
        }
    }

    const prepared = [];
    for (let i = 0; i < payload.rows.length; i += 1) {
        const row = payload.rows[i];
        const game = payload.games[row[1]];
        if (!weekMatches(payload.weeks[game[0]], settings.week)) {
            continue;
        }

        const stats = new Float64Array(fieldCount);
        const otDelta = otByRow.get(i);
        for (let k = 0; k < fieldCount; k += 1) {
            stats[k] = row[ROW_META_COLUMNS + k] + (otDelta ? otDelta[1 + k] : 0);
        }

        // The stored score includes any overtime cap, and it stays in the differential whether
        // or not overtime stats are counted -- matching calculate_scar.
        const capDiff = game[1] - game[2];
        const multiplier = settings.blowoutAdjustment ? blowoutMultiplier(capDiff) : 1;
        const minutes = stats[timeIndex] / 3600;

        prepared.push({
            playerIdx: row[0],
            gameIdx: row[1],
            side: row[2],
            stats: stats,
            minutes: minutes,
            multiplier: multiplier,
            adjustedMinutes: minutes * multiplier,
            tscar: payload.tscar[i],
            // Superseded by a later match in the same season-week. The row still belongs to its
            // game, so SCAR's per-game regression has to see it; it is only left out when
            // totalling a player. Dropping it earlier changes the team totals that the
            // regression divides up, and shifts every other player in that game.
            superseded: row[3] === 1,
        });
    }

    return { rows: prepared, divisors: divisors, timeIndex: timeIndex };
}

/** Sum each player's stats across their rows, scaled by the blowout multiplier. */
function aggregateByPlayer(prepared, payload) {
    const fieldCount = payload.fields.length;
    const players = new Map();

    for (const row of prepared.rows) {
        if (row.superseded) {
            continue;
        }
        let entry = players.get(row.playerIdx);
        if (!entry) {
            entry = {
                playerIdx: row.playerIdx,
                totals: new Float64Array(fieldCount),
                minutes: 0,
                adjustedMinutes: 0,
            };
            players.set(row.playerIdx, entry);
        }
        for (let k = 0; k < fieldCount; k += 1) {
            entry.totals[k] += row.stats[k] * row.multiplier;
        }
        entry.minutes += row.minutes;
        entry.adjustedMinutes += row.adjustedMinutes;
    }

    for (const entry of players.values()) {
        const named = {};
        payload.fields.forEach((field, index) => {
            named[field] = entry.totals[index];
        });
        entry.named = named;
        entry.derived = calculateDerivedStats(named);
    }

    return Array.from(players.values());
}

/**
 * Rank every player by the site's stored TSCAR, best first.
 *
 * TSCAR is read straight off PlayerRegulationStats rather than recomputed, so these are the
 * standings the season stats page would show for the same week selection.
 */
function rankByStoredTscar(prepared) {
    const totals = new Map();
    for (const row of prepared.rows) {
        if (row.superseded) {
            continue;
        }
        totals.set(row.playerIdx, (totals.get(row.playerIdx) || 0) + row.tscar);
    }
    const ranks = new Map();
    Array.from(totals.entries())
        .sort((a, b) => b[1] - a[1])
        .forEach(function (entry, index) {
            ranks.set(entry[0], index + 1);
        });
    return ranks;
}

/** Look up a player's value for a weightable stat, in the units the weight box expects. */
function statValue(entry, key, payload, divisors) {
    const fieldIndex = payload.fields.indexOf(key);
    if (fieldIndex !== -1) {
        return entry.totals[fieldIndex] / divisors[fieldIndex];
    }
    return entry.derived[key] || 0;
}


/* ------------------------------------------------------------------ formulas */

function computeAdditive(prepared, payload, weights) {
    const entries = aggregateByPlayer(prepared, payload);
    const keys = Object.keys(weights);
    for (const entry of entries) {
        let score = 0;
        for (const key of keys) {
            score += weights[key] * statValue(entry, key, payload, prepared.divisors);
        }
        entry.score = score;
    }
    return entries;
}

function computeGasp(prepared, payload, weights) {
    const entries = aggregateByPlayer(prepared, payload);
    const keys = Object.keys(weights);

    for (const entry of entries) {
        entry.score = 0;
    }

    for (const key of keys) {
        const values = entries.map((entry) =>
            statValue(entry, key, payload, prepared.divisors)
        );
        const mean = values.reduce((sum, value) => sum + value, 0) / (values.length || 1);
        const variance =
            values.reduce((sum, value) => sum + (value - mean) * (value - mean), 0) /
            (values.length || 1);
        const stdev = Math.sqrt(variance);
        if (stdev === 0) {
            continue; // every player identical in this stat; it can't separate anyone
        }
        entries.forEach((entry, index) => {
            entry.score += weights[key] * ((values[index] - mean) / stdev);
        });
    }

    // Rescale so the worst player sits at 0 and the best at 10.
    const rawScores = entries.map((entry) => entry.score);
    const lowest = Math.min.apply(null, rawScores);
    const highest = Math.max.apply(null, rawScores);
    const spread = highest - lowest;
    for (const entry of entries) {
        entry.score = spread > 0 ? ((entry.score - lowest) / spread) * 10 : 0;
    }

    return entries;
}

/**
 * Port of calculate_scar in reference/utils/stat_collection.py, with the user's weights and
 * replacement level.
 *
 * Every step of the real SCAR pipeline is linear, so OSCAR and DSCAR collapse into a single
 * combined weight vector: the 50/50 regression split and the per-side replacement bonus both
 * sum back to the same total. That means one pass over one weight vector reproduces TSCAR.
 */
function computeScar(prepared, payload, weights, settings) {
    const { rows, divisors } = prepared;
    const weightByIndex = payload.fields.map((field) => weights[field] || 0);

    let leagueRaw = 0;
    let leagueMinutes = 0;
    for (const row of rows) {
        let raw = 0;
        for (let k = 0; k < weightByIndex.length; k += 1) {
            if (weightByIndex[k] !== 0) {
                raw += weightByIndex[k] * (row.stats[k] / divisors[k]);
            }
        }
        row.rawAdjusted = raw * row.multiplier;
        leagueRaw += row.rawAdjusted;
        leagueMinutes += row.adjustedMinutes;
    }

    // Normalize so the minutes-weighted league average is zero.
    const leaguePerMinute = leagueMinutes > 0 ? leagueRaw / leagueMinutes : 0;
    for (const row of rows) {
        row.normalized = row.rawAdjusted - leaguePerMinute * row.adjustedMinutes;
    }

    const byGame = new Map();
    for (const row of rows) {
        let gameRows = byGame.get(row.gameIdx);
        if (!gameRows) {
            gameRows = [];
            byGame.set(row.gameIdx, gameRows);
        }
        gameRows.push(row);
    }

    const scores = new Map();
    const minutesByPlayer = new Map();

    byGame.forEach(function (gameRows, gameIdx) {
        const game = payload.games[gameIdx];
        const capDiff = game[1] - game[2];
        const gameMultiplier = settings.blowoutAdjustment ? blowoutMultiplier(capDiff) : 1;
        const bacd = capDiff * gameMultiplier;

        // Regress each team's total toward half the blowout-adjusted cap differential,
        // distributing the correction across players by adjusted minutes.
        const teamNormalized = [0, 0];
        const teamMinutes = [0, 0];
        for (const row of gameRows) {
            teamNormalized[row.side] += row.normalized;
            teamMinutes[row.side] += row.adjustedMinutes;
        }

        const adjustmentPerMinute = [0, 1].map(function (side) {
            const target = side === 0 ? bacd / 2 : -bacd / 2;
            return teamMinutes[side] > 0
                ? (target - teamNormalized[side]) / teamMinutes[side]
                : 0;
        });

        for (const row of gameRows) {
            if (row.superseded) {
                continue;
            }
            const replacementBonus = (settings.replacement / 10) * row.adjustedMinutes;
            const rowScore =
                row.normalized +
                adjustmentPerMinute[row.side] * row.adjustedMinutes +
                replacementBonus;
            scores.set(row.playerIdx, (scores.get(row.playerIdx) || 0) + rowScore);
        }
    });

    for (const row of rows) {
        if (row.superseded) {
            continue;
        }
        let entry = minutesByPlayer.get(row.playerIdx);
        if (!entry) {
            entry = { minutes: 0, adjustedMinutes: 0 };
            minutesByPlayer.set(row.playerIdx, entry);
        }
        entry.minutes += row.minutes;
        entry.adjustedMinutes += row.adjustedMinutes;
    }

    const entries = [];
    minutesByPlayer.forEach(function (minuteTotals, playerIdx) {
        entries.push({
            playerIdx: playerIdx,
            minutes: minuteTotals.minutes,
            adjustedMinutes: minuteTotals.adjustedMinutes,
            score: scores.get(playerIdx) || 0,
        });
    });
    return entries;
}


/* ------------------------------------------------------------------ rendering */

function playerUrl(playerName) {
    // The player route uses a <path:> converter, so slashes must survive encoding.
    return "/player/" + encodeURIComponent(playerName).replace(/%2F/g, "/");
}

function renderLeaderboard(entries, payload, settings, tscarRanks) {
    const tbody = document.getElementById("leaderboard-body");

    // initTableSort attaches listeners and appends a sort indicator to every header, so the
    // header row is rebuilt from its original markup before each re-init.
    document.querySelector("#leaderboard-table thead").innerHTML = state.headerHtml;

    // GASP is already rescaled onto a fixed 0-10 range, so a per-10-minutes rate of it is
    // meaningless and the column is dropped entirely.
    const showPerTen = settings.formula !== "gasp";
    const perTenHeader = document.getElementById("per-ten-header");
    if (showPerTen) {
        perTenHeader.title = settings.blowoutAdjustment
            ? "Score per 10 blowout-adjusted minutes played"
            : "Score per 10 minutes played";
    } else {
        perTenHeader.remove();
    }
    const columnCount = showPerTen ? 5 : 4;

    if (!entries.length) {
        tbody.innerHTML =
            '<tr><td colspan="' + columnCount + '" style="text-align: center; padding: 2rem; color: #6c757d;">' +
            "No players found for this selection.</td></tr>";
        return;
    }

    entries.sort((a, b) => b.score - a.score);

    // entries are in Score order, so the index is the player's rank by Score.
    const html = entries.map(function (entry, index) {
        const player = payload.players[entry.playerIdx];
        // The blowout-adjustment checkbox decides the denominator, independent of the formula.
        const minutes = settings.blowoutAdjustment ? entry.adjustedMinutes : entry.minutes;
        const perTen = minutes > 0 ? (entry.score / minutes) * 10 : 0;
        const rankDelta = (tscarRanks.get(entry.playerIdx) || 0) - (index + 1);
        const rankLabel = rankDelta > 0 ? "+" + rankDelta : rankDelta < 0 ? String(rankDelta) : "—";
        const teamCell = player[3]
            ? '<a href="/team/' + player[4] + '/">' + escapeHtml(player[3]) + "</a>"
            : "—";

        return (
            "<tr>" +
            '<td class="team-name"><a href="' +
            escapeHtml(playerUrl(player[2])) +
            '">' +
            escapeHtml(player[1]) +
            "</a></td>" +
            '<td style="text-align: center;">' +
            teamCell +
            "</td>" +
            "<td>" +
            entry.score.toFixed(1) +
            "</td>" +
            (showPerTen ? "<td>" + perTen.toFixed(2) + "</td>" : "") +
            // An explicit sort value keeps the em dash and the "+" prefix out of the sorter.
            '<td data-sort-value="' +
            rankDelta +
            '">' +
            rankLabel +
            "</td>" +
            "</tr>"
        );
    });

    tbody.innerHTML = html.join("");
    initTableSort("#leaderboard-table", {
        initialSort: { column: SCORE_COLUMN_INDEX, direction: "desc" },
    });
}


/* ------------------------------------------------------------------ settings I/O */

function readWeights() {
    const weights = {};
    document.querySelectorAll(".weight-input").forEach(function (input) {
        if (input.disabled) {
            return;
        }
        const value = parseFloat(input.value);
        if (!isNaN(value) && value !== 0) {
            weights[input.dataset.stat] = value;
        }
    });
    return weights;
}

/** Every weight box's value, ignoring whether the current formula has disabled it. */
function readAllWeights() {
    const weights = {};
    document.querySelectorAll(".weight-input").forEach(function (input) {
        const value = parseFloat(input.value);
        if (!isNaN(value) && value !== 0) {
            weights[input.dataset.stat] = value;
        }
    });
    return weights;
}

/**
 * True when the form still holds a preset (or nothing) rather than the user's own numbers.
 *
 * Switching formula loads that formula's default weights, but only while this holds, so
 * hand-entered weights are never silently overwritten.
 */
function weightsAreUntouched() {
    const current = readAllWeights();
    const keys = Object.keys(current);
    if (!keys.length) {
        return true;
    }
    return [state.scarPresetWeights, state.gaspPresetWeights].some(function (preset) {
        const presetKeys = Object.keys(preset);
        return (
            presetKeys.length === keys.length &&
            presetKeys.every((key) => current[key] === preset[key])
        );
    });
}

function readSettings() {
    const replacement = parseFloat(document.getElementById("replacement-input").value);
    return {
        seasonId: document.getElementById("season-dropdown").value,
        week: document.getElementById("week-dropdown").value,
        formula: document.getElementById("formula-dropdown").value,
        blowoutAdjustment: document.getElementById("blowout-checkbox").checked,
        includeOvertime: document.getElementById("overtime-checkbox").checked,
        replacement: isNaN(replacement) ? 0 : replacement,
        weights: readWeights(),
    };
}

function applySettings(config) {
    const leagueDropdown = document.getElementById("league-dropdown");
    const seasonDropdown = document.getElementById("season-dropdown");

    // Find which league owns the saved season so the season dropdown can be repopulated.
    Object.keys(state.seasonsByLeague).forEach(function (leagueId) {
        const owns = state.seasonsByLeague[leagueId].some(
            (season) => String(season.id) === String(config.s)
        );
        if (owns) {
            leagueDropdown.value = leagueId;
        }
    });
    populateSeasons();
    seasonDropdown.value = String(config.s);

    document.getElementById("formula-dropdown").value = config.f;
    // A shared link records an explicit blowout choice, so don't let the formula override it.
    state.blowoutTouched = true;
    document.getElementById("blowout-checkbox").checked = config.b === 1;
    document.getElementById("overtime-checkbox").checked = config.o === 1;
    document.getElementById("replacement-input").value = config.r;

    setWeights(config.wt || {});
    onFormulaChange();

    return config.w;
}

function encodeConfig(settings) {
    const config = {
        v: CONFIG_VERSION,
        s: Number(settings.seasonId),
        w: settings.week,
        f: settings.formula,
        b: settings.blowoutAdjustment ? 1 : 0,
        o: settings.includeOvertime ? 1 : 0,
        r: settings.replacement,
        wt: settings.weights,
    };
    const bytes = new TextEncoder().encode(JSON.stringify(config));
    let binary = "";
    bytes.forEach(function (byte) {
        binary += String.fromCharCode(byte);
    });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decodeConfig(encoded) {
    try {
        const base64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i += 1) {
            bytes[i] = binary.charCodeAt(i);
        }
        const config = JSON.parse(new TextDecoder().decode(bytes));
        return config && config.v === CONFIG_VERSION ? config : null;
    } catch (error) {
        return null;
    }
}


/* ------------------------------------------------------------------ UI wiring */

function setWeights(weights) {
    document.querySelectorAll(".weight-input").forEach(function (input) {
        const value = weights[input.dataset.stat];
        input.value = value === undefined ? "" : value;
    });
    syncActionButtons();
}

/** There is nothing to generate or share until at least one weight is set. */
function syncActionButtons() {
    const hasWeights = Object.keys(readWeights()).length > 0;
    document.getElementById("generate-button").disabled = !hasWeights;
    document.getElementById("share-button").disabled = !hasWeights;
}

function setStatus(message, isError) {
    const status = document.getElementById("leaderboard-status");
    status.textContent = message || "";
    status.classList.toggle("status-error", Boolean(isError));
}

function populateSeasons() {
    const leagueId = document.getElementById("league-dropdown").value;
    const seasonDropdown = document.getElementById("season-dropdown");
    const seasons = state.seasonsByLeague[leagueId] || [];
    seasonDropdown.innerHTML = seasons
        .map((season) => '<option value="' + season.id + '">' + escapeHtml(season.name) + "</option>")
        .join("");
}

function populateWeeks(payload, selected) {
    const weekDropdown = document.getElementById("week-dropdown");
    const aggregates = [
        { value: "all_regular_season", label: "All Regular Season" },
        { value: "all_playoffs", label: "All Playoffs" },
        { value: "all_season", label: "All RS + Playoffs" },
    ];
    const options = aggregates.concat(
        payload.weeks.map((week) => ({ value: week, label: week }))
    );
    weekDropdown.innerHTML = options
        .map(
            (option) =>
                '<option value="' + escapeHtml(option.value) + '">' + escapeHtml(option.label) + "</option>"
        )
        .join("");
    if (selected && options.some((option) => option.value === selected)) {
        weekDropdown.value = selected;
    }
}

function onFormulaChange() {
    const isScar = document.getElementById("formula-dropdown").value === "scar";

    // The blowout adjustment is on by default for SCAR only, but stop steering it once the
    // user has expressed a preference of their own.
    if (!state.blowoutTouched) {
        document.getElementById("blowout-checkbox").checked = isScar;
    }

    document.getElementById("replacement-field").hidden = !isScar;

    // Stats SCAR already accounts for, plus every derived stat, drop out of the form in SCAR
    // mode (see hide_in_scar in custom_leaders.py). They are disabled as well as hidden so
    // readWeights skips whatever is still typed into them.
    document.querySelectorAll(".weight-cell-hide-in-scar").forEach(function (cell) {
        cell.hidden = isScar;
        cell.querySelector(".weight-input").disabled = isScar;
    });

    // Hiding stats can empty the effective weight set, so the buttons follow.
    syncActionButtons();
}

async function loadSeason(seasonId, weekToSelect) {
    if (!seasonId) {
        setStatus("No seasons available for this league.", false);
        return false;
    }
    if (state.payloads.has(seasonId)) {
        state.payload = state.payloads.get(seasonId);
        populateWeeks(state.payload, weekToSelect);
        return true;
    }

    setStatus("Loading season data…", false);
    try {
        const response = await fetch(
            "/leaders/custom/data/" + seasonId + "/?v=" + PAYLOAD_VERSION
        );
        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }
        const payload = await response.json();
        if (payload.version !== PAYLOAD_VERSION) {
            throw new Error("payload version " + payload.version);
        }
        state.payloads.set(seasonId, payload);
        state.payload = payload;
        populateWeeks(payload, weekToSelect);
        setStatus("", false);
        return true;
    } catch (error) {
        setStatus("Could not load season data. Please try again.", true);
        return false;
    }
}

function generate() {
    if (!state.payload) {
        setStatus("Season data is still loading. Try again in a moment.", false);
        return;
    }
    const settings = readSettings();
    if (!Object.keys(settings.weights).length) {
        document.getElementById("leaderboard-results").hidden = true;
        return;
    }

    const prepared = prepareRows(state.payload, settings);
    let entries;
    if (settings.formula === "scar") {
        entries = computeScar(prepared, state.payload, settings.weights, settings);
    } else if (settings.formula === "gasp") {
        entries = computeGasp(prepared, state.payload, settings.weights);
    } else {
        entries = computeAdditive(prepared, state.payload, settings.weights);
    }

    renderLeaderboard(entries, state.payload, settings, rankByStoredTscar(prepared));
    setStatus("", false);
    document.getElementById("leaderboard-results").hidden = false;
    state.live = true;
    updateShareLink(settings);
}

function updateShareLink(settings) {
    window.history.replaceState(null, "", "#c=" + encodeConfig(settings));
}

function scheduleRecompute() {
    if (!state.live) {
        return;
    }
    window.clearTimeout(state.recomputeTimer);
    state.recomputeTimer = window.setTimeout(generate, 150);
}

async function onSeasonChange() {
    state.live = false;
    document.getElementById("leaderboard-results").hidden = true;
    await loadSeason(document.getElementById("season-dropdown").value, null);
}

async function copyShareLink() {
    const button = document.getElementById("share-button");
    updateShareLink(readSettings());
    try {
        await navigator.clipboard.writeText(window.location.href);
        button.textContent = "Copied!";
    } catch (error) {
        button.textContent = "Press Ctrl+C to copy";
        window.prompt("Copy this link:", window.location.href);
    }
    window.setTimeout(function () {
        button.textContent = "Copy share link";
    }, 2000);
}

function presetFor(formula) {
    if (formula === "scar") {
        return state.scarPresetWeights;
    }
    if (formula === "gasp") {
        return state.gaspPresetWeights;
    }
    return null;
}

function onPresetChange(event) {
    const preset = event.target.value;
    if (preset === "clear") {
        setWeights({});
    } else if (presetFor(preset)) {
        setWeights(presetFor(preset));
    }
    event.target.value = "";
    scheduleRecompute();
}

async function init() {
    state.seasonsByLeague = JSON.parse(
        document.getElementById("seasons-by-league-data").textContent
    );
    state.scarPresetWeights = JSON.parse(
        document.getElementById("scar-preset-data").textContent
    );
    state.gaspPresetWeights = JSON.parse(
        document.getElementById("gasp-preset-data").textContent
    );
    state.headerHtml = document.querySelector("#leaderboard-table thead").innerHTML;

    document.getElementById("blowout-checkbox").addEventListener("change", function () {
        state.blowoutTouched = true;
    });

    document.getElementById("league-dropdown").addEventListener("change", function () {
        populateSeasons();
        onSeasonChange();
    });
    document.getElementById("season-dropdown").addEventListener("change", onSeasonChange);
    document.getElementById("formula-dropdown").addEventListener("change", function () {
        const preset = presetFor(document.getElementById("formula-dropdown").value);
        if (preset && weightsAreUntouched()) {
            setWeights(preset);
        }
        onFormulaChange();
        scheduleRecompute();
    });
    document.getElementById("preset-dropdown").addEventListener("change", onPresetChange);
    document.getElementById("generate-button").addEventListener("click", generate);
    document.getElementById("share-button").addEventListener("click", copyShareLink);

    ["week-dropdown", "blowout-checkbox", "overtime-checkbox", "replacement-input"].forEach(
        function (id) {
            document.getElementById(id).addEventListener("change", scheduleRecompute);
        }
    );
    document.querySelectorAll(".weight-input").forEach(function (input) {
        input.addEventListener("input", function () {
            syncActionButtons();
            scheduleRecompute();
        });
    });

    populateSeasons();
    onFormulaChange();

    const hash = window.location.hash;
    if (hash.startsWith("#c=")) {
        const config = decodeConfig(hash.slice(3));
        if (config) {
            const week = applySettings(config);
            const loaded = await loadSeason(String(config.s), week);
            if (loaded) {
                generate();
            }
            return;
        }
    }

    // Default landing state: newest season of the first league, SCAR weights preloaded.
    setWeights(state.scarPresetWeights);
    document.getElementById("formula-dropdown").value = "scar";
    onFormulaChange();
    await loadSeason(document.getElementById("season-dropdown").value, null);
}

document.addEventListener("DOMContentLoaded", init);
