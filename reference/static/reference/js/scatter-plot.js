/**
 * Small SVG scatter plots comparing one player against the rest of the league.
 * Usage: renderScatterCharts(container, charts), where each chart is
 * {x_label, y_label, points: [{name, x, y, x_display, y_display, is_viewed}]}.
 * Hovering or tapping near a point shows the player's name and both values.
 */

const SVG_NS = "http://www.w3.org/2000/svg";
// Sizes are in SVG units; the SVG is scaled to its container's width by CSS.
const CHART_WIDTH = 320;
const CHART_HEIGHT = 240;
const CHART_MARGIN = { top: 10, right: 12, bottom: 40, left: 50 };
// Gap between the axes and the nearest possible point, so points never sit on an axis line
const PLOT_INSET = 6;
const TARGET_TICK_COUNT = 4;
// Multiples of a power of 10 that make round tick steps, largest first
const TICK_STEP_MULTIPLIERS = [5, 2.5, 2, 1, 0.5, 0.25, 0.2, 0.1];
const FLOAT_TOLERANCE = 1e-9;
const OTHER_POINT_RADIUS = 2.5;
const VIEWED_POINT_RADIUS = 5.5;
const VIEWED_POINT_COLOR = "#57c";
const HOVER_DISTANCE = 14;

function renderScatterCharts(container, charts) {
    charts.forEach(chart => container.appendChild(buildScatterChart(chart)));
}

function chooseTickStep(min, max) {
    // Of the round steps (so labels are easy to read), pick the one that puts closest to
    // TARGET_TICK_COUNT ticks within the data's range, preferring the larger step on ties
    const magnitude = Math.pow(10, Math.floor(Math.log10(max - min)));
    let bestStep = null;
    let bestDistance = Infinity;
    for (const multiplier of TICK_STEP_MULTIPLIERS) {
        const step = multiplier * magnitude;
        const firstTick = Math.ceil(min / step - FLOAT_TOLERANCE) * step;
        const tickCount = Math.floor((max - firstTick) / step + FLOAT_TOLERANCE) + 1;
        const distance = Math.abs(tickCount - TARGET_TICK_COUNT);
        if (distance < bestDistance) {
            bestStep = step;
            bestDistance = distance;
        }
    }
    return bestStep;
}

function countDecimals(step) {
    // Fewest decimal places that show every multiple of step exactly (e.g. 2 for 0.25)
    let decimals = 0;
    while (Math.abs(Math.round(step * 10 ** decimals) - step * 10 ** decimals) > FLOAT_TOLERANCE) {
        decimals++;
    }
    return decimals;
}

function buildAxisScale(values, pixelStart, pixelEnd) {
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (min === max) {
        min -= 1;
        max += 1;
    }
    const step = chooseTickStep(min, max);
    const decimals = countDecimals(step);

    const ticks = [];
    const firstIndex = Math.ceil(min / step - FLOAT_TOLERANCE);
    for (let i = firstIndex; i * step <= max + FLOAT_TOLERANCE * step; i++) {
        ticks.push(i * step);
    }

    const toPixel = value => pixelStart + ((value - min) / (max - min)) * (pixelEnd - pixelStart);
    return { ticks, decimals, toPixel };
}

function createSvgElement(tag, attributes) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, value));
    return element;
}

function createSvgText(text, attributes) {
    const element = createSvgElement("text", attributes);
    element.textContent = text;
    return element;
}

function drawXAxis(svg, scale, label, plot) {
    svg.appendChild(createSvgElement("line", {
        x1: plot.left, y1: plot.bottom, x2: plot.right, y2: plot.bottom, class: "scatter-axis",
    }));
    scale.ticks.forEach(tick => {
        const x = scale.toPixel(tick);
        svg.appendChild(createSvgElement("line", {
            x1: x, y1: plot.bottom, x2: x, y2: plot.bottom + 4, class: "scatter-axis",
        }));
        svg.appendChild(createSvgText(tick.toFixed(scale.decimals), {
            x: x, y: plot.bottom + 15, "text-anchor": "middle", class: "scatter-tick-label",
        }));
    });
    svg.appendChild(createSvgText(label, {
        x: (plot.left + plot.right) / 2, y: CHART_HEIGHT - 4,
        "text-anchor": "middle", class: "scatter-axis-title",
    }));
}

function drawYAxis(svg, scale, label, plot) {
    svg.appendChild(createSvgElement("line", {
        x1: plot.left, y1: plot.top, x2: plot.left, y2: plot.bottom, class: "scatter-axis",
    }));
    scale.ticks.forEach(tick => {
        const y = scale.toPixel(tick);
        svg.appendChild(createSvgElement("line", {
            x1: plot.left - 4, y1: y, x2: plot.left, y2: y, class: "scatter-axis",
        }));
        svg.appendChild(createSvgText(tick.toFixed(scale.decimals), {
            x: plot.left - 7, y: y + 4, "text-anchor": "end", class: "scatter-tick-label",
        }));
    });
    const titleX = 12;
    const titleY = (plot.top + plot.bottom) / 2;
    svg.appendChild(createSvgText(label, {
        x: titleX, y: titleY, "text-anchor": "middle", class: "scatter-axis-title",
        transform: `rotate(-90 ${titleX} ${titleY})`,
    }));
}

function buildScatterChart(chart) {
    const plot = {
        left: CHART_MARGIN.left,
        right: CHART_WIDTH - CHART_MARGIN.right,
        top: CHART_MARGIN.top,
        bottom: CHART_HEIGHT - CHART_MARGIN.bottom,
    };
    const xScale = buildAxisScale(
        chart.points.map(p => p.x), plot.left + PLOT_INSET, plot.right - PLOT_INSET
    );
    const yScale = buildAxisScale(
        chart.points.map(p => p.y), plot.bottom - PLOT_INSET, plot.top + PLOT_INSET
    );

    const wrapper = document.createElement("div");
    wrapper.className = "scatter-chart";
    const svg = createSvgElement("svg", {
        viewBox: `0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`,
        role: "img",
        "aria-label": `${chart.y_label} vs ${chart.x_label}`,
    });
    wrapper.appendChild(svg);

    drawXAxis(svg, xScale, chart.x_label, plot);
    drawYAxis(svg, yScale, chart.y_label, plot);

    const placedPoints = chart.points.map(point => ({
        point: point,
        cx: xScale.toPixel(point.x),
        cy: yScale.toPixel(point.y),
    }));
    // Draw the viewed player last so their point sits on top of everyone else's
    const drawOrder = [...placedPoints].sort((a, b) => a.point.is_viewed - b.point.is_viewed);
    drawOrder.forEach(placed => {
        svg.appendChild(createSvgElement("circle", {
            cx: placed.cx,
            cy: placed.cy,
            r: placed.point.is_viewed ? VIEWED_POINT_RADIUS : OTHER_POINT_RADIUS,
            class: placed.point.is_viewed ? "scatter-point-viewed" : "scatter-point",
            fill: placed.point.is_viewed ? VIEWED_POINT_COLOR : "#000",
        }));
    });

    const highlight = createSvgElement("circle", { r: 7, class: "scatter-highlight" });
    highlight.style.display = "none";
    svg.appendChild(highlight);

    const tooltip = document.createElement("div");
    tooltip.className = "scatter-tooltip";
    tooltip.hidden = true;
    wrapper.appendChild(tooltip);

    attachTooltip(svg, wrapper, tooltip, highlight, placedPoints, chart);
    return wrapper;
}

function findNearestPoint(placedPoints, x, y) {
    let nearest = null;
    let nearestDistance = HOVER_DISTANCE;
    placedPoints.forEach(placed => {
        const distance = Math.hypot(placed.cx - x, placed.cy - y);
        // Prefer the viewed player when points overlap, since that's who people look for
        if (distance < nearestDistance || (distance === nearestDistance && placed.point.is_viewed)) {
            nearest = placed;
            nearestDistance = distance;
        }
    });
    return nearest;
}

function showTooltip(tooltip, wrapper, placed, chart, scaleFactor) {
    tooltip.replaceChildren();
    const name = document.createElement("strong");
    name.textContent = placed.point.name;
    tooltip.appendChild(name);
    [
        `${chart.y_label}: ${placed.point.y_display}`,
        `${chart.x_label}: ${placed.point.x_display}`,
    ].forEach(text => {
        const line = document.createElement("div");
        line.textContent = text;
        tooltip.appendChild(line);
    });
    tooltip.hidden = false;

    // Position beside the point, flipping to its left side if it would overflow the chart
    const pointX = placed.cx * scaleFactor;
    const pointY = placed.cy * scaleFactor;
    const offset = 10;
    let left = pointX + offset;
    if (left + tooltip.offsetWidth > wrapper.clientWidth) {
        left = pointX - offset - tooltip.offsetWidth;
    }
    tooltip.style.left = `${Math.max(0, left)}px`;
    tooltip.style.top = `${Math.max(0, pointY - tooltip.offsetHeight / 2)}px`;
}

function attachTooltip(svg, wrapper, tooltip, highlight, placedPoints, chart) {
    const hide = () => {
        tooltip.hidden = true;
        highlight.style.display = "none";
    };
    const update = event => {
        const rect = svg.getBoundingClientRect();
        const scaleFactor = rect.width / CHART_WIDTH;
        const x = (event.clientX - rect.left) / scaleFactor;
        const y = (event.clientY - rect.top) / scaleFactor;
        const nearest = findNearestPoint(placedPoints, x, y);
        if (!nearest) {
            hide();
            return;
        }
        highlight.setAttribute("cx", nearest.cx);
        highlight.setAttribute("cy", nearest.cy);
        highlight.style.display = "";
        showTooltip(tooltip, wrapper, nearest, chart, scaleFactor);
    };
    svg.addEventListener("pointermove", update);
    svg.addEventListener("pointerdown", update);
    svg.addEventListener("pointerleave", event => {
        // Touch input fires pointerleave right after a tap, which would hide the tooltip at once
        if (event.pointerType === "mouse") {
            hide();
        }
    });
}
