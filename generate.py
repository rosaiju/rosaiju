"""Fetch GitHub stats and write dark_mode.svg / light_mode.svg.

By default the existing SVGs are updated in place: each <tspan> with a known id
gets its new value, and the matching "_dots" tspan is resized so the right edge
stays aligned. Pass --rebuild (or delete the SVGs) to regenerate them from the
layout below, e.g. after changing ascii_*.txt or the info fields.

Token: GITHUB_TOKEN or GH_TOKEN env var. Locally on Windows:
    $env:GITHUB_TOKEN = gh auth token; py generate.py
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

USER = "rosaiju"
BIRTHDAY = date(2002, 12, 15)
SVG_NS = "http://www.w3.org/2000/svg"
FILES = {"dark_mode.svg": "dark", "light_mode.svg": "light"}

# ---------------------------------------------------------------- stats

def graphql(token, query, variables=None):
    r = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if "errors" in body:
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch_stats(token):
    # Public data only, so the numbers are the same whether this runs locally
    # (your own token) or in Actions (GITHUB_TOKEN, which can't see private repos).
    user = graphql(token, """
    query($login: String!, $merged: String!, $external: String!) {
      user(login: $login) {
        contributionsCollection { contributionYears }
        repositories(ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) { totalCount }
      }
      merged: search(query: $merged, type: ISSUE, first: 0) { issueCount }
      external: search(query: $external, type: ISSUE, first: 0) { issueCount }
    }""", {
        "login": USER,
        "merged": f"is:pr is:merged author:{USER}",
        "external": f"is:pr is:merged author:{USER} -user:{USER}",
    })
    prs_merged, prs_external = user["merged"]["issueCount"], user["external"]["issueCount"]
    user = user["user"]

    # contributionsCollection spans at most one year, so ask for each year at once via aliases.
    years = user["contributionsCollection"]["contributionYears"]
    parts = [
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z") '
        "{ totalCommitContributions }"
        for y in years
    ]
    commits = 0
    if parts:
        q = 'query($login: String!) { user(login: $login) { ' + " ".join(parts) + " } }"
        per_year = graphql(token, q, {"login": USER})["user"]
        commits = sum(v["totalCommitContributions"] for v in per_year.values())

    return {
        "repos": user["repositories"]["totalCount"],
        "commits": commits,
        "prs_merged": prs_merged,
        "prs_external": prs_external,
    }


def uptime(today):
    years = today.year - BIRTHDAY.year
    months = today.month - BIRTHDAY.month
    days = today.day - BIRTHDAY.day
    if days < 0:
        months -= 1
        # borrow the length of the previous month
        first = today.replace(day=1)
        prev_month_len = (first - date.fromordinal(first.toordinal() - 1).replace(day=1)).days
        days += prev_month_len
    if months < 0:
        years -= 1
        months += 12

    def unit(n, word):
        return f"{n} {word}{'' if n == 1 else 's'}"

    return f"{unit(years, 'year')}, {unit(months, 'month')}, {unit(days, 'day')}"


# ---------------------------------------------------------------- layout

WIDTH, HEIGHT = 985, 530
# Every line gets an exact textLength, so the card has the same geometry whether the
# viewer's monospace font is Consolas (0.55em wide), Menlo or DejaVu (0.6em).
ART_FONT, ART_LINE, ART_CHAR = 10, 12, 6.0
INFO_FONT, INFO_LINE, INFO_CHAR = 14, 21, 8.4
INFO_COLS = 62  # characters per info line, dots included

THEMES = {
    "dark": dict(bg="#161b22", text="#c9d1d9", key="#ffa657", value="#a5d6ff", dots="#616e7f",
                 head="#8b949e", art="#c9d1d9"),
    "light": dict(bg="#f6f8fa", text="#24292f", key="#953800", value="#0a3069", dots="#c2cfde",
                  head="#57606a", art="#24292f"),
}


def field(key, value, id_=None, width=INFO_COLS):
    """One ". Key: ..... value" line as a list of (css class, text, id) runs."""
    lead = f". {key}:"
    n_dots = max(1, width - len(lead) - len(value) - 2)
    return [
        ("cc", ". ", None),
        ("key", key, None),
        ("cc", ":", None),
        ("cc", " " + "." * n_dots + " ", f"{id_}_dots" if id_ else None),
        ("value", value, f"{id_}_data" if id_ else None),
    ]


def pair(k1, v1, id1, k2, v2, id2):
    half = (INFO_COLS - 3) // 2
    left = field(k1, v1, id1, half)
    # the " | " separator replaces the right half's leading ". ", so give it those 2 columns back
    right = field(k2, v2, id2, INFO_COLS - 3 - half + 2)
    return left + [("cc", " | ", None)] + right[1:]


def header(title):
    return [("cc", "- ", None), ("head", title, None), ("cc", " " + "-" * (INFO_COLS - len(title) - 3), None)]


def info_lines(stats, up):
    return [
        [("text", "rohan@sainju", None), ("cc", " " + "-" * (INFO_COLS - 13), None)],
        field("OS", "Morgan State University, B.S. CS (Dec 2026)"),
        field("Uptime", up, "age"),
        field("Host", "CAPC Lab, Open LLM Evaluation research"),
        field("Kernel", "Software Engineering / Data Engineering / AI"),
        field("IDE", "VS Code"),
        [],
        field("Languages.Programming", "Python, Go, Scala, SQL, Haskell"),
        field("Languages.Web/Cloud", "React, AWS"),
        field("Languages.Real", "English, Nepali"),
        [],
        header("Contact"),
        field("Email.Personal", "rohansainju7@gmail.com"),
        field("LinkedIn", "linkedin.com/in/rohansainju"),
        [],
        header("GitHub Stats"),
        pair("Repos", f"{stats['repos']:,}", "repo", "Commits", f"{stats['commits']:,}", "commit"),
        pair("PRs.Merged", f"{stats['prs_merged']:,}", "pr", "PRs.External", f"{stats['prs_external']:,}", "ext_pr"),
    ]


def first_baseline(n_lines, line, font):
    """Baseline of the first line when n_lines are centered vertically on the card."""
    top = (HEIGHT - n_lines * line) / 2
    return top + (line - font) / 2 + font * 0.8


def render(theme, stats, up):
    c = THEMES[theme]
    art_file = f"ascii_{theme}.txt"
    with open(art_file, encoding="utf-8") as f:
        art = f.read().rstrip("\n").split("\n")

    out = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="{SVG_NS}" font-family="Consolas, Menlo, \'DejaVu Sans Mono\', \'Courier New\', monospace" '
        f'width="{WIDTH}px" height="{HEIGHT}px" font-size="{INFO_FONT}px">',
        "<style>",
        f".key {{fill: {c['key']};}} .value {{fill: {c['value']};}} .cc {{fill: {c['dots']};}} "
        f".head {{fill: {c['head']};}}",
        f"text, tspan {{white-space: pre;}}",
        "</style>",
        f'<rect width="{WIDTH}px" height="{HEIGHT}px" fill="{c["bg"]}" rx="15"/>',
    ]

    # Horizontal: equal space left of the art, between art and panel, and right of the panel.
    art_w = max(map(len, art)) * ART_CHAR
    info_w = INFO_COLS * INFO_CHAR
    gap = (WIDTH - art_w - info_w) / 3
    art_x, info_x = gap, 2 * gap + art_w

    y0 = first_baseline(len(art), ART_LINE, ART_FONT)
    out.append(f'<g fill="{c["art"]}" font-size="{ART_FONT}px">')
    for i, row in enumerate(art):
        if row:
            out.append(
                f'<text x="{art_x:.1f}" y="{y0 + i * ART_LINE:.1f}" textLength="{len(row) * ART_CHAR:.1f}" '
                f'lengthAdjust="spacing" xml:space="preserve">{escape(row)}</text>'
            )
    out.append("</g>")

    lines = info_lines(stats, up)
    y0 = first_baseline(len(lines), INFO_LINE, INFO_FONT)
    out.append(f'<g fill="{c["text"]}">')
    for i, runs in enumerate(lines):
        if not runs:
            continue
        spans = []
        for cls, text, id_ in runs:
            attrs = f' class="{cls}"' if cls != "text" else ""
            attrs += f' id="{id_}"' if id_ else ""
            spans.append(f"<tspan{attrs}>{escape(text)}</tspan>")
        width = sum(len(text) for _, text, _ in runs) * INFO_CHAR
        out.append(
            f'<text x="{info_x:.1f}" y="{y0 + i * INFO_LINE:.1f}" textLength="{width:.1f}" '
            f'lengthAdjust="spacing" xml:space="preserve">{"".join(spans)}</text>'
        )
    out.append("</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- in-place update

def update_in_place(path, values):
    ET.register_namespace("", SVG_NS)
    tree = ET.parse(path)
    by_id = {el.get("id"): el for el in tree.iter() if el.get("id")}
    for id_, new in values.items():
        data, dots = by_id.get(f"{id_}_data"), by_id.get(f"{id_}_dots")
        if data is None or dots is None:
            raise KeyError(f"{path} has no tspan {id_}_data/{id_}_dots; run with --rebuild")
        # keep (dots + value) the same total length so the line stays aligned
        n_dots = len(dots.text.strip()) + len(data.text) - len(new)
        dots.text = " " + "." * max(1, n_dots) + " "
        data.text = new
    with open(path, "wb") as f:  # binary, so Windows doesn't write CRLF
        tree.write(f, encoding="UTF-8", xml_declaration=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="regenerate SVGs from scratch")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("Set GITHUB_TOKEN (locally: $env:GITHUB_TOKEN = gh auth token)")

    stats = fetch_stats(token)
    try:
        tz = ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:  # Windows without the tzdata package
        tz = timezone.utc
    up = uptime(datetime.now(tz).date())
    print(f"uptime={up!r}", " ".join(f"{k}={v}" for k, v in stats.items()))

    values = {
        "age": up,
        "repo": f"{stats['repos']:,}",
        "commit": f"{stats['commits']:,}",
        "pr": f"{stats['prs_merged']:,}",
        "ext_pr": f"{stats['prs_external']:,}",
    }
    for path, theme in FILES.items():
        if args.rebuild or not os.path.exists(path):
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(render(theme, stats, up))
            print(f"rendered {path}")
        else:
            update_in_place(path, values)
            print(f"updated {path}")


if __name__ == "__main__":
    main()
