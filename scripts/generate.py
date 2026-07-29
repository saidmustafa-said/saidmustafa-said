#!/usr/bin/env python3
"""
Draw every graphic on the profile, from the GitHub GraphQL API, into committed SVG.

Why generate instead of embedding someone else's badge service: a third-party
image host can rate-limit, change, or go dark, and every one of them is a request
that has to succeed for the page to look finished. Nothing here loads from
anywhere — the SVGs are files in this repo.

Why SVG and not markdown tables: GitHub strips <script> and CSS from READMEs, so
an image is the only way to put this page's own type and colour on it. Animation
is SMIL, inside the SVG, for the same reason.

Two copies of every graphic are written — assets/ and assets/dark/ — and the
README picks between them with <picture media="(prefers-color-scheme: dark)">.
That is more reliable than a media query inside a single SVG, which GitHub's
image proxy does not consistently honour.

Stdlib only. Run: GITHUB_TOKEN=... GH_LOGIN=saidmustafa-said python3 scripts/generate.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"
ROOT = Path(__file__).resolve().parent.parent
WIDTH = 620
# Nothing is drawn inside this margin. Text anchored at the exact edge gets
# clipped by the viewport in most renderers.
PAD = 14
INNER = WIDTH - 2 * PAD


# --------------------------------------------------------------------------- #
# themes
# --------------------------------------------------------------------------- #

class Theme:
    def __init__(self, name, bg, fg, muted, accent, grid, levels):
        self.name = name
        self.bg = bg
        self.fg = fg
        self.muted = muted
        self.accent = accent
        self.grid = grid
        self.levels = levels  # 5 steps, empty → densest


# The site's palette, so the profile and saidmustafasaid.com read as one brand.
DARK = Theme(
    name="dark",
    bg="#0c1112",
    fg="#f2f5f4",
    muted="#7f8d8c",
    accent="#00d3cd",
    grid="#1a2524",
    levels=["#161f20", "#0d4b4a", "#008f8b", "#00b3ae", "#00d3cd"],
)

# Teal is darkened on white: #00d3cd on #fff is ~1.6:1 and unreadable.
LIGHT = Theme(
    name="light",
    bg="#ffffff",
    fg="#0c1112",
    muted="#6b7a79",
    accent="#00807c",
    grid="#e6ecec",
    levels=["#eef2f2", "#b8e4e2", "#6cc9c5", "#22a7a2", "#00807c"],
)


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #

# Only what the remaining cards need: the contribution calendar and a repo
# count. Per-repository languages are gone with the language chart — with ~96%
# of the work private, counting public bytes measured a rounding error.
QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    login
    contributionsCollection {
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(first: 1, ownerAffiliations: OWNER, isFork: false) {
      totalCount
    }
  }
}
"""


def graphql(query: str, login: str, token: str) -> dict:
    body = json.dumps({"query": query, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{login}-profile-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    # GraphQL answers 200 with an errors array, so this has to be checked by hand.
    if "errors" in payload:
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]


def fetch(login: str, token: str) -> dict:
    return graphql(QUERY, login, token)["user"]


def days_of(user: dict) -> list[tuple[date, int]]:
    """Flatten the calendar to (date, count), oldest first."""
    out = []
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    for w in weeks:
        for d in w["contributionDays"]:
            out.append((datetime.strptime(d["date"], "%Y-%m-%d").date(), d["contributionCount"]))
    return out


def streaks(days: list[tuple[date, int]]) -> tuple[int, int]:
    """(current, longest).

    Today is excluded from breaking the current streak: the day is not over, and
    a run should not read as broken at 00:05 UTC because nothing is pushed yet.
    """
    longest = run = 0
    for _, c in days:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)

    today = days[-1][0] if days else None
    current = 0
    for d, c in reversed(days):
        if c > 0:
            current += 1
        elif d == today:
            continue  # today is still open
        else:
            break
    return current, longest


# --------------------------------------------------------------------------- #
# svg helpers
# --------------------------------------------------------------------------- #

# No font file is shipped. Every text node is placed at an explicit x, and any
# run that must line up uses textLength, so a viewer whose default monospace is
# a different width still gets the intended layout instead of a squeezed one.
FONT = "ui-monospace, 'JetBrains Mono', 'SFMono-Regular', Menlo, Consolas, monospace"


def svg_open(w: int, h: int, t: Theme, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}">'
        f'<rect width="{w}" height="{h}" fill="{t.bg}"/>'
    )


def text(s: str, x: float, y: float, size: float, fill: str,
         weight: str = "400", anchor: str = "start",
         spacing: str = "0", length: float | None = None) -> str:
    attrs = (
        f'x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" letter-spacing="{spacing}" '
        f'text-anchor="{anchor}" xml:space="preserve"'
    )
    if length is not None:
        attrs += f' textLength="{length:.1f}" lengthAdjust="spacing"'
    return f"<text {attrs}>{escape(s)}</text>"


def write(rel: str, t: Theme, body: str) -> None:
    out = ROOT / ("assets/dark" if t.name == "dark" else "assets") / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body + "</svg>\n", encoding="utf-8")
    print(f"  {out.relative_to(ROOT)}")


# --------------------------------------------------------------------------- #
# graphics
# --------------------------------------------------------------------------- #

def header(name: str, t: Theme) -> None:
    """The top wordmark. Drawn rather than typed so the profile opens in the same
    type and colour as saidmustafasaid.com — GitHub gives markdown neither."""
    parts = name.upper().split()
    line_h, first = 34, 42
    # Canvas sized from the name, not hard-coded: a fixed height put the role
    # line on top of the last name line.
    h = first + line_h * (len(parts) - 1) + 52
    s = svg_open(WIDTH, h, t, f"{name} — AI/ML and Cloud Engineer, Berlin")
    for i, part in enumerate(parts):
        s += text(part, PAD, first + i * line_h, 30,
                  t.accent if i == 1 else t.fg, weight="600", spacing="1")
    s += text("AI/ML & CLOUD ENGINEER   ·   BERLIN, GERMANY", PAD, h - 22, 11,
              t.muted, spacing="3")
    s += f'<rect x="{PAD}" y="{h - 10}" width="{INNER}" height="1" fill="{t.grid}"/>'
    write("header.svg", t, s)


def heading(slug: str, label: str, t: Theme) -> None:
    """A section rule: number, label, hairline. The only way to get this page's
    own type onto a heading, since GitHub strips CSS from markdown."""
    h = 46
    s = svg_open(WIDTH, h, t, label)
    s += text(label.upper(), PAD, 20, 12, t.accent, weight="600", spacing="4")
    s += f'<rect x="{PAD}" y="32" width="{INNER}" height="1" fill="{t.grid}"/>'
    # Short accent segment that draws itself in, once, on load. The final width
    # is the attribute value and the animation runs *to* it, so a renderer that
    # ignores SMIL still shows the finished state rather than nothing.
    s += (
        f'<rect x="{PAD}" y="32" width="140" height="1" fill="{t.accent}">'
        f'<animate attributeName="width" from="0" to="140" dur="0.9s" begin="0.15s" '
        f'fill="freeze" calcMode="spline" keySplines="0.16 1 0.3 1" keyTimes="0;1"/>'
        f"</rect>"
    )
    write(f"hd-{slug}.svg", t, s)


def calendar(days: list[tuple[date, int]], total: int, private: int, t: Theme) -> None:
    """The year as a grid. Rectangles, not characters, so it cannot be broken by
    the viewer's font."""
    pad_top = 54
    offset0 = (days[0][0].weekday() + 1) % 7 if days else 0
    weeks = (len(days) + offset0 + 6) // 7
    # Size the cell to the column count instead of hard-coding it: 53 weeks at a
    # fixed 9+3 overflows the 620px canvas and the last month falls off the edge.
    step = INNER / weeks
    gap = max(1.0, min(3.0, step * 0.25))
    cell = step - gap
    grid_w = weeks * step - gap
    h = pad_top + round(7 * step) + 28
    x0 = PAD + (INNER - grid_w) / 2

    s = svg_open(WIDTH, h, t, f"{total} contributions in the last year")
    s += text(f"{total:,}", PAD, 26, 26, t.fg, weight="600")
    s += text("contributions in the last year", PAD, 44, 11, t.muted, spacing="2")
    if private:
        s += text(f"{private:,} private", WIDTH - PAD, 26, 11, t.muted, anchor="end", spacing="2")

    # Level thresholds from this user's own distribution, not a fixed 1/3/6/9 —
    # a fixed scale makes a quiet year look empty and a loud one look saturated.
    counts = sorted(c for _, c in days if c > 0)
    if counts:
        qs = [counts[int(len(counts) * f)] for f in (0.25, 0.5, 0.75)]
    else:
        qs = [1, 2, 3]

    def level(c: int) -> int:
        if c == 0:
            return 0
        if c <= qs[0]:
            return 1
        if c <= qs[1]:
            return 2
        if c <= qs[2]:
            return 3
        return 4

    # Week 0 may be partial: the calendar always starts on a Sunday, so offset
    # the first column by the weekday of the first day.
    for i, (d, c) in enumerate(days):
        idx = i + offset0
        col, row = idx // 7, idx % 7
        x = x0 + col * step
        y = pad_top + row * step
        lv = level(c)
        s += (
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{cell:.2f}" height="{cell:.2f}" rx="1" '
            f'fill="{t.levels[lv]}">'
            # Stagger left-to-right so the year appears to fill in.
            f'<animate attributeName="opacity" from="0" to="1" dur="0.4s" '
            f'begin="{0.15 + col * 0.012:.3f}s" fill="freeze"/>'
            f"</rect>"
        )

    legend_y = pad_top + 7 * step + 12
    s += text("less", x0, legend_y + 9, 10, t.muted)
    for i, col in enumerate(t.levels):
        s += (
            f'<rect x="{x0 + 34 + i * step:.2f}" y="{legend_y:.2f}" '
            f'width="{cell:.2f}" height="{cell:.2f}" rx="1" fill="{col}"/>'
        )
    s += text("more", x0 + 34 + 5 * step + 6, legend_y + 9, 10, t.muted)
    write("stats.svg", t, s)


def streak_card(current: int, longest: int, total: int, repos: int, t: Theme) -> None:
    h = 96
    s = svg_open(WIDTH, h, t, f"current streak {current} days, longest {longest} days")
    cells = [
        (str(current), "current streak"),
        (str(longest), "longest streak"),
        (f"{total:,}", "contributions"),
        (str(repos), "own repos"),
    ]
    step = INNER / len(cells)
    for i, (value, label) in enumerate(cells):
        cx = PAD + step * i + step / 2
        s += text(value, cx, 46, 28, t.accent, weight="600", anchor="middle")
        s += text(label.upper(), cx, 68, 10, t.muted, anchor="middle", spacing="2")
        if i:
            x = PAD + step * i
            s += f'<rect x="{x:.1f}" y="24" width="1" height="48" fill="{t.grid}"/>'
    write("streak.svg", t, s)


PROFILE_URL = "https://saidmustafasaid.com/profile.json"

# Tier → weight. Only the top tiers get the accent; the weak fields are drawn
# muted so the chart reads as a shape rather than a scoreboard.
RANK_TIERS = ["ACADEMIC", "JUNIOR", "ASSOCIATE", "PROFESSIONAL", "SENIOR", "STAFF", "ARCHITECT", "PRINCIPAL"]


def fetch_profile(url: str = PROFILE_URL) -> dict | None:
    """
    Figures, roles, impact, field scores and recent writing, from my own site.

    Returns None on any failure. A missing card is survivable, a failed daily run
    is not, so the previously committed SVGs stay in place and the README never
    shows a broken image because a self-hosted box was rebooting.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "profile-generator"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except Exception as e:  # network, DNS, TLS, JSON, all equally non-fatal
        print(f"  (profile.json unavailable: {e}, keeping the committed cards)")
        return None
    if not data.get("fields"):
        print("  (profile.json has no fields, keeping the committed cards)")
        return None
    return data


def figures_card(profile: dict, t: Theme) -> None:
    """
    The numbers that belong in the first screen.

    A profile that opens with prose gives a reader nothing to hold. These are all
    counted from real records, never asserted: projects from the log files,
    certifications from the CV, fields from the scoring engine.
    """
    figures = profile.get("figures", [])
    if not figures:
        return
    h = 92
    s = svg_open(WIDTH, h, t, "key figures")
    step = INNER / len(figures)
    for i, f in enumerate(figures):
        cx = PAD + step * i + step / 2
        s += text(str(f["value"]), cx, 44, 26, t.accent, weight="600", anchor="middle")
        # Two short lines beat one long one at this width.
        words = str(f["label"]).split()
        half = (len(words) + 1) // 2
        s += text(" ".join(words[:half]).upper(), cx, 64, 9, t.muted, anchor="middle", spacing="1")
        s += text(" ".join(words[half:]).upper(), cx, 76, 9, t.muted, anchor="middle", spacing="1")
        if i:
            s += f'<rect x="{PAD + step * i:.1f}" y="22" width="1" height="56" fill="{t.grid}"/>'
    write("figures.svg", t, s)


def track_card(profile: dict, t: Theme) -> None:
    """Roles with dates, then what the work actually changed."""
    roles = profile.get("roles", [])
    impact = profile.get("impact", [])
    if not roles:
        return

    row_h, top = 30, 34
    h = top + row_h * len(roles) + (58 if impact else 14)
    s = svg_open(WIDTH, h, t, "roles and measured impact")
    s += text("TRACK RECORD", PAD, 18, 11, t.muted, spacing="3")

    for i, r in enumerate(roles):
        y = top + i * row_h
        span = f"{r['from']} → {r['to']}"
        s += text(span, PAD, y + 12, 11, t.accent if r["to"] == "now" else t.muted)
        s += text(str(r["title"]), PAD + 108, y + 12, 12, t.fg)
        s += text(str(r["company"]), PAD + 108, y + 25, 10, t.muted)

    if impact:
        base = top + row_h * len(roles) + 12
        s += f'<rect x="{PAD}" y="{base}" width="{INNER}" height="1" fill="{t.grid}"/>'
        step = INNER / len(impact)
        for i, m in enumerate(impact):
            cx = PAD + step * i + step / 2
            s += text(str(m["value"]), cx, base + 26, 18, t.accent, weight="600", anchor="middle")
            s += text(str(m["label"]).upper(), cx, base + 40, 9, t.muted, anchor="middle", spacing="1")
    write("track.svg", t, s)


def update_readme_writing(profile: dict) -> None:
    """
    Write the recent posts into the README as real markdown links.

    Nothing inside an SVG is clickable on GitHub: the README image is served
    through a proxy that strips interactivity, so a drawn list of posts offers no
    way to open any of them. This is markdown for that reason, and it is markdown
    INSTEAD of a card rather than as well as one, because a picture of the titles
    above the same titles as text is the page saying everything twice.
    """
    posts = profile.get("writing", [])
    if not posts:
        return

    readme = ROOT / "README.md"
    body = readme.read_text(encoding="utf-8")
    start, end = "<!-- writing:start -->", "<!-- writing:end -->"
    if start not in body or end not in body:
        print("  (README has no writing markers, skipping the link list)")
        return

    lines = [
        f"- [{p['title']}]({p['url']}) &nbsp;<sub>{str(p.get('date', ''))[:10]}</sub>"
        for p in posts
    ]
    lines += ["", "[All writing →](https://saidmustafasaid.com/blog)"]
    block = f"{start}\n\n" + "\n".join(lines) + f"\n\n{end}"

    head, _, rest = body.partition(start)
    _, _, tail = rest.partition(end)
    readme.write_text(head + block + tail, encoding="utf-8")
    print(f"  README: {len(posts)} writing links")


def field_card(rank: dict, t: Theme) -> None:
    """
    The 12 fields, strongest to weakest.

    This is the centrepiece, and the weak rows are the reason it works: a
    self-assessment that shows MOBILE at zero is one you can believe about the
    fields it scores high. Scores come from my own engine over real project
    history, not from counting bytes on GitHub — which is the only honest option
    when almost all the work is in private repositories.
    """
    fields = rank["fields"]
    row_h, top = 24, 58
    h = top + row_h * len(fields) + 22

    # Wide enough for the longest real label ("PLATFORM & DEVELOPER TOOLING",
    # 28 chars at ~6.6px per char in this mono) — truncating a field name to fit
    # a round number would hide what the row is about.
    label_w = 200
    bar_x = PAD + label_w
    bar_w = WIDTH - PAD - 112 - bar_x

    s = svg_open(WIDTH, h, t, "engineering field map, twelve fields scored")
    s += text("FIELD MAP", PAD, 20, 11, t.muted, spacing="3")
    s += text(f"rank: {rank.get('rank', '').upper()}", WIDTH - PAD, 20, 10, t.accent, anchor="end", spacing="2")
    s += text(
        "scored from real project history · saidmustafasaid.com",
        PAD, 38, 10, t.muted,
    )

    for i, f in enumerate(fields):
        y = top + i * row_h
        # `value` is 0..1 from the engine; the card shows it out of 100.
        pct = max(0.0, min(1.0, float(f["value"])))
        fill_w = bar_w * pct
        strong = f.get("rank", "") in ("PROFESSIONAL", "SENIOR", "STAFF", "ARCHITECT", "PRINCIPAL")
        colour = t.accent if strong else t.levels[2]

        label = f["label"]
        if len(label) > 29:
            label = label[:28] + "…"
        s += text(label, PAD, y + 13, 11, t.fg if strong else t.muted)

        s += f'<rect x="{bar_x}" y="{y + 4}" width="{bar_w}" height="10" rx="1" fill="{t.grid}"/>'
        if fill_w > 0:
            s += (
                f'<rect x="{bar_x}" y="{y + 4}" width="{fill_w:.1f}" height="10" rx="1" fill="{colour}">'
                f'<animate attributeName="width" from="0" to="{fill_w:.1f}" dur="0.9s" '
                f'begin="{0.15 + i * 0.05:.2f}s" fill="freeze" calcMode="spline" '
                f'keySplines="0.16 1 0.3 1" keyTimes="0;1"/>'
                f"</rect>"
            )

        s += text(f"{pct * 100:4.1f}", bar_x + bar_w + 30, y + 13, 11, t.fg if strong else t.muted, anchor="end")
        s += text(f.get("rank", ""), WIDTH - PAD, y + 13, 9, t.muted, anchor="end", spacing="1")

    computed = (rank.get("computed") or "")[:10]
    if computed:
        s += text(f"recomputed {computed}", PAD, h - 8, 9, t.muted)
    write("fields.svg", t, s)


# --------------------------------------------------------------------------- #

HEADINGS = [
    ("now", "01 · now"),
    ("shipped", "02 · shipped"),
    ("fields", "03 · field map"),
    ("track", "04 · track record"),
    ("writing", "05 · writing"),
    ("stats", "06 · telemetry"),
]


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GH_LOGIN", "saidmustafa-said")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1

    try:
        user = fetch(login, token)
    except urllib.error.HTTPError as e:
        print(f"GitHub API {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        return 1

    cc = user["contributionsCollection"]
    total = cc["contributionCalendar"]["totalContributions"]
    private = cc["restrictedContributionsCount"]
    days = days_of(user)
    # A year is 365 days; the calendar returns whole weeks, which overshoots.
    cutoff = days[-1][0] - timedelta(days=364) if days else None
    days = [d for d in days if d[0] >= cutoff] if cutoff else days

    current, longest = streaks(days)
    repos = user["repositories"]["totalCount"]

    # Everything that is about the work rather than about GitHub comes from my
    # own site. Language-by-bytes was dropped: with almost all the work in
    # private repositories it measured a rounding error and called it a person.
    profile = fetch_profile()

    print(f"{login}: {total} contributions ({private} private), streak {current}/{longest}")
    if profile:
        print(f"  figures: {len(profile.get('figures', []))}, roles: {len(profile.get('roles', []))}, "
              f"fields: {len(profile['fields'])}, writing: {len(profile.get('writing', []))}")
        update_readme_writing(profile)

    for theme in (LIGHT, DARK):
        print(f"{theme.name}:")
        header(user.get("name") or "Said Mustafa Said", theme)
        for slug, label in HEADINGS:
            heading(slug, label, theme)
        if profile:
            figures_card(profile, theme)
            field_card(profile, theme)
            track_card(profile, theme)
        calendar(days, total, private, theme)
        streak_card(current, longest, total, repos, theme)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
