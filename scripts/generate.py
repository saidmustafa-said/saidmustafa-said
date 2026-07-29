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

# Quiet → loud. Also the character ramp the portrait uses, so the year strip and
# the portrait read as the same drawing.
RAMP = " :+#@"


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

# Organisations whose repositories are also mine. Without these the language card
# is a lie by omission: the biggest TypeScript codebase here lives in Conducks/,
# is public, and was invisible because `ownerAffiliations: OWNER` means "owned by
# the USER account" — an org repo is owned by the org, not by me.
#
# Listed explicitly rather than resolved from org membership, because the Actions
# token is scoped to this repository and cannot enumerate an organisation's
# members. Naming the org works with any token for public repos. Add an org here
# when one starts holding work worth counting.
EXTRA_ORGS = ["Conducks", "myCVpath", "Said-Foundation"]

ORG_QUERY = """
query($login: String!) {
  organization(login: $login) {
    repositories(
      first: 100
      isFork: false
      orderBy: { field: PUSHED_AT, direction: DESC }
    ) {
      nodes {
        name
        isArchived
        pushedAt
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""

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
    repositories(
      first: 100
      ownerAffiliations: OWNER
      isFork: false
      orderBy: { field: PUSHED_AT, direction: DESC }
    ) {
      totalCount
      nodes {
        name
        isArchived
        pushedAt
        stargazerCount
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges { size node { name } }
        }
      }
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
    """The user, with any organisation repositories folded into the repo list."""
    user = graphql(QUERY, login, token)["user"]

    for org in EXTRA_ORGS:
        try:
            data = graphql(ORG_QUERY, org, token)
        except SystemExit:
            # A missing or invisible org is not fatal: the token may simply not
            # be able to see it, and a language card is worth less than the run.
            print(f"  (org {org}: not visible to this token, skipped)")
            continue
        node = data.get("organization")
        if not node:
            continue
        repos = node["repositories"]["nodes"]
        if repos:
            print(f"  (org {org}: +{len(repos)} repos)")
        for repo in repos:
            # Namespaced so an org repo cannot collide with a user repo of the
            # same name, and so the source is obvious when debugging.
            repo["name"] = f"{org}/{repo['name']}"
            repo.setdefault("stargazerCount", 0)
        user["repositories"]["nodes"].extend(repos)

    return user


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


# Byte counts are a terrible proxy for "what does this person write", and these
# are the worst offenders. A .ipynb stores every chart and image as base64 INSIDE
# the JSON, so a single coursework notebook can outweigh an entire service: one
# repo here was 88% of the whole card. Markup and data formats are not languages
# anyone claims either.
NOT_A_LANGUAGE = {
    "Jupyter Notebook",
    "HTML",
    "CSS",
    "SCSS",
    "Roff",
    "TeX",
    "Inno Setup",
    "Batchfile",
}

# No single repository may contribute more than this share of the total. One
# vendored dependency tree or one dataset-shaped repo would otherwise decide the
# entire chart.
REPO_CAP = 0.35

# Below this share a language is not a skill, it is a stray file.
MIN_SHARE = 0.005


def languages(
    user: dict,
    top: int = 6,
    within_days: int | None = 365,
    today: date | None = None,
) -> list[tuple[str, int, int]]:
    """
    (language, bytes, repo count) across owned, non-fork, non-archived repos.

    `within_days` keeps only repositories pushed inside that window, so the card
    answers "what am I writing NOW" instead of "what have I ever written". Pass
    None for all time.

    An honest caveat, stated here because the card cannot state it: GitHub's
    language API is a snapshot of a repo's CURRENT contents — there is no history
    in it. So this is "languages of the repos I touched in that window", not
    "bytes I wrote in that window". Getting the latter means walking every commit
    diff, which is a different and far more expensive job. The card's caption is
    worded to match what is actually measured.

    Two corrections applied on top, both because raw Linguist bytes lie:
      - languages in NOT_A_LANGUAGE are dropped entirely
      - each repo is scaled down if it exceeds REPO_CAP of everything else, so
        the chart shows a body of work rather than its single largest file
    """
    repos = [r for r in user["repositories"]["nodes"] if not r["isArchived"]]

    if within_days is not None:
        cutoff = (today or date.today()) - timedelta(days=within_days)
        repos = [
            r
            for r in repos
            if r.get("pushedAt")
            and datetime.strptime(r["pushedAt"][:10], "%Y-%m-%d").date() >= cutoff
        ]

    kept = []
    for repo in repos:
        langs = {
            e["node"]["name"]: e["size"]
            for e in repo["languages"]["edges"]
            if e["node"]["name"] not in NOT_A_LANGUAGE
        }
        if langs:
            kept.append(langs)

    grand = sum(sum(l.values()) for l in kept) or 1

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for langs in kept:
        size = sum(langs.values())
        # Scale the whole repo down proportionally rather than clipping one
        # language, so the repo's internal language mix is preserved.
        scale = min(1.0, (REPO_CAP * grand) / size) if size else 1.0
        for name, value in langs.items():
            totals[name] = totals.get(name, 0) + value * scale
            counts[name] = counts.get(name, 0) + 1

    # Drop anything that rounds to 0.0% on the card. A vendored test fixture or a
    # single config file otherwise earns a row that reads as a claimed skill.
    grand_total = sum(totals.values()) or 1
    ranked = [
        (name, value)
        for name, value in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        if value / grand_total >= MIN_SHARE
    ][:top]
    return [(name, int(value), counts[name]) for name, value in ranked]


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


def lang_card(
    langs: list[tuple[str, int, int]],
    t: Theme,
    slug: str = "langs",
    heading: str = "TOP LANGUAGES",
    caption: str = "public repos · notebooks excluded",
) -> None:
    row_h, top = 26, 40
    # An empty window still gets a card, so a README that links it never 404s.
    h = top + row_h * max(len(langs), 1) + 12
    total = sum(v for _, v, _ in langs) or 1
    s = svg_open(WIDTH, h, t, f"{heading.lower()} — {caption}")
    s += text(heading, PAD, 20, 11, t.muted, spacing="3")
    # Say what the number actually measures. Private work is the majority here
    # and is invisible to this token, so an unqualified chart would mislead.
    s += text(caption, WIDTH - PAD, 20, 10, t.muted, anchor="end")

    if not langs:
        s += text("no public repositories in this window", PAD, top + 14, 12, t.muted)
        write(f"{slug}.svg", t, s)
        return

    bar_x = PAD + 116
    bar_w = WIDTH - PAD - 96 - bar_x
    for i, (name, size, n_repos) in enumerate(langs):
        y = top + i * row_h
        pct = size / total
        fill_w = bar_w * pct
        s += text(name, PAD, y + 14, 12, t.fg)
        # Repo count next to the bar: "3 repos at 40%" is a different claim from
        # "one repo at 40%", and the bar alone cannot tell them apart.
        s += text(f"{n_repos}×", WIDTH - PAD - 52, y + 14, 10, t.muted, anchor="end")
        s += f'<rect x="{bar_x}" y="{y + 5}" width="{bar_w}" height="10" rx="1" fill="{t.grid}"/>'
        # Final width on the attribute, animation *to* it — a renderer that drops
        # SMIL (or a static screenshot) shows a full bar, not an empty track.
        s += (
            f'<rect x="{bar_x}" y="{y + 5}" width="{fill_w:.1f}" height="10" rx="1" fill="{t.accent}">'
            # Every start is offset: an animation that begins at exactly 0s has
            # already applied `from` by the time a static renderer samples the
            # frame, which erases the first bar.
            f'<animate attributeName="width" from="0" to="{fill_w:.1f}" dur="0.9s" '
            f'begin="{0.15 + i * 0.08:.2f}s" fill="freeze" calcMode="spline" '
            f'keySplines="0.16 1 0.3 1" keyTimes="0;1"/>'
            f"</rect>"
        )
        s += text(f"{pct * 100:4.1f}%", WIDTH - PAD, y + 14, 11, t.muted, anchor="end")
    write(f"{slug}.svg", t, s)


def year_strip(days: list[tuple[date, int]], t: Theme) -> None:
    """One character per day, quiet to loud. textLength pins each row to the same
    width, so the grid holds together in any monospace."""
    counts = sorted(c for _, c in days if c > 0)
    qs = [counts[int(len(counts) * f)] for f in (0.33, 0.66)] if counts else [1, 2]

    def char(c: int) -> str:
        if c == 0:
            return RAMP[1]
        if c <= qs[0]:
            return RAMP[2]
        if c <= qs[1]:
            return RAMP[3]
        return RAMP[4]

    offset = (days[0][0].weekday() + 1) % 7 if days else 0
    weeks = (len(days) + offset + 6) // 7
    rows = [[" "] * weeks for _ in range(7)]
    for i, (_, c) in enumerate(days):
        idx = i + offset
        rows[idx % 7][idx // 7] = char(c)

    line_h, top = 15, 40
    h = top + 7 * line_h + 14
    s = svg_open(WIDTH, h, t, "the last year, one character per day")
    s += text("THE LAST YEAR", PAD, 20, 11, t.muted, spacing="3")
    s += text(f"{RAMP[1]} {RAMP[2]} {RAMP[3]} {RAMP[4]}  quiet to loud", WIDTH - PAD, 20, 10, t.muted, anchor="end")
    for r, row in enumerate(rows):
        s += text("".join(row), PAD, top + r * line_h, 12, t.accent, length=INNER)
    write("year.svg", t, s)


# --------------------------------------------------------------------------- #

# One card per window. The README shows the first and tucks the rest into
# <details> blocks, which is the only interactivity GitHub markdown allows — it
# strips scripts, so a real toggle is impossible. Default is the last 12 months
# because "what is he writing now" ages better than a lifetime total that only
# ever grows more stale.
WINDOWS = [
    ("langs", 365, "TOP LANGUAGES · LAST 12 MONTHS", "repos pushed since last year"),
    ("langs-3y", 1095, "TOP LANGUAGES · LAST 3 YEARS", "repos pushed in 3 years"),
    ("langs-all", None, "TOP LANGUAGES · ALL TIME", "every public repo"),
]

HEADINGS = [
    ("about", "01 — about"),
    ("stack", "02 — stack"),
    ("projects", "03 — projects"),
    ("stats", "04 — telemetry"),
    ("colophon", "05 — about this page"),
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

    # Computed once, drawn twice (light + dark).
    windows = [
        (slug, heading_text, caption, languages(user, within_days=within))
        for slug, within, heading_text, caption in WINDOWS
    ]

    print(f"{login}: {total} contributions, streak {current}/{longest}, {repos} own repos")
    for slug, _, caption, langs in windows:
        summary = ", ".join(f"{n} {v}" for n, v, _ in langs[:3]) or "empty"
        print(f"  {slug:<10} ({caption}): {summary}")

    for theme in (LIGHT, DARK):
        print(f"{theme.name}:")
        header(user.get("name") or "Said Mustafa Said", theme)
        for slug, label in HEADINGS:
            heading(slug, label, theme)
        calendar(days, total, private, theme)
        streak_card(current, longest, total, repos, theme)
        for slug, heading_text, caption, langs in windows:
            lang_card(langs, theme, slug=slug, heading=heading_text, caption=caption)
        year_strip(days, theme)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
