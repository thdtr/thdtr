"""Render the htop-style profile card (dark_mode.svg / light_mode.svg).

Stats come from the GitHub GraphQL API. Set GH_TOKEN to a token that can read
your private repos to count them too; with the default Actions token only
public repos are counted.

    GH_TOKEN=$(gh auth token) python3 generate.py
"""
import hashlib
import json
import re
import os
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

USER = "thdtr"
FIRST_COMMIT = date(2022, 4, 28)
HERE = Path(__file__).parent

PROJECTS = [  # name, language, license, short description
    ("bia", "Rust", "MIT", "code editor"),
    ("dindim", "Rust", "Apache-2.0", "expense tracker"),
    ("vixe", "JS", "custom", "ASCII platformer"),
]
METERS = [("AI", 97.0), ("OSS", 72.0), ("Rust", 64.0), ("Mate", 88.0)]

# ------------------------------------------------------------------ data


def graphql(query, variables=None):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Set GH_TOKEN (e.g. GH_TOKEN=$(gh auth token)).")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-readme-generator"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.load(resp)
    if "errors" in body:
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]


def fetch_stats(today):
    user = graphql(
        """query($login: String!, $from: DateTime!) {
          user(login: $login) {
            id
            followers { totalCount }
            pullRequests(states: MERGED) { totalCount }
            contributionsCollection(from: $from) { contributionCalendar { totalContributions } }
          }
        }""",
        {"login": USER, "from": f"{today.year}-01-01T00:00:00Z"},
    )["user"]

    repos, public, commits, cursor = 0, 0, 0, None
    while True:
        page = graphql(
            """query($login: String!, $id: ID!, $after: String) {
              user(login: $login) {
                repositories(first: 50, after: $after, ownerAffiliations: OWNER, isFork: false) {
                  pageInfo { hasNextPage endCursor }
                  nodes {
                    isPrivate
                    defaultBranchRef { target { ... on Commit { history(author: {id: $id}) { totalCount } } } }
                  }
                }
              }
            }""",
            {"login": USER, "id": user["id"], "after": cursor},
        )["user"]["repositories"]
        for repo in page["nodes"]:
            repos += 1
            public += not repo["isPrivate"]
            ref = repo["defaultBranchRef"]
            if ref and ref["target"]:
                commits += ref["target"]["history"]["totalCount"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    return dict(
        repos=repos, public=public, commits=commits,
        prs=user["pullRequests"]["totalCount"],
        followers=user["followers"]["totalCount"],
        year=user["contributionsCollection"]["contributionCalendar"]["totalContributions"],
    )


def uptime(a, b):
    months = (b.year - a.year) * 12 + b.month - a.month
    if b.day < a.day:
        months -= 1
    y0, m0 = divmod(a.month - 1 + months, 12)
    anchor = date(a.year + y0, m0 + 1, min(a.day, 28))
    return f"{months // 12}y {months % 12}m {(b - anchor).days}d"


# ------------------------------------------------------------------ render

FONT = ("ui-monospace,'SF Mono',SFMono-Regular,'Cascadia Mono',Consolas,"
        "'DejaVu Sans Mono','Liberation Mono',Menlo,monospace")
PALETTE = {  # colors taken from Ed's hair in the avatar (#CF5243)
    # dark = glowing red phosphor, light = red ink on a warm printout
    "dark": dict(bg="#140a08", fg="#ff6b57", dim="#a8483b", hi="#ff6b57", scan="#000000"),
    "light": dict(bg="#f7ede8", fg="#a63a2d", dim="#c48a7f", hi="#6b1f16", scan="#e8d4cb"),
}
W, PAD, FS, LH = 700, 28, 13.5, 19


def build_rows(s, today):
    rows = []  # each row: list of (text, css class or None); [] is a blank row
    right = [
        [("Tasks: ", "dim"), (f"{s['repos']} repos, {s['public']} public", "hi")],
        [("Commits: ", "dim"), (f"{s['commits']:,}", "hi"), ("  PRs: ", "dim"), (str(s["prs"]), "hi")],
        [("Load: ", "dim"), (f"{s['year']:,} contributions ({today.year})", "hi")],
        [("Uptime: ", "dim"), (uptime(FIRST_COMMIT, today), "hi")],
    ]
    for (label, pct), extra in zip(METERS, right):
        fill = round(pct / 100 * 30)
        rows.append([(f"{label:>4}", "hi"), ("[", None), ("|" * fill, "hi"),
                     (" " * (30 - fill) + f"{pct:5.1f}%", "dim"), ("]   ", None), *extra])
    rows.append([])
    rows.append([(f"{'PID':>5} {'USER':<6} {'LANG':<7} {'LICENSE':<11} S  COMMAND", "inv")])
    for pid, (name, lang, lic, desc) in zip([1337, 2048, 4242], PROJECTS):
        rows.append([(f"{pid:>5} ", "dim"), ("thdtr  ", None), (f"{lang:<7} ", None),
                     (f"{lic:<11} ", "dim"), ("R  ", "hi"), (f"{name:<7}", "hi"), (desc, None)])
    rows.append([(f"{31337:>5} ", "dim"), ("thdtr  ", None), (f"{'agent':<7} ", None),
                 (f"{'-':<11} ", "dim"), ("S  ", "dim"), ("claude --code-with thdtr", None)])
    rows.append([])
    rows.append([("Thiago Dutra · AI enthusiast & open-source programmer · Brazil", "dim")])
    rows.append([])
    keys = [("F1", "Help"), ("F2", "Setup"), ("F3", "Search"), ("F5", "Fork"),
            ("F6", "Clone"), ("F7", "Issue"), ("F8", "PR"), ("F10", "Quit")]
    rows.append([seg for k, v in keys for seg in ((k, "inv"), (f"{v:<7}", "invl"))])
    return rows


def render(rows, mode):
    P = PALETTE[mode]
    dark = mode == "dark"
    H = PAD * 2 + LH * len(rows)
    text, bars = [], []
    for i, segs in enumerate(rows):
        top = PAD + i * LH
        if any(c in ("inv", "invl") for _, c in segs):
            # full-width bar so it never depends on the viewer's monospace width
            bars.append(f'<rect x="0" y="{top}" width="{W}" height="{LH}" fill="{P["fg"]}"/>')
        if segs:
            body = "".join(f'<tspan class="{c}">{escape(t)}</tspan>' if c else escape(t) for t, c in segs)
            text.append(f'<text x="{PAD}" y="{top + LH - 5}">{body}</text>')
    glow = ('<filter id="glow" x="-5%" y="-10%" width="110%" height="120%"><feGaussianBlur stdDeviation="2" result="b"/>'
            '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>') if dark else ""
    nl = "\n"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" xml:space="preserve" role="img" aria-label="Thiago Dutra (thdtr): AI enthusiast and open-source programmer from Brazil">
<title>thdtr: htop</title>
<style>
text, tspan {{ white-space: pre; font-family: {FONT}; }}
text {{ font-size: {FS}px; fill: {P['fg']}; }}
.dim {{ fill: {P['dim']}; }}
.hi {{ fill: {P['hi']}; font-weight: 700; }}
.inv {{ fill: {P['bg']}; font-weight: 700; }}
.invl {{ fill: {P['bg']}; opacity: .75; }}
</style>
<defs>{glow}
<radialGradient id="vig" cx="50%" cy="50%" r="75%"><stop offset="60%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity="{0.55 if dark else 0.07}"/></radialGradient>
<pattern id="scan" width="4" height="3" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="{P['scan']}" opacity="{0.35 if dark else 0.25}"/></pattern>
<clipPath id="screen"><rect width="{W}" height="{H}" rx="18"/></clipPath></defs>
<g clip-path="url(#screen)">
<rect width="{W}" height="{H}" fill="{P['bg']}"/>
<g{' filter="url(#glow)"' if dark else ''}>
{nl.join(bars)}
{nl.join(text)}
</g>
<rect width="{W}" height="{H}" fill="url(#scan)"/>
<rect width="{W}" height="{H}" fill="url(#vig)"/>
</g>
</svg>
"""


def main():
    today = datetime.now(timezone.utc).date()
    stats = fetch_stats(today)
    print(json.dumps(stats))
    rows = build_rows(stats, today)
    digest = hashlib.sha256()
    for mode in ("dark", "light"):
        svg = render(rows, mode)
        digest.update(svg.encode())
        (HERE / f"{mode}_mode.svg").write_text(svg, encoding="utf-8")
    # Point the README at ?v=<hash> so caches never serve an old card.
    readme = HERE / "README.md"
    version = digest.hexdigest()[:10]
    text = re.sub(r"(_mode\.svg)(\?v=[0-9a-f]+)?", rf"\1?v={version}", readme.read_text(encoding="utf-8"))
    readme.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
