#!/usr/bin/env python3
"""Maintain the roadmap from its canonical YAML file.

    python roadmap.py validate roadmap.yaml
    python roadmap.py sync roadmap.yaml --repo OWNER/REPO [--dry-run] [--yes]
    python roadmap.py render roadmap.yaml roadmap.md|roadmap.html [--repo OWNER/REPO] [--check]

The YAML file defines the objectives and key results and is edited only by
pull request. Identifiers are never renumbered or reused; an entry that no
longer applies is removed, leaving a gap. Progress lives in GitHub, with one
issue per objective and one sub-issue per key result, and a closed issue is
the record that its entry is done.

``validate`` checks the structure of the YAML file. ``sync`` makes the issues
match it: missing ones are created, titles, bodies and labels are updated, and
issues for entries no longer in the file are closed. It never deletes.
``render`` writes the document, as markdown or as a web page depending on the
output extension, from the YAML and, with ``--repo``, the issue state; ``--check`` instead fails if the document on disk is not what
would be written. Both need an authenticated ``gh`` when ``--repo`` is given.
"""
import argparse
import datetime
import html
import json
import re
import subprocess

import yaml

LABELS = {"roadmap": "0e8a16", "objective": "1d76db", "key result": "5319e7"}
PRIORITIES = ("high", "medium", "low")
HOW_TO_READ = """\
## How to read this document

Each **objective** is a qualitative goal that describes a state we want the Project to reach. Each objective has up to five **key results**: concrete, measurable outcomes that, taken together, tell us whether the objective has been achieved. A key result is a single sentence that contains its own measure of success, for example a number, a published document, or a merged and released feature.

Every objective has an identifier such as `O3` and every key result has an identifier such as `R3.2`. Identifiers are stable: once assigned they are never renumbered or reused, so they can be cited in funding requests, issues, and pull requests without ambiguity. New objectives and key results take the next unused number.

The objectives and key results are defined in [`roadmap.yaml`](roadmap.yaml), and changes to their wording or priority are made by pull request to that file. This document is generated from it and from the GitHub issues that track progress: one issue per objective, linked from the line under its heading, with one sub-issue per key result, linked from the end of the key result. Status updates, links to funded work, and links to implementation pull requests belong in the issues. A key result is complete when its issue has been closed, and an objective is complete when the SPOC closes its issue, after which it is listed under completed objectives below. An entry that no longer applies is removed from the YAML file, which closes its issue; its identifier is not reused.

Each objective may carry a priority (high, medium, or low) assigned by the SPOC. Priority reflects how important the SPOC considers it that progress is made before the next revision, independent of whether anyone is currently working on it.
"""


def run(*cmd, payload=None):
    result = subprocess.run(["gh", *cmd, *(["--input", "-"] if payload else [])],
                            input=json.dumps(payload) if payload else None,
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"gh {' '.join(cmd)} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def load(path):
    """Return the parsed YAML file, or exit listing every structural problem."""
    try:
        doc = yaml.safe_load(open(path))
    except yaml.YAMLError as exc:
        raise SystemExit(f"{path}: not valid YAML (an unquoted colon in a title is the usual cause)\n{exc}")
    errors = []

    def check(entry, where, fields, text_field):
        if not isinstance(entry, dict):
            errors.append(f"{where}: expected a mapping")
            return False
        for key in entry.keys() - fields:
            errors.append(f"{where}: unknown field {key!r}")
        if not isinstance(entry.get(text_field), str) or not entry[text_field].strip():
            errors.append(f"{where}: {text_field!r} must be a non-empty string"
                          " (quote it if it contains a colon)")
        return True

    def number(entry, prefix, where, previous):
        """Return the number following prefix in the entry's id, which must exceed the previous one."""
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", str(entry.get("id")))
        if not m:
            errors.append(f"{where}: id {entry.get('id')!r} should be {prefix} followed by a number")
            return previous
        if int(m[1]) <= previous:
            errors.append(f"{where}: id {entry['id']} is out of order; new entries take the next unused number")
        return int(m[1])

    for field in ("title", "revision", "introduction"):
        if not isinstance(doc.get(field), str):
            errors.append(f"top level: {field!r} must be a string")
    objectives = doc.get("objectives")
    if not isinstance(objectives, list):
        raise SystemExit(f"{path}: 'objectives' must be a list")
    n = 0
    for i, obj in enumerate(objectives, 1):
        where = f"objective {i}"
        if not check(obj, where, {"id", "title", "priority", "key_results"}, "title"):
            continue
        n = number(obj, "O", where, n)
        if "priority" in obj and obj["priority"] not in PRIORITIES:
            errors.append(f"{where}: priority must be one of {', '.join(PRIORITIES)}")
        key_results = obj.get("key_results")
        if not isinstance(key_results, list) or not key_results:
            errors.append(f"{where}: 'key_results' must be a non-empty list")
            continue
        m = 0
        for j, kr in enumerate(key_results, 1):
            where = f"objective {i}, key result {j}"
            if check(kr, where, {"id", "text"}, "text"):
                m = number(kr, f"R{n}.", where, m)
    if errors:
        raise SystemExit("\n".join(f"{path}: {e}" for e in errors))
    return doc


def issues(repo):
    """Return {identifier: issue} for every roadmap issue in the repository."""
    found = run("issue", "list", "-R", repo, "-l", "roadmap", "-s", "all", "-L", "1000",
                "--json", "number,title,body,state,labels")
    return {m[1]: issue for issue in found if (m := re.match(r"(O\d+|R\d+\.\d+):", issue["title"]))}


def entry_url(repo, doc_path, obj):
    anchor = re.sub(r"[^\w\s-]", "", f"{obj['id']} {obj['title']}".lower()).replace(" ", "-")
    return f"https://github.com/{repo}/blob/main/{doc_path}#{anchor}"


def sync(doc, repo, doc_path, dry):
    existing = issues(repo)
    changes = []

    def ensure(entry, title, body, labels, parent=None):
        """Create or update the issue for an entry; return its number, or None in a dry run."""
        if issue := existing.pop(entry["id"], None):
            want = {"title": title, "body": body, "labels": sorted(labels)}
            have = {"title": issue["title"], "body": issue["body"].replace("\r\n", "\n").rstrip(),
                    "labels": sorted(label["name"] for label in issue["labels"])}
            if patch := {k: v for k, v in want.items() if v != have[k]}:
                changes.append(f"update  #{issue['number']} {entry['id']}: {', '.join(patch)}")
                dry or run("api", "-X", "PATCH", f"repos/{repo}/issues/{issue['number']}", payload=patch)
            return issue["number"]
        changes.append(f"create  {title}")
        if dry:
            return None
        payload = {"title": title, "body": body, "labels": labels}
        issue = run("api", "-X", "POST", f"repos/{repo}/issues", payload=payload)
        if parent:
            # The endpoint wants the database id of the sub-issue, not its number.
            run("api", "-X", "POST", f"repos/{repo}/issues/{parent}/sub_issues",
                payload={"sub_issue_id": issue["id"]})
        return issue["number"]

    for name, color in LABELS.items():
        dry or run("label", "create", name, "-R", repo, "--color", color, "--force")
    for obj in doc["objectives"]:
        url = entry_url(repo, doc_path, obj)
        body = (f"**Roadmap entry:** {url}\n\n## Key results\n\n"
                + "".join(f"- **{kr['id']}** {kr['text']}\n" for kr in obj["key_results"])
                + "\nEach key result is tracked as a sub-issue of this issue. Changes to the wording "
                "or priority of the objective are made by pull request to `roadmap.yaml`; progress "
                "updates and links to funded work and implementation PRs belong here. Close this "
                "issue when the objective has been achieved.")
        number = ensure(obj, f"{obj['id']}: {obj['title']}", body, ["roadmap", "objective"])
        for kr in obj["key_results"]:
            body = (f"Key result **{kr['id']}** of objective **{obj['id']}**"
                    f"{f' (#{number})' if number else ''}: {kr['text']}\n\n**Roadmap entry:** {url}\n\n"
                    "Close this issue when the key result has been achieved, with a comment "
                    "pointing at the evidence.")
            ensure(kr, f"{kr['id']}: {kr['text']}", body, ["roadmap", "key result"], parent=number)
    # Whatever is left was removed from the YAML, including the key results of a removed objective.
    for entry_id, issue in existing.items():
        if issue["state"] == "OPEN":
            changes.append(f"close   #{issue['number']} {entry_id}: no longer in the roadmap")
            dry or run("api", "-X", "PATCH", f"repos/{repo}/issues/{issue['number']}",
                       payload={"state": "closed", "state_reason": "not_planned"})
    print("\n".join(changes) or "nothing to do")


def collect(doc, repo):
    """Return the objectives with their issue state folded in, split into open and completed."""
    state = issues(repo) if repo else {}

    def status(entry):
        issue = state.get(entry["id"])
        return {**entry, "done": bool(issue and issue["state"] == "CLOSED"),
                "number": issue and issue["number"],
                "url": issue and f"https://github.com/{repo}/issues/{issue['number']}"}

    objectives = []
    for obj in doc["objectives"]:
        obj = status(obj)
        obj["key_results"] = [status(kr) for kr in obj["key_results"]]
        obj["n_done"] = sum(kr["done"] for kr in obj["key_results"])
        objectives.append(obj)
    return ([o for o in objectives if not o["done"]], [o for o in objectives if o["done"]])


def to_markdown(doc, repo, open_, completed):
    def objective(obj):
        notes = []
        if "priority" in obj:
            notes.append(f"Priority: {obj['priority']}")
        if obj["number"]:
            notes.append(f"Tracking issue: [#{obj['number']}]({obj['url']})")
        notes.append(f"{obj['n_done']} of {len(obj['key_results'])} key results complete")
        out = [f"### {obj['id']} {obj['title']}", "", f"*{' · '.join(notes)}*", ""]
        for kr in obj["key_results"]:
            link = f" [[#{kr['number']}]({kr['url']})]" if kr["number"] else ""
            out.append(f"- [{'x' if kr['done'] else ' '}] **{kr['id']}** {kr['text']}{link}")
        return out + [""]

    today = datetime.date.today().isoformat()
    out = [f"# {doc['title']}", "",
           "<!-- Generated by roadmap.py from roadmap.yaml; edit those instead of this file. -->", "",
           f"**Latest revision: {doc['revision']}**" + (f" · *Status from GitHub issues as of {today}*" if repo else ""), "",
           "## Introduction", "", doc["introduction"].rstrip(), "",
           HOW_TO_READ, "## Objectives", ""]
    for obj in open_:
        out += objective(obj)
    if completed:
        out += ["## Completed objectives", ""]
        for obj in completed:
            out += objective(obj)
    return "\n".join(out)


def to_html(doc, repo, open_, completed):
    def inline(text):
        """Escape text and convert the little markdown used in prose: code, links, bold."""
        text = html.escape(text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
        return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

    def prose(text):
        return "".join(f"<p>{inline(p.strip())}</p>\n" for p in text.strip().split("\n\n") if p.strip())

    def objective(obj):
        n, total = obj["n_done"], len(obj["key_results"])
        meta = []
        if "priority" in obj:
            meta.append(f'<span class="chip chip-{obj["priority"]}">{obj["priority"]} priority</span>')
        if obj["number"]:
            meta.append(f'<a class="issue" href="{obj["url"]}">Tracking issue #{obj["number"]}</a>')
        meta.append(f'<span class="progress" role="img" aria-label="{n} of {total} key results complete">'
                    f'<span class="bar"><span class="fill" style="width:{100 * n // total}%"></span></span>'
                    f'<span class="count">{n}<span class="of">/{total}</span></span></span>')
        krs = "".join(
            f'<li class="{"done" if kr["done"] else "todo"}"><span class="mark" aria-hidden="true"></span>'
            f'<span class="kr-id">{kr["id"]}</span><span class="kr-text">{inline(kr["text"])}'
            + (f' <a class="issue" href="{kr["url"]}">#{kr["number"]}</a>' if kr["number"] else "")
            + "</span></li>\n" for kr in obj["key_results"])
        return (f'<section class="objective{" complete" if obj["done"] else ""}" id="{obj["id"].lower()}">\n'
                f'<h3><span class="obj-id">{obj["id"]}</span> {inline(obj["title"])}</h3>\n'
                f'<div class="meta">{"".join(meta)}</div>\n<ul class="krs">\n{krs}</ul>\n</section>\n')

    all_objs = open_ + completed
    n_kr = sum(len(o["key_results"]) for o in all_objs)
    n_done = sum(o["n_done"] for o in all_objs)
    overview = "".join(
        f'<a class="tile{" complete" if o["done"] else ""}" href="#{o["id"].lower()}" title="{html.escape(o["title"])}">'
        f'<span class="obj-id">{o["id"]}</span><span class="bar"><span class="fill" '
        f'style="width:{100 * o["n_done"] // len(o["key_results"])}%"></span></span></a>\n' for o in all_objs)
    status = (f'<p class="status">Status from GitHub issues as of {datetime.date.today().isoformat()}. '
              f'{len(completed)} of {len(all_objs)} objectives and {n_done} of {n_kr} key results complete.</p>'
              if repo else '<p class="status">Rendered without issue state.</p>')
    how = HOW_TO_READ.split("\n", 2)[2]
    body = (f'<header>\n<p class="eyebrow">Generated from <code>roadmap.yaml</code></p>\n'
            f'<h1>{inline(doc["title"])}</h1>\n<p class="revision">Latest revision: {inline(doc["revision"])}</p>\n'
            f'{status}\n<nav class="overview" aria-label="Objectives">\n{overview}</nav>\n</header>\n'
            f'<section class="prose">\n<h2>Introduction</h2>\n{prose(doc["introduction"])}'
            f'<details>\n<summary>How to read this document</summary>\n{prose(how)}</details>\n</section>\n'
            f'<h2>Objectives</h2>\n' + "".join(objective(o) for o in open_)
            + (f'<h2>Completed objectives</h2>\n' + "".join(objective(o) for o in completed) if completed else ""))
    return HTML_PAGE.replace("{title}", html.escape(doc["title"])).replace("{body}", body)


def render(doc, repo, output):
    groups = collect(doc, repo)
    return (to_html if output.endswith(".html") else to_markdown)(doc, repo, *groups)


HTML_PAGE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap">
<style>
/* Single reading column; objectives are stacked sections with a progress bar in their meta row. */
:root {
  --bg: #f7f6f2; --surface: #fffefb; --fg: #1f2430; --muted: #646b78; --rule: #d9d6cd;
  --accent: #d1551c; --accent-soft: #f7dcc9; --done: #2f7d4f; --done-soft: #d7ecdc; --link: #1d5aa6;
  --display: "Newsreader", Georgia, "Times New Roman", serif;
  --body: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  --mono: "IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #15181f; --surface: #1d2129; --fg: #e8e6e0; --muted: #9aa1ad; --rule: #333945;
  --accent: #e8773d; --accent-soft: #4a2a19; --done: #5cb57f; --done-soft: #1e3b2a; --link: #7fb0ee; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #15181f; --surface: #1d2129; --fg: #e8e6e0; --muted: #9aa1ad; --rule: #333945;
  --accent: #e8773d; --accent-soft: #4a2a19; --done: #5cb57f; --done-soft: #1e3b2a; --link: #7fb0ee; color-scheme: dark }
* { box-sizing: border-box }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.55 var(--body); padding-block: 2.5rem 4rem; padding-inline: 16px }
main { max-width: 46rem; margin-inline: auto }
a { color: var(--link); text-underline-offset: 2px }
a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }
code { font: 0.9em var(--mono) }
h1, h2, h3 { font-family: var(--display); font-weight: 500; line-height: 1.15; text-wrap: balance; margin: 0 }
h1 { font-size: clamp(2rem, 5vw, 2.8rem) }
h2 { font-size: 1.5rem; margin-block: 3rem 1.25rem; padding-bottom: .4rem; border-bottom: 1px solid var(--rule) }
h3 { font-size: 1.3rem; font-weight: 600 }
header { display: grid; gap: .6rem }
.eyebrow { margin: 0; font-size: .78rem; letter-spacing: .06em; text-transform: uppercase; color: var(--muted) }
.revision { margin: 0; color: var(--muted) }
.status { margin: 0; font-size: .95rem }
.overview { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .75rem }
.tile { display: grid; gap: .3rem; width: 4.6rem; padding: .45rem .5rem; background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; text-decoration: none; color: inherit }
.tile:hover { border-color: var(--accent) }
.tile.complete .fill { background: var(--done) }
.obj-id, .kr-id { font: 500 .8rem/1 var(--mono); color: var(--accent); letter-spacing: .02em }
.prose p { max-width: 65ch; margin-block: 0 1rem }
details { border-left: 3px solid var(--rule); padding-left: 1rem }
summary { cursor: pointer; font-weight: 500; margin-bottom: .75rem }
.objective { padding-block: 1.5rem; border-top: 1px solid var(--rule) }
.objective:first-of-type { border-top: 0 }
.objective h3 .obj-id { font-size: .9rem; vertical-align: .25em; margin-right: .3rem }
.objective.complete .obj-id, .objective.complete .fill, .tile.complete .obj-id { color: var(--done); background: var(--done) }
.objective.complete .obj-id, .tile.complete .obj-id { background: none }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem 1.25rem; margin-block: .6rem 1rem; font-size: .9rem; color: var(--muted) }
.chip { padding: .1rem .55rem; border-radius: 999px; font-size: .78rem; font-weight: 500; text-transform: capitalize; background: var(--surface); border: 1px solid var(--rule) }
.chip-high { color: var(--accent); border-color: var(--accent) }
.progress { display: inline-flex; align-items: center; gap: .5rem; min-width: 10rem; flex: 1 }
.bar { flex: 1; height: 6px; border-radius: 3px; background: var(--rule); overflow: hidden }
.fill { display: block; height: 100%; background: var(--accent); transition: width .4s }
.count { font: 500 .9rem var(--mono); color: var(--fg); font-variant-numeric: tabular-nums }
.of { color: var(--muted) }
.krs { list-style: none; margin: 0; padding: 0; display: grid; gap: .55rem }
.krs li { display: grid; grid-template-columns: 1.1rem auto 1fr; gap: .6rem; align-items: baseline; min-width: 0 }
.mark { width: .95rem; height: .95rem; border-radius: 50%; border: 1.5px solid var(--muted); align-self: start; margin-top: .3rem; position: relative }
.done .mark { background: var(--done); border-color: var(--done) }
.done .mark::after { content: ""; position: absolute; left: 4px; top: 1px; width: 4px; height: 8px; border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg) }
.done .kr-text { color: var(--muted) }
.kr-text { min-width: 0 }
.kr-text .issue { font-size: .85em; white-space: nowrap }
@media (prefers-reduced-motion: reduce) { .fill { transition: none } }
</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("validate", "sync", "render"):
        sp = sub.add_parser(name)
        sp.add_argument("yaml", help="the canonical roadmap YAML file")
        if name != "validate":
            sp.add_argument("--repo", required=name == "sync", help="GitHub repository as owner/name")
    sub.choices["sync"].add_argument("--doc", default="roadmap.md",
                                     help="path of the rendered document in the repository, for links in issue bodies")
    sub.choices["sync"].add_argument("--dry-run", action="store_true", help="report changes without making them")
    sub.choices["sync"].add_argument("--yes", action="store_true", help="do not ask for confirmation")
    sub.choices["render"].add_argument("output", help="file to write; .html gives a web page, anything else markdown")
    sub.choices["render"].add_argument("--check", action="store_true",
                                       help="exit with an error if the output file is not up to date")
    args = p.parse_args()

    doc = load(args.yaml)
    if args.command == "validate":
        n = sum(len(o["key_results"]) for o in doc["objectives"])
        print(f"{args.yaml}: {len(doc['objectives'])} objectives, {n} key results, no problems found")
    elif args.command == "sync":
        if not (args.dry_run or args.yes):
            answer = input(f"Create and update roadmap issues in {args.repo}? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                raise SystemExit("aborted")
        sync(doc, args.repo, args.doc, args.dry_run)
    else:
        text = render(doc, args.repo, args.output)
        if args.check:
            if open(args.output).read() != text:
                raise SystemExit(f"{args.output} is out of date; run: python roadmap.py render {args.yaml} {args.output}")
            print(f"{args.output} is up to date")
        else:
            open(args.output, "w").write(text)


if __name__ == "__main__":
    main()
