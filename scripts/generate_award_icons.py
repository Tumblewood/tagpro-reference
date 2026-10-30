"""
Generates SVG icons for championships (trophies), playing awards (medals), and
non-playing awards (ribbons).

Usage: python scripts/generate_award_icons.py [output_dir]
Defaults to writing into reference/static/reference/awards/.

Medals are written as medal_<award>_<strap color>_<placement>.svg, ribbons as
ribbon_<award>_<placement>.svg, and trophies as trophy_<competition>.svg.
reference/utils/award_icons.py relies on these names (and the strap color names
in LEAGUE_COLORS) to pick an icon for each award.
"""

import math
import os
import sys

DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "reference",
    "static",
    "reference",
    "awards",
)

OUTLINE = 2

# Flat metal palettes: face is the main fill, ring is the slightly darker
# secondary fill, icon is used for stamped details, edge for outlines.
METALS = {
    "gold": {"light": "#ffe58a", "face": "#f6c637", "ring": "#e3a81d", "icon": "#a66f0c", "edge": "#6e4a06"},
    "silver": {"light": "#f7f8fa", "face": "#d6dbe1", "ring": "#b6bec7", "icon": "#6b737c", "edge": "#474e56"},
    "bronze": {"light": "#f3c194", "face": "#d68c4c", "ring": "#b8702f", "icon": "#7a4317", "edge": "#53300f"},
    "ice": {"light": "#ffffff", "face": "#c4e8ff", "ring": "#8ccaf0", "icon": "#3f8cc0", "edge": "#245f88"},
}
PLACEMENT_METALS = {1: "gold", 2: "silver", 3: "bronze"}

LEAGUE_COLORS = {
    "blue": {"main": "#2f6fd6", "back": "#2559ad", "edge": "#163f87"},
    "red": {"main": "#d63a3a", "back": "#b02c2c", "edge": "#7d1717"},
    "orange": {"main": "#f5a31a", "back": "#d98a0b", "edge": "#8a5400"},
    "green": {"main": "#2e9e4f", "back": "#23813f", "edge": "#145226"},
    "white": {"main": "#f7f7f7", "back": "#dcdcdc", "edge": "#7d7d7d"},
}

RIBBON_COLORS = {
    1: {"main": "#2a63c9", "inner": "#4f86e3", "edge": "#163a80", "icon": "#163a80"},
    2: {"main": "#d03434", "inner": "#e45f5f", "edge": "#7d1717", "icon": "#7d1717"},
    3: {"main": "#f2c12e", "inner": "#f8d661", "edge": "#8a6a00", "icon": "#6b5000"},
}
RIBBON_BUTTON = {"fill": "#fdf6e0", "edge": "#c9a227"}

WOOD = {"main": "#5b3a1e", "edge": "#2e1c0b"}

# Where the flexed arm's fist holds a mini flag or shield, in the arm icon's 24x24 box
HELD_ICON_OFFSETS = {"flag": (11.6, -0.5), "shield": (11, 1)}
STRAP_STRIPE_COLOR = "#111111"

# Trophy file name -> (style, options)
TROPHIES = {
    "trophy_mltp": ("classic", {"plate": "blue"}),
    "trophy_mltp_minors": ("classic", {"plate": "red"}),
    "trophy_nltp": ("classic", {"plate": "orange"}),
    "trophy_nltp_b": ("classic", {"plate": "green"}),
    "trophy_oltp": ("classic", {"plate": "blue", "upside_down": True}),
    "trophy_oltp_minors": ("classic", {"plate": "red", "upside_down": True}),
    "trophy_eltp": ("world_cup", {"band": "blue"}),
    "trophy_eltp_minors": ("world_cup", {"band": "red"}),
    "trophy_enltp": ("world_cup", {"band": "orange"}),
    "trophy_frozen_balls": ("snowflake", {}),
    "trophy_generic": ("generic", {}),
}

# Medal award key -> (icon name, icon options, striped strap)
MEDALS = {
    "mvb": ("ball_crown", {}, True),
    "obos": ("flag", {}, True),
    "dbos": ("shield", {}, True),
    "all_star": ("star", {}, False),
    "all_star_o": ("star", {"inner": "flag"}, False),
    "all_star_d": ("star", {"inner": "shield"}, False),
    "best_valued": ("tagcoin", {}, False),
    "fu_gasp": ("middle_finger", {}, False),
    "most_improved": ("line_chart", {}, False),
    "notable_disappearance": ("ghost", {}, False),
    "best_call_up": ("up_arrow", {}, False),
    "best_5th_ball": ("five", {}, False),
    "ros": ("sprout", {}, False),
    "oros": ("sprout", {"inner": "flag"}, False),
    "dros": ("sprout", {"inner": "shield"}, False),
    "well_rounded": ("scales", {}, False),
    "best_offense_pair": ("double_flags", {}, False),
    "best_defense_pair": ("double_shields", {}, False),
    "most_cohesive_unit": ("chain", {}, False),
    "position_change": ("swap", {}, False),
    "best_individual_performance": ("flexed_arm", {}, False),
    "best_offensive_performance": ("flexed_arm", {"inner": "flag"}, False),
    "best_defensive_performance": ("flexed_arm", {"inner": "shield"}, False),
    "team_ball_o": ("team_balls", {"inner": "flag"}, False),
    "team_ball_d": ("team_balls", {"inner": "shield"}, False),
    "best_veteran": ("chevrons", {}, False),
    "forget_mltp": ("no_majors", {}, False),
    "deceiving_record": ("mask", {}, False),
    "random_stat": ("die", {}, False),
    "ball_of_fame": ("laurel", {}, False),
}

# Ribbon award key -> icon name
RIBBONS = {
    "best_streamer": "video_camera",
    "best_commentator": "microphone",
    "behind_the_scenes": "pillar",
    "best_captain": "captain_hat",
    "best_co_captain": "sailor_hat",
    "heart": "heart",
    "best_roster_moves": "clipboard",
    "community_contributor": "people",
}

# Leaf centers and angles for one side of the laurel wreath, in a 24x24 box
LAUREL_LEAVES = [(9.6, 20.6, -15), (6.4, 18.2, -40), (4.4, 14.8, -62), (3.6, 11, -80), (4, 7.2, -100), (5.4, 3.8, -120)]


def svg_document(body):
    """Wraps body markup in a 64x64 SVG document."""
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64' width='64' height='64'>"
        f"{body}</svg>\n"
    )


def star_points(cx, cy, outer, inner, count, rotation=-90):
    """Returns a polygon points string for a star with the given number of points."""
    points = []
    for i in range(count * 2):
        radius = outer if i % 2 == 0 else inner
        angle = math.radians(rotation + i * 180 / count)
        points.append(f"{cx + radius * math.cos(angle):.2f},{cy + radius * math.sin(angle):.2f}")
    return " ".join(points)


def place_icon(markup, cx, cy, size):
    """Positions a 24x24 icon so it is centered at (cx, cy) with the given size."""
    scale = size / 24
    return f"<g transform='translate({cx - size / 2:.2f} {cy - size / 2:.2f}) scale({scale:.4f})'>{markup}</g>"


def mini_icon(name, fg, bg, x, y, size):
    """Draws a small secondary icon (like the flag held by the flexed arm) inside another icon's 24x24 box."""
    scale = size / 24
    return f"<g transform='translate({x} {y}) scale({scale:.4f})'>{ICONS[name](fg, bg)}</g>"


# ---------------------------------------------------------------------------
# Icons. Each is drawn in a 24x24 box and takes a foreground color plus a
# background color for cut-out details.
# ---------------------------------------------------------------------------


def icon_flag(fg, bg):
    return (
        f"<rect x='3.5' y='1.5' width='3.2' height='21' rx='1.6' fill='{fg}'/>"
        f"<polygon points='6.7,1.5 22.5,8 6.7,14.5' fill='{fg}' stroke='{fg}' stroke-width='1' stroke-linejoin='round'/>"
    )


def icon_shield(fg, bg):
    return f"<path d='M12 1.5 L21.5 4.8 V11 C21.5 16.6 17.5 20.6 12 22.8 C6.5 20.6 2.5 16.6 2.5 11 V4.8 Z' fill='{fg}'/>"


def icon_ball_crown(fg, bg):
    return (
        f"<circle cx='12' cy='15.7' r='7.3' fill='{fg}'/>"
        f"<polygon points='4.5,7.2 4.5,1 8.3,4.2 12,0.5 15.7,4.2 19.5,1 19.5,7.2' fill='{fg}'/>"
        f"<path d='M8.2 13.6 A4.3 4.3 0 0 1 10.9 11' fill='none' stroke='{bg}' stroke-width='1.6' stroke-linecap='round'/>"
    )


def icon_star(fg, bg, inner=None):
    markup = f"<polygon points='{star_points(12, 13, 12.5, 6.3, 5)}' fill='{fg}' stroke='{fg}' stroke-width='1.5' stroke-linejoin='round'/>"
    if inner:
        markup += mini_icon(inner, bg, fg, 7.3, 8.6, 9.4)
    return markup


def icon_tagcoin(fg, bg):
    return (
        f"<rect x='3' y='2' width='18' height='4' rx='1' fill='{fg}'/>"
        f"<rect x='10' y='2' width='4' height='20.5' rx='1' fill='{fg}'/>"
        f"<rect x='6' y='9.5' width='12' height='2.8' rx='1' fill='{fg}'/>"
        f"<rect x='6' y='14.7' width='12' height='2.8' rx='1' fill='{fg}'/>"
    )


def icon_middle_finger(fg, bg):
    return (
        f"<rect x='9.4' y='0.8' width='5.2' height='14' rx='2.6' fill='{fg}'/>"
        f"<rect x='4' y='10' width='16' height='13' rx='4' fill='{fg}'/>"
        f"<path d='M9.4 10.6 V14.2 M14.6 10.6 V14.2 M6 18 H13.5' stroke='{bg}' stroke-width='1.3' stroke-linecap='round'/>"
    )


def icon_line_chart(fg, bg):
    return (
        f"<path d='M2.5 2 V21.5 H22' fill='none' stroke='{fg}' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>"
        f"<polyline points='6.5,17 10.5,11.5 13.8,14.5 18,8.5' fill='none' stroke='{fg}' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>"
        f"<polygon points='14.2,5.6 22,3 21,11' fill='{fg}' stroke='{fg}' stroke-width='1' stroke-linejoin='round'/>"
    )


def icon_ghost(fg, bg):
    return (
        "<path d='M3.5 22.5 V11 C3.5 5.5 7.3 1.5 12 1.5 C16.7 1.5 20.5 5.5 20.5 11 V22.5 "
        f"L17.7 19.8 L14.9 22.5 L12 19.8 L9.1 22.5 L6.3 19.8 Z' fill='{fg}'/>"
        f"<ellipse cx='8.8' cy='10' rx='1.8' ry='2.5' fill='{bg}'/>"
        f"<ellipse cx='15.2' cy='10' rx='1.8' ry='2.5' fill='{bg}'/>"
    )


def icon_up_arrow(fg, bg):
    return f"<polygon points='12,1.5 22.5,12 16.2,12 16.2,22.5 7.8,22.5 7.8,12 1.5,12' fill='{fg}' stroke='{fg}' stroke-width='1' stroke-linejoin='round'/>"


def icon_five(fg, bg):
    return (
        "<path d='M18 3 H8.2 L7 11 C8.8 10.2 10.3 9.8 12 9.8 C16 9.8 18.5 12.4 18.5 15.9 "
        f"C18.5 19.6 15.6 22 12 22 C9.3 22 7.1 20.9 5.8 18.9' fill='none' stroke='{fg}' stroke-width='3.6' stroke-linecap='round' stroke-linejoin='round'/>"
    )


def icon_sprout(fg, bg, inner=None):
    ground_end = 13 if inner else 19
    sprout = (
        f"<path d='M12 22 V11' stroke='{fg}' stroke-width='3' stroke-linecap='round'/>"
        f"<path d='M12 13.5 C5.5 13.5 2 9.8 2 4.5 C8 4.5 12 7.8 12 13.5 Z' fill='{fg}'/>"
        f"<path d='M12 11 C12 5.8 15.3 2 22 2 C22 7.6 18.2 11 12 11 Z' fill='{fg}'/>"
        f"<path d='M5 22 H{ground_end}' stroke='{fg}' stroke-width='3' stroke-linecap='round'/>"
    )
    if not inner:
        return sprout
    return f"<g transform='translate(-3 0)'>{sprout}</g>{mini_icon(inner, fg, bg, 12.5, 11.5, 12)}"


def icon_scales(fg, bg):
    return (
        f"<circle cx='12' cy='3' r='2' fill='{fg}'/>"
        f"<path d='M12 4 V20 M6.5 21.5 H17.5 M3.5 6.5 H20.5' stroke='{fg}' stroke-width='2.6' stroke-linecap='round'/>"
        f"<path d='M3.5 6.5 L1 13 M3.5 6.5 L6 13 M20.5 6.5 L18 13 M20.5 6.5 L23 13' stroke='{fg}' stroke-width='1.3'/>"
        f"<path d='M0.3 13 H6.7 A3.2 3.2 0 0 1 0.3 13 Z M17.3 13 H23.7 A3.2 3.2 0 0 1 17.3 13 Z' fill='{fg}'/>"
    )


def icon_double_flags(fg, bg):
    return (
        f"<g transform='translate(-0.5 0) scale(0.78)'>{icon_flag(fg, bg)}</g>"
        f"<g transform='translate(6.2 5) scale(0.78)' stroke='{bg}' stroke-width='3' paint-order='stroke'>{icon_flag(fg, bg)}</g>"
    )


def icon_double_shields(fg, bg):
    shield = "M12 1.5 L21.5 4.8 V11 C21.5 16.6 17.5 20.6 12 22.8 C6.5 20.6 2.5 16.6 2.5 11 V4.8 Z"
    return (
        f"<path d='{shield}' fill='{fg}' transform='translate(-1.4 0) scale(0.76)'/>"
        f"<path d='{shield}' fill='{fg}' stroke='{bg}' stroke-width='2.4' paint-order='stroke' transform='translate(6.6 5.2) scale(0.76)'/>"
    )


def icon_chain(fg, bg):
    link = "<rect x='-7' y='-3.9' width='14' height='7.8' rx='3.9' fill='none' stroke='{color}' stroke-width='{width}'/>"
    first = f"<g transform='translate(8.2 15.8) rotate(-45)'>{link.format(color=fg, width=3)}</g>"
    second_gap = f"<g transform='translate(15.8 8.2) rotate(-45)'>{link.format(color=bg, width=5.4)}</g>"
    second = f"<g transform='translate(15.8 8.2) rotate(-45)'>{link.format(color=fg, width=3)}</g>"
    # Redraw the part of the first link that passes over the second so they interlock.
    overlap = f"<path d='M9.5 9.6 L13.4 13.5' stroke='{bg}' stroke-width='5.4'/><path d='M9.5 9.6 L13.4 13.5' stroke='{fg}' stroke-width='3'/>"
    return first + second_gap + second + overlap


def icon_swap(fg, bg):
    arrow = (
        f"<path d='M3 10 C5 4.5 12 3 17 6' fill='none' stroke='{fg}' stroke-width='2.8' stroke-linecap='round'/>"
        f"<polygon points='21.5,8.8 13.8,9.4 17.6,2.8' fill='{fg}' stroke='{fg}' stroke-width='1' stroke-linejoin='round'/>"
    )
    return f"{arrow}<g transform='rotate(180 12 12)'>{arrow}</g>"


def icon_flexed_arm(fg, bg, inner=None):
    arm = (
        "<path d='M1 23 V15.5 C1 11.8 3.4 9 6.8 8.4 C10 7.8 12.9 9.6 14 12.8 L14.6 9.6 C12.9 9 11.5 7.5 11.7 5.6 "
        "C12 2.9 14.1 1 16.8 1 H19.8 C21.6 1 23 2.4 23 4.2 V8.5 C23.1 12 23.4 16 22.9 19.2 "
        f"C22.5 21.6 20.6 23 18 23 Z' fill='{fg}'/>"
        f"<path d='M14.3 5.4 C16 4.5 18 4.5 20.2 5.4 M14 12.8 C14.7 15 16.1 16.4 18.2 17.2' fill='none' stroke='{bg}' stroke-width='1.3' stroke-linecap='round'/>"
    )
    if not inner:
        return arm
    # The held flag or shield sits in front of the fist, outlined so it stays distinct.
    held_x, held_y = HELD_ICON_OFFSETS[inner]
    held = mini_icon(inner, fg, bg, held_x, held_y, 11)
    return (
        f"<g transform='translate(0 4.8) scale(0.8)'>{arm}</g>"
        f"<g stroke='{bg}' stroke-width='3' paint-order='stroke'>{held}</g>"
    )


def icon_video_camera(fg, bg):
    return (
        f"<rect x='1' y='6' width='15' height='12.5' rx='2.5' fill='{fg}'/>"
        f"<polygon points='16,10.5 23,6.5 23,18 16,14' fill='{fg}' stroke='{fg}' stroke-width='1' stroke-linejoin='round'/>"
        f"<circle cx='6' cy='10.5' r='2' fill='{bg}'/>"
    )


def icon_microphone(fg, bg):
    return (
        f"<rect x='7.8' y='1' width='8.4' height='13.5' rx='4.2' fill='{fg}'/>"
        f"<path d='M10 5.5 H14 M10 8.8 H14' stroke='{bg}' stroke-width='1.3' stroke-linecap='round'/>"
        f"<path d='M4.5 10.5 V11 C4.5 15.3 7.8 18.3 12 18.3 C16.2 18.3 19.5 15.3 19.5 11 V10.5' fill='none' stroke='{fg}' stroke-width='2.4' stroke-linecap='round'/>"
        f"<path d='M12 18.3 V21.8 M7.5 22 H16.5' stroke='{fg}' stroke-width='2.4' stroke-linecap='round'/>"
    )


def icon_pillar(fg, bg):
    return (
        f"<rect x='2' y='1.5' width='20' height='3.6' rx='0.8' fill='{fg}'/>"
        f"<rect x='4.5' y='5.1' width='15' height='2' fill='{fg}'/>"
        f"<rect x='6.5' y='7.1' width='11' height='11.3' fill='{fg}'/>"
        f"<path d='M9.8 8.8 V16.7 M14.2 8.8 V16.7' stroke='{bg}' stroke-width='1.3' stroke-linecap='round'/>"
        f"<rect x='4.5' y='18.4' width='15' height='2' fill='{fg}'/>"
        f"<rect x='2' y='20.4' width='20' height='3.1' rx='0.8' fill='{fg}'/>"
    )


def icon_captain_hat(fg, bg):
    return (
        f"<path d='M1 9.5 C1 3.8 23 3.8 23 9.5 C23 11.6 19.8 12.6 18.2 13 H5.8 C4.2 12.6 1 11.6 1 9.5 Z' fill='{fg}'/>"
        f"<rect x='5.8' y='13' width='12.4' height='3.6' fill='{bg}' stroke='{fg}' stroke-width='1.4'/>"
        f"<path d='M4.6 16.6 H19.4 C18.4 21.6 5.6 21.6 4.6 16.6 Z' fill='{fg}'/>"
        f"<circle cx='12' cy='8.8' r='2.1' fill='{bg}'/>"
    )


def icon_sailor_hat(fg, bg):
    return (
        f"<path d='M6.5 13 C6.5 7 17.5 7 17.5 13 Z' fill='{fg}'/>"
        f"<path d='M3 12.5 H21 C21 16 19.5 17.5 17 17.5 H7 C4.5 17.5 3 16 3 12.5 Z' fill='{fg}'/>"
        f"<path d='M6 14.6 H18' stroke='{bg}' stroke-width='1.2' stroke-linecap='round'/>"
    )


def icon_heart(fg, bg):
    return (
        "<path d='M12 22 C4.8 16.4 1 12.8 1 8 C1 4.6 3.7 2 7 2 C9.1 2 11 3.3 12 5.4 "
        f"C13 3.3 14.9 2 17 2 C20.3 2 23 4.6 23 8 C23 12.8 19.2 16.4 12 22 Z' fill='{fg}'/>"
    )


def icon_team_balls(fg, bg, inner=None):
    markup = (
        f"<circle cx='5.2' cy='6.8' r='4.7' fill='{fg}'/>"
        f"<circle cx='18.8' cy='6.8' r='4.7' fill='{fg}'/>"
        f"<circle cx='12' cy='15.3' r='7.6' fill='{fg}' stroke='{bg}' stroke-width='2.4'/>"
    )
    if inner:
        markup += mini_icon(inner, bg, fg, 7.5, 10.8, 9)
    return markup


def icon_chevrons(fg, bg):
    return f"<path d='M3.5 10 L12 4.5 L20.5 10 M3.5 15.2 L12 9.7 L20.5 15.2 M3.5 20.4 L12 14.9 L20.5 20.4' fill='none' stroke='{fg}' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'/>"


def icon_no_majors(fg, bg):
    return (
        f"<path d='M7.5 17 V7.5 L12 12.5 L16.5 7.5 V17' fill='none' stroke='{fg}' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>"
        f"<path d='M5 5 L19 19' stroke='{bg}' stroke-width='4.2'/>"
        f"<path d='M5 5 L19 19' stroke='{fg}' stroke-width='2.2'/>"
        f"<circle cx='12' cy='12' r='10' fill='none' stroke='{fg}' stroke-width='2.6'/>"
    )


def icon_mask(fg, bg):
    return (
        "<path d='M1.5 7.5 C5 5.5 9 6 12 8.5 C15 6 19 5.5 22.5 7.5 C23 13 20.5 17 16.5 17 "
        f"C14 17 12.8 15 12 13.5 C11.2 15 10 17 7.5 17 C3.5 17 1 13 1.5 7.5 Z' fill='{fg}'/>"
        f"<ellipse cx='7' cy='11.3' rx='2.8' ry='1.9' fill='{bg}'/>"
        f"<ellipse cx='17' cy='11.3' rx='2.8' ry='1.9' fill='{bg}'/>"
    )


def icon_die(fg, bg):
    pips = "".join(
        f"<circle cx='{x}' cy='{y}' r='1.9' fill='{bg}'/>"
        for x, y in [(7.5, 7.5), (16.5, 7.5), (12, 12), (7.5, 16.5), (16.5, 16.5)]
    )
    return f"<rect x='2.5' y='2.5' width='19' height='19' rx='4' fill='{fg}'/>{pips}"


def icon_laurel(fg, bg):
    leaves = "".join(
        f"<ellipse cx='{x}' cy='{y}' rx='3.2' ry='1.7' transform='rotate({angle} {x} {y})' fill='{fg}'/>"
        for x, y, angle in LAUREL_LEAVES
    )
    branch = f"<path d='M11 22 C5 20 2.4 14 3.8 3' fill='none' stroke='{fg}' stroke-width='1.4' stroke-linecap='round'/>{leaves}"
    return (
        f"{branch}<g transform='translate(24 0) scale(-1 1)'>{branch}</g>"
        f"<circle cx='12' cy='11.5' r='4.8' fill='{fg}'/>"
    )


def icon_clipboard(fg, bg):
    return (
        f"<rect x='3.5' y='3' width='17' height='20' rx='2' fill='{fg}'/>"
        f"<rect x='8' y='1' width='8' height='4.5' rx='1.2' fill='{fg}' stroke='{bg}' stroke-width='1.2'/>"
        f"<path d='M7.5 10 H16.5 M7.5 14 H16.5 M7.5 18 H13' stroke='{bg}' stroke-width='1.6' stroke-linecap='round'/>"
    )


def icon_people(fg, bg):
    side_person = (
        f"<circle cx='4.8' cy='8.5' r='2.8' fill='{fg}'/>"
        f"<path d='M0.5 19.5 C0.5 15 2.3 12.8 4.8 12.8 C7.3 12.8 9 15 9 19.5 Z' fill='{fg}'/>"
    )
    return (
        f"{side_person}<g transform='translate(24 0) scale(-1 1)'>{side_person}</g>"
        f"<circle cx='12' cy='7' r='3.8' fill='{fg}' stroke='{bg}' stroke-width='1.4'/>"
        f"<path d='M5.5 21.5 C5.5 15.5 8.3 12.5 12 12.5 C15.7 12.5 18.5 15.5 18.5 21.5 Z' fill='{fg}' stroke='{bg}' stroke-width='1.4' stroke-linejoin='round'/>"
    )


ICONS = {
    "flag": icon_flag,
    "shield": icon_shield,
    "ball_crown": icon_ball_crown,
    "star": icon_star,
    "tagcoin": icon_tagcoin,
    "middle_finger": icon_middle_finger,
    "line_chart": icon_line_chart,
    "ghost": icon_ghost,
    "up_arrow": icon_up_arrow,
    "five": icon_five,
    "sprout": icon_sprout,
    "scales": icon_scales,
    "double_flags": icon_double_flags,
    "double_shields": icon_double_shields,
    "chain": icon_chain,
    "swap": icon_swap,
    "flexed_arm": icon_flexed_arm,
    "video_camera": icon_video_camera,
    "microphone": icon_microphone,
    "pillar": icon_pillar,
    "captain_hat": icon_captain_hat,
    "sailor_hat": icon_sailor_hat,
    "heart": icon_heart,
    "team_balls": icon_team_balls,
    "chevrons": icon_chevrons,
    "no_majors": icon_no_majors,
    "mask": icon_mask,
    "die": icon_die,
    "laurel": icon_laurel,
    "clipboard": icon_clipboard,
    "people": icon_people,
}


# ---------------------------------------------------------------------------
# Trophies
# ---------------------------------------------------------------------------


def outlined(fill, edge):
    """Fill and outline attributes shared by most trophy shapes."""
    return f"fill='{fill}' stroke='{edge}' stroke-width='{OUTLINE}' stroke-linejoin='round'"


def wood_base(plate_fill, plate_edge):
    """Dark wooden plinth with a large nameplate on the front."""
    return (
        f"<rect x='13' y='47' width='38' height='15.5' rx='2' {outlined(WOOD['main'], WOOD['edge'])}/>"
        f"<rect x='17.5' y='50.5' width='29' height='8.5' rx='1.5' {outlined(plate_fill, plate_edge)}/>"
    )


def handles(path, fill, edge, width):
    """Draws a handle on the left and its mirror image on the right."""
    handle = (
        f"<path d='{path}' fill='none' stroke='{edge}' stroke-width='{width + 2 * OUTLINE}' stroke-linecap='round'/>"
        f"<path d='{path}' fill='none' stroke='{fill}' stroke-width='{width}' stroke-linecap='round'/>"
    )
    return f"{handle}<g transform='translate(64 0) scale(-1 1)'>{handle}</g>"


def classic_trophy(plate, upside_down=False):
    m = METALS["gold"]
    plate_color = LEAGUE_COLORS[plate]
    body = (
        f"{handles('M16.5 12 C6.5 12 6.5 26 20.5 27', m['ring'], m['edge'], 3.4)}"
        f"<path d='M14 6 H50 V12.5 C50 25 41.5 33.5 32 34.5 C22.5 33.5 14 25 14 12.5 Z' {outlined(m['face'], m['edge'])}/>"
        f"<path d='M19.5 10 C19.5 19 22.5 25 27 28.5' fill='none' stroke='{m['light']}' stroke-width='3' stroke-linecap='round'/>"
        f"<path d='M42 9.5 C42 18 40 23 36.5 27' fill='none' stroke='{m['ring']}' stroke-width='3' stroke-linecap='round'/>"
        f"<rect x='28' y='33.5' width='8' height='8' {outlined(m['ring'], m['edge'])}/>"
        f"<path d='M23 47 L26.5 41 H37.5 L41 47 Z' {outlined(m['face'], m['edge'])}/>"
        f"{wood_base(plate_color['main'], plate_color['edge'])}"
    )
    if upside_down:
        body = f"<g transform='rotate(180 32 34.25)'>{body}</g>"
    return svg_document(body)


def world_cup_trophy(band):
    m = METALS["gold"]
    band_color = LEAGUE_COLORS[band]
    body = (
        f"<path d='M24.5 45 C25 38 16.5 33 19 21.5 C22.5 27 26.5 29.5 32 29.5 C37.5 29.5 41.5 27 45 21.5 C47.5 33 39 38 39.5 45 Z' {outlined(m['face'], m['edge'])}/>"
        f"<path d='M28 43 C29.5 37.5 23.5 33 25.5 28.5 M36 43 C34.5 37.5 40.5 33 38.5 28.5' fill='none' stroke='{m['ring']}' stroke-width='2.2' stroke-linecap='round'/>"
        f"<circle cx='32' cy='15' r='12' {outlined(m['face'], m['edge'])}/>"
        f"<ellipse cx='32' cy='15' rx='5' ry='12' fill='none' stroke='{m['icon']}' stroke-width='1.6'/>"
        f"<path d='M20 15 H44' stroke='{m['icon']}' stroke-width='1.6'/>"
        f"<path d='M24.5 9.5 A12 12 0 0 1 30 5' fill='none' stroke='{m['light']}' stroke-width='2.2' stroke-linecap='round'/>"
        f"<rect x='21' y='44' width='22' height='5' {outlined(m['ring'], m['edge'])}/>"
        f"<rect x='19' y='49' width='26' height='7' {outlined(band_color['main'], band_color['edge'])}/>"
        f"<rect x='17' y='56' width='30' height='6.5' rx='1' {outlined(m['ring'], m['edge'])}/>"
    )
    return svg_document(body)


def snowflake_path(cx, cy, radius):
    """Six-armed snowflake with a pair of branches on each arm."""
    segments = []
    for i in range(6):
        angle = math.radians(90 + i * 60)
        tip_x, tip_y = cx + radius * math.cos(angle), cy - radius * math.sin(angle)
        segments.append(f"M{cx} {cy} L{tip_x:.2f} {tip_y:.2f}")
        branch_x, branch_y = cx + radius * 0.58 * math.cos(angle), cy - radius * 0.58 * math.sin(angle)
        for offset in (-55, 55):
            branch_angle = angle + math.radians(offset)
            end_x = branch_x + radius * 0.32 * math.cos(branch_angle)
            end_y = branch_y - radius * 0.32 * math.sin(branch_angle)
            segments.append(f"M{branch_x:.2f} {branch_y:.2f} L{end_x:.2f} {end_y:.2f}")
    return " ".join(segments)


def snowflake_trophy():
    ice = METALS["ice"]
    silver = METALS["silver"]
    flake = snowflake_path(32, 20, 17.5)
    body = (
        f"<rect x='29' y='35' width='6' height='7' {outlined(silver['ring'], silver['edge'])}/>"
        f"<path d='M23 47 L26.5 41 H37.5 L41 47 Z' {outlined(silver['face'], silver['edge'])}/>"
        f"<path d='{flake}' fill='none' stroke='{ice['edge']}' stroke-width='{4 + 2 * OUTLINE}' stroke-linecap='round'/>"
        f"<path d='{flake}' fill='none' stroke='{ice['face']}' stroke-width='4' stroke-linecap='round'/>"
        f"<polygon points='{star_points(32, 20, 4.5, 4.5, 3, -90)}' fill='{ice['light']}' stroke='{ice['edge']}' stroke-width='1.2'/>"
        f"{wood_base(ice['face'], ice['edge'])}"
    )
    return svg_document(body)


def generic_trophy():
    m = METALS["gold"]
    body = (
        f"{handles('M18.5 12.5 C10 12.5 10 24 21.5 25', m['ring'], m['edge'], 3)}"
        f"<path d='M16.5 7 H47.5 L45.5 21.5 C44.5 29 38.5 33.5 32 33.5 C25.5 33.5 19.5 29 18.5 21.5 Z' {outlined(m['face'], m['edge'])}/>"
        f"<polygon points='{star_points(32, 19, 7.5, 3.3, 5)}' fill='{m['icon']}'/>"
        f"<rect x='29' y='33' width='6' height='8.5' {outlined(m['ring'], m['edge'])}/>"
        f"<path d='M24 47 L27.5 41.5 H36.5 L40 47 Z' {outlined(m['face'], m['edge'])}/>"
        f"<rect x='19.5' y='47' width='25' height='6' {outlined(m['ring'], m['edge'])}/>"
        f"<rect x='15' y='53' width='34' height='9.5' rx='1.5' {outlined(m['face'], m['edge'])}/>"
    )
    return svg_document(body)


TROPHY_STYLES = {
    "classic": classic_trophy,
    "world_cup": world_cup_trophy,
    "snowflake": snowflake_trophy,
    "generic": generic_trophy,
}


# ---------------------------------------------------------------------------
# Medals and ribbons
# ---------------------------------------------------------------------------


def medal_straps(strap, striped):
    """V-shaped neck ribbon, with a black stripe down each side for the top individual awards."""
    color = LEAGUE_COLORS[strap]
    strap_attrs = f"stroke='{color['edge']}' stroke-width='{OUTLINE}' stroke-linejoin='round'"
    left = f"<polygon points='13,1.5 27,1.5 37,23 27,25' fill='{color['back']}' {strap_attrs}/>"
    right = f"<polygon points='51,1.5 37,1.5 27,23 37,25' fill='{color['main']}' {strap_attrs}/>"
    if not striped:
        return left + right
    stripe = f"stroke='{STRAP_STRIPE_COLOR}' stroke-width='2.6'"
    return (
        f"{left}<line x1='20' y1='2.5' x2='32' y2='24' {stripe}/>"
        f"{right}<line x1='44' y1='2.5' x2='32' y2='24' {stripe}/>"
    )


def medal(icon_name, icon_options, striped, strap, placement):
    m = METALS[PLACEMENT_METALS[placement]]
    draw = ICONS[icon_name]
    # A light copy offset down and to the right makes the icon look stamped into the face.
    highlight = draw(m["light"], m["light"], **icon_options)
    main = draw(m["icon"], m["face"], **icon_options)
    body = (
        f"{medal_straps(strap, striped)}"
        f"<circle cx='32' cy='40.5' r='22' {outlined(m['ring'], m['edge'])}/>"
        f"<circle cx='32' cy='40.5' r='17.5' fill='{m['face']}'/>"
        f"<g transform='translate(0.9 0.9)'>{place_icon(highlight, 32, 40.5, 25)}</g>"
        f"{place_icon(main, 32, 40.5, 25)}"
    )
    return svg_document(body)


def ribbon(icon_name, placement):
    colors = RIBBON_COLORS[placement]
    ribbon_attrs = f"fill='{colors['main']}' stroke='{colors['edge']}' stroke-width='{OUTLINE}' stroke-linejoin='round'"
    body = (
        f"<polygon points='22,32 32,35 25,62.5 20.5,57.5 13.5,61' {ribbon_attrs}/>"
        f"<polygon points='42,32 32,35 39,62.5 43.5,57.5 50.5,61' {ribbon_attrs}/>"
        f"<polygon points='{star_points(32, 23, 22, 18.5, 16)}' {ribbon_attrs}/>"
        f"<circle cx='32' cy='23' r='16' fill='{colors['inner']}'/>"
        f"<circle cx='32' cy='23' r='13' fill='{RIBBON_BUTTON['fill']}' stroke='{RIBBON_BUTTON['edge']}' stroke-width='{OUTLINE}'/>"
        f"{place_icon(ICONS[icon_name](colors['icon'], RIBBON_BUTTON['fill']), 32, 23, 19)}"
    )
    return svg_document(body)


def write_icon(output_dir, filename, markup):
    with open(os.path.join(output_dir, f"{filename}.svg"), "w") as f:
        f.write(markup)


def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    for filename, (style, options) in TROPHIES.items():
        write_icon(output_dir, filename, TROPHY_STYLES[style](**options))
    for award, (icon_name, icon_options, striped) in MEDALS.items():
        for strap in LEAGUE_COLORS:
            for placement in PLACEMENT_METALS:
                markup = medal(icon_name, icon_options, striped, strap, placement)
                write_icon(output_dir, f"medal_{award}_{strap}_{placement}", markup)
    for award, icon_name in RIBBONS.items():
        for placement in RIBBON_COLORS:
            write_icon(output_dir, f"ribbon_{award}_{placement}", ribbon(icon_name, placement))


if __name__ == "__main__":
    main()
