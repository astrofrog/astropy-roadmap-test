#!/usr/bin/env python3
"""Snapshot the roadmap from GitHub and render it.

    python roadmap.py pull PROJECT_URL roadmap.yaml [--dry-run]
    python roadmap.py render roadmap.yaml roadmap.md

The roadmap lives in GitHub. Every issue on the project board is an objective,
and its sub-issues are its key results. Each title starts with the entry's
identifier, such as ``O3: ...`` for an objective and ``R3.2: ...`` for one of
its key results; identifiers are never renumbered or reused. An issue closed as
completed marks its entry done, and one closed for any other reason removes it
from the roadmap. Open objectives are ranked by their order on the board.

``pull`` writes all of this to a YAML snapshot, printing one line per change,
and exits without writing if an identifier is missing or wrong. ``render``
writes the markdown page from the snapshot and the page wording in
``text.yaml`` next to it; the documentation build in ``docs/`` calls it. ``gh``
must be authenticated with the ``read:project`` scope for ``pull``.
"""

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path

import jinja2
from ruamel.yaml import YAML

yaml = YAML(typ="safe", pure=True)
yaml.sort_base_mapping_type_on_output = False
yaml.default_flow_style = False
yaml.width = 10**6

PROJECT_URL = re.compile(r"https://github\.com/(users|orgs)/([^/]+)/projects/(\d+)/?")
TITLE = re.compile(r"(O\d+|R\d+\.\d+):\s*(.+)", re.DOTALL)
QUERY = """
query($login: String!, $number: Int!) {
  %s(login: $login) { projectV2(number: $number) {
    items(first: 100, orderBy: {field: POSITION, direction: ASC}) {
      pageInfo { hasNextPage }
      nodes { content { ...entry ... on Issue { subIssues(first: 50) { nodes { ...entry } } } } }
    }
  } }
}
fragment entry on Issue { title url state stateReason closedAt }
"""


def fetch(project):
    """Return the issues on the project board, in board order, with their sub-issues."""
    m = PROJECT_URL.fullmatch(project)
    if not m:
        raise SystemExit(
            f"{project}: expected a URL such as https://github.com/orgs/NAME/projects/1"
        )
    owner = {"users": "user", "orgs": "organization"}[m[1]]
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={QUERY % owner}"]
        + ["-f", f"login={m[2]}", "-F", f"number={m[3]}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit(f"reading {project} failed:\n{result.stderr.strip()}")
    items = json.loads(result.stdout)["data"][owner]["projectV2"]["items"]
    if items["pageInfo"]["hasNextPage"]:
        raise SystemExit(f"{project}: more than 100 items on the board")
    # Draft issues and pull requests have no issue content and are skipped.
    return [node["content"] for node in items["nodes"] if "title" in (node["content"] or {})]


def pull(project, path, dry):
    """Write the snapshot of the roadmap on GitHub, printing one line per change."""
    errors = []

    def entry(issue, kind):
        """Return the snapshot entry for an issue, or None if it is not part of the roadmap."""
        if issue["state"] == "CLOSED" and issue["stateReason"] != "COMPLETED":
            return None
        m = TITLE.fullmatch(issue["title"].strip())
        if not m or not m[1].startswith(kind):
            errors.append(f"{issue['url']}: {issue['title']!r} should start with {kind}<number>:")
            return None
        found = {"id": m[1], "title": m[2], "url": issue["url"]}
        if issue["state"] == "CLOSED":
            found["completed"] = datetime.date.fromisoformat(issue["closedAt"][:10])
        return found

    objectives = []
    rank = 0
    for issue in fetch(project):
        if not (obj := entry(issue, "O")):
            continue
        if "completed" not in obj:
            rank += 1
            obj["rank"] = rank
        obj["key_results"] = [
            kr for sub in issue["subIssues"]["nodes"] if (kr := entry(sub, f"R{obj['id'][1:]}."))
        ]
        obj["key_results"].sort(key=lambda kr: int(kr["id"].split(".")[1]))
        objectives.append(obj)
    objectives.sort(key=lambda obj: int(obj["id"][1:]))
    ids = [e["id"] for obj in objectives for e in [obj, *obj["key_results"]]]
    errors += [
        f"{i} is used by more than one issue" for i in dict.fromkeys(ids) if ids.count(i) > 1
    ]
    if errors:
        raise SystemExit("\n".join(errors))

    old = load(path) if Path(path).exists() else {}
    if old.get("project") == project and old.get("objectives") == objectives:
        print("snapshot already up to date")
        return

    def by_id(objectives):
        return {e["id"]: e for obj in objectives for e in [obj, *obj["key_results"]]}

    before, after = by_id(old.get("objectives", [])), by_id(objectives)
    for i, e in after.items():
        b = before.get(i, {})
        if not b:
            print(f"{i} added: {e['title']}")
        elif b["title"] != e["title"]:
            print(f"{i} reworded: {e['title']}")
        if b.get("url") not in (None, e["url"]):
            print(f"{i} is now tracked in {e['url']}")
        if "completed" in e and b.get("completed") != e["completed"]:
            print(f"{i} completed on {e['completed']}")
        elif "completed" in b and "completed" not in e:
            print(f"{i} reopened")
    for i in before:
        if i not in after:
            print(f"{i} removed")

    def ranking(objectives):
        return [
            obj["id"] for obj in sorted(objectives, key=lambda o: o.get("rank", 0)) if "rank" in obj
        ]

    if (order := ranking(objectives)) != ranking(old.get("objectives", [])):
        print(f"ranking is now {', '.join(order)}")
    if not dry:
        with Path(path).open("w") as f:
            f.write("# Written by roadmap.py pull from GitHub; do not edit.\n")
            yaml.dump({"project": project, "as_of": today(), "objectives": objectives}, f)


def today():
    return datetime.datetime.now(tz=datetime.UTC).date()


def load(path):
    return yaml.load(Path(path).read_text())


def render(doc, text):
    """Return the markdown page from the snapshot and the page wording."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(Path(__file__).resolve().parent / "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    objectives = sorted(doc["objectives"], key=lambda obj: obj.get("rank", 0))
    return env.get_template("roadmap.md").render(
        doc=doc,
        text=text,
        objectives=objectives,
        n_ranked=sum("rank" in obj for obj in objectives),
    )


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)
    sp = sub.add_parser("pull")
    sp.add_argument("project", help="URL of the GitHub project board holding the objectives")
    sp.add_argument("yaml", help="the snapshot file to write")
    sp.add_argument("--dry-run", action="store_true", help="report changes without writing")
    sp = sub.add_parser("render")
    sp.add_argument("yaml", help="the snapshot file")
    sp.add_argument("output", help="markdown file to write")
    sp.add_argument("--text", help="the wording file; default: text.yaml next to the snapshot")
    args = p.parse_args()

    if args.command == "pull":
        pull(args.project, args.yaml, args.dry_run)
    else:
        text = load(args.text or Path(args.yaml).with_name("text.yaml"))
        Path(args.output).write_text(render(load(args.yaml), text))


if __name__ == "__main__":
    main()
