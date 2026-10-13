#!/usr/bin/env python3
"""Snapshot the roadmap from GitHub and render it.

    python roadmap.py pull PROJECT_URL roadmap.yaml
    python roadmap.py render roadmap.yaml roadmap.md

The roadmap lives in GitHub. Every issue on the project board is an objective,
and its sub-issues are its key results. Each title starts with the entry's
identifier, such as ``O3: ...`` for an objective and ``R3.2: ...`` for one of
its key results; identifiers are never renumbered or reused. An issue closed as
completed marks its entry done, and one closed for any other reason removes it
from the roadmap. Open objectives are ranked by their order on the board.

``pull`` writes all of this to a YAML snapshot, leaving the file alone if
nothing has changed, and exits without writing if an identifier is missing or
wrong. ``render`` writes the markdown page from the snapshot and the page
wording in ``text.yaml`` next to it; the documentation build in ``docs/`` calls
it. ``gh`` must be authenticated with the ``read:project`` scope for ``pull``.
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

PROJECT_URL = re.compile(
    r"https://github\.com/(?P<owner>users|orgs)/(?P<login>[^/]+)/projects/(?P<number>\d+)/?"
)
TITLE = re.compile(r"(?P<id>O\d+|R\d+\.\d+):\s*(?P<title>.+)")

# Fetches the issues on a project board in board order, each with its sub-issues.
# The owner field, user or organization, is filled in before the query is sent.
QUERY = """
query($login: String!, $number: Int!) {
  %s(login: $login) {
    projectV2(number: $number) {
      items(first: 100, orderBy: {field: POSITION, direction: ASC}) {
        pageInfo { hasNextPage }
        nodes {
          content {
            ...entry
            ... on Issue { subIssues(first: 50) { nodes { ...entry } } }
          }
        }
      }
    }
  }
}
fragment entry on Issue { title url state stateReason closedAt }
"""


def fetch_board(project):
    """Return the issues on the project board, in board order, with their sub-issues."""
    match = PROJECT_URL.fullmatch(project)
    if match is None:
        raise SystemExit(
            f"{project}: expected a URL such as https://github.com/orgs/NAME/projects/1"
        )
    owner = "user" if match["owner"] == "users" else "organization"
    command = [
        "gh", "api", "graphql",
        "-f", f"query={QUERY % owner}",
        "-f", f"login={match['login']}",
        "-F", f"number={match['number']}",
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"reading {project} failed:\n{result.stderr.strip()}")

    items = json.loads(result.stdout)["data"][owner]["projectV2"]["items"]
    if items["pageInfo"]["hasNextPage"]:
        raise SystemExit(f"{project}: more than 100 items on the board")
    issues = []
    for item in items["nodes"]:
        # Draft issues and pull requests come back empty and are skipped.
        if item["content"]:
            issues.append(item["content"])
    return issues


def make_entry(issue, prefix, errors):
    """Return the snapshot entry for an issue, or None if it is not part of the roadmap.

    The identifier in the title must start with ``prefix``: ``O`` for an
    objective, or for example ``R3.`` for a key result of O3. A problem with
    the title is added to ``errors``.
    """
    closed = issue["state"] == "CLOSED"
    if closed and issue["stateReason"] != "COMPLETED":
        return None
    match = TITLE.fullmatch(issue["title"].strip())
    if match is None or not match["id"].startswith(prefix):
        errors.append(f"{issue['url']}: {issue['title']!r} should start with {prefix}<number>:")
        return None
    entry = {"id": match["id"], "title": match["title"], "url": issue["url"]}
    if closed:
        entry["completed"] = datetime.date.fromisoformat(issue["closedAt"][:10])
    return entry


def id_number(entry):
    """Return the last number in an entry's identifier: 3 for O3, 2 for R3.2."""
    return int(re.findall(r"\d+", entry["id"])[-1])


def make_objectives(issues):
    """Return the snapshot's objectives, or exit listing every problem with the issues."""
    errors = []
    objectives = []
    rank = 0
    for issue in issues:
        objective = make_entry(issue, "O", errors)
        if objective is None:
            continue
        if "completed" not in objective:
            rank += 1
            objective["rank"] = rank
        key_results = []
        for sub_issue in issue["subIssues"]["nodes"]:
            key_result = make_entry(sub_issue, f"R{id_number(objective)}.", errors)
            if key_result is not None:
                key_results.append(key_result)
        objective["key_results"] = sorted(key_results, key=id_number)
        objectives.append(objective)

    seen = set()
    for objective in objectives:
        for entry in [objective, *objective["key_results"]]:
            if entry["id"] in seen:
                errors.append(f"{entry['id']} is used by more than one issue")
            seen.add(entry["id"])
    if errors:
        raise SystemExit("\n".join(errors))
    return sorted(objectives, key=id_number)


def pull(project, path):
    """Write the snapshot of the roadmap on GitHub, unless it has not changed."""
    objectives = make_objectives(fetch_board(project))
    if Path(path).exists():
        old = load(path)
        if old["project"] == project and old["objectives"] == objectives:
            return
    snapshot = {"project": project, "as_of": datetime.date.today(), "objectives": objectives}
    with Path(path).open("w") as f:
        f.write("# Written by roadmap.py pull from GitHub; do not edit.\n")
        yaml.dump(snapshot, f)


def load(path):
    return yaml.load(Path(path).read_text())


def render(snapshot, text):
    """Return the markdown page from the snapshot and the page wording."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(Path(__file__).resolve().parent / "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    # Completed objectives have no rank; the template lists them separately.
    objectives = sorted(snapshot["objectives"], key=lambda objective: objective.get("rank", 0))
    n_ranked = sum("rank" in objective for objective in objectives)
    template = env.get_template("roadmap.md")
    return template.render(doc=snapshot, text=text, objectives=objectives, n_ranked=n_ranked)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    pull_parser = commands.add_parser("pull")
    pull_parser.add_argument("project", help="URL of the GitHub project board")
    pull_parser.add_argument("yaml", help="the snapshot file to write")
    render_parser = commands.add_parser("render")
    render_parser.add_argument("yaml", help="the snapshot file")
    render_parser.add_argument("output", help="markdown file to write")
    render_parser.add_argument(
        "--text", help="wording file; default: text.yaml next to the snapshot"
    )
    args = parser.parse_args()

    if args.command == "pull":
        pull(args.project, args.yaml)
    else:
        text = load(args.text or Path(args.yaml).with_name("text.yaml"))
        Path(args.output).write_text(render(load(args.yaml), text))


if __name__ == "__main__":
    main()
