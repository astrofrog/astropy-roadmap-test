#!/usr/bin/env python3
"""Snapshot the roadmap from GitHub and render it.

    python roadmap.py pull OWNER/REPO PROJECT_URL roadmap.yaml
    python roadmap.py render roadmap.yaml roadmap.md

The roadmap lives in the issues of a GitHub repository. Every issue with the
``objective`` label is an objective, titled with its identifier such as
``O3: ...``, and its sub-issues, titled ``R3.1: ...``, ``R3.2: ...`` and so on,
are its key results.
Identifiers are never renumbered or reused. An issue closed as completed marks
its entry done, and one closed for any other reason removes it from the
roadmap. Open objectives on the project board are ranked by their order there;
open objectives not on the board are unranked.

``pull`` writes all of this to a YAML snapshot, leaving the file alone if
nothing has changed. It exits without writing if the issues are inconsistent,
and prints a warning for anything that is allowed but probably a mistake.
``render`` writes the markdown page from the snapshot and the page wording in
``text.yaml`` next to it; the documentation build in ``docs/`` calls it. ``gh``
must be authenticated with the ``read:project`` scope for ``pull``.
"""

import argparse
import datetime
import json
import re
import subprocess
from collections import defaultdict
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
IDENTIFIER = re.compile(r"(?P<prefix>O|R\d+\.)(?P<number>\d+)")
TITLE = re.compile(rf"(?P<id>{IDENTIFIER.pattern}):\s*(?P<title>.+)")
MAX_KEY_RESULTS = 5
OBJECTIVE_LABEL = "objective"

# Every issue in a repository, open and closed, each with its labels and sub-issues.
ISSUES_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        ...entry
        labels(first: 20) { nodes { name } }
        subIssues(first: 50) { nodes { ...entry } }
      }
    }
  }
}
fragment entry on Issue { title url state stateReason closedAt }
"""

# The URLs of the issues on a project board, in board order. The owner field,
# user or organization, is filled in before the query is sent.
BOARD_QUERY = """
query($login: String!, $number: Int!) {
  %s(login: $login) {
    projectV2(number: $number) {
      items(first: 100, orderBy: {field: POSITION, direction: ASC}) {
        pageInfo { hasNextPage }
        nodes { content { ... on Issue { url } } }
      }
    }
  }
}
"""


def graphql(query, **variables):
    """Run a GraphQL query with gh and return its data."""
    command = ["gh", "api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        if value is None:
            continue
        # -F sends numbers as numbers; -f sends everything as a string.
        flag = "-F" if isinstance(value, int) else "-f"
        command += [flag, f"{name}={value}"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"GitHub query failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout)["data"]


def fetch_issues(repo):
    """Return every issue in the repository, open and closed, with its sub-issues."""
    owner, name = repo.split("/")
    issues = []
    after = None
    while True:
        data = graphql(ISSUES_QUERY, owner=owner, name=name, after=after)
        page = data["repository"]["issues"]
        issues.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return issues
        after = page["pageInfo"]["endCursor"]


def fetch_board(project):
    """Return the URLs of the issues on the project board, in board order."""
    match = PROJECT_URL.fullmatch(project)
    if match is None:
        raise SystemExit(
            f"{project}: expected a URL such as https://github.com/orgs/NAME/projects/1"
        )
    owner = "user" if match["owner"] == "users" else "organization"
    data = graphql(BOARD_QUERY % owner, login=match["login"], number=int(match["number"]))
    items = data[owner]["projectV2"]["items"]
    if items["pageInfo"]["hasNextPage"]:
        raise SystemExit(f"{project}: more than 100 items on the board")
    urls = []
    for item in items["nodes"]:
        # Draft issues and pull requests come back empty and are skipped.
        if item["content"]:
            urls.append(item["content"]["url"])
    return urls


def is_removed(issue):
    """Return whether an issue was closed for a reason other than being completed."""
    return issue["state"] == "CLOSED" and issue["stateReason"] != "COMPLETED"


def is_objective(issue):
    """Return whether an issue has the objective label."""
    for label in issue["labels"]["nodes"]:
        if label["name"] == OBJECTIVE_LABEL:
            return True
    return False


def make_entry(issue, match):
    """Return the snapshot entry for an issue whose title matched TITLE."""
    entry = {"id": match["id"], "title": match["title"], "url": issue["url"]}
    if issue["state"] == "CLOSED":
        entry["completed"] = datetime.date.fromisoformat(issue["closedAt"][:10])
    return entry


def id_number(entry):
    """Return the last number in an entry's identifier: 3 for O3, 2 for R3.2."""
    return int(IDENTIFIER.fullmatch(entry["id"])["number"])


def build_roadmap(issues, board):
    """Return the snapshot's objectives and a list of warnings.

    Exits listing every error if the issues are inconsistent.
    """
    errors = []
    # Every identifier in use, including by removed entries, with the issues using it.
    uses = defaultdict(list)
    sub_issue_urls = set()
    objectives = []
    key_results_of = {}

    for issue in issues:
        if not is_objective(issue):
            continue
        for sub_issue in issue["subIssues"]["nodes"]:
            sub_issue_urls.add(sub_issue["url"])
        match = TITLE.fullmatch(issue["title"].strip())
        if match is None or match["prefix"] != "O":
            if not is_removed(issue):
                errors.append(
                    f"{issue['url']}: {issue['title']!r} should start with"
                    " an identifier such as O1:"
                )
            continue
        uses[match["id"]].append(issue)
        prefix = f"R{match['number']}."
        key_results = []
        for sub_issue in issue["subIssues"]["nodes"]:
            sub_match = TITLE.fullmatch(sub_issue["title"].strip())
            if sub_match is not None and sub_match["prefix"] == prefix:
                uses[sub_match["id"]].append(sub_issue)
                if not is_removed(sub_issue):
                    key_results.append(make_entry(sub_issue, sub_match))
            elif not is_removed(sub_issue) and not is_removed(issue):
                errors.append(
                    f"{sub_issue['url']}: {sub_issue['title']!r} should start with"
                    f" an identifier such as {prefix}1:"
                )
        if not is_removed(issue):
            objective = make_entry(issue, match)
            objectives.append(objective)
            key_results_of[objective["id"]] = sorted(key_results, key=id_number)

    # Objectives without the label, and key results that are not sub-issues of their
    # objective, would otherwise be left out silently.
    for issue in issues:
        match = TITLE.fullmatch(issue["title"].strip())
        if match is None or is_removed(issue):
            continue
        if match["prefix"] == "O" and not is_objective(issue):
            errors.append(
                f"{issue['url']}: {match['id']} does not have the {OBJECTIVE_LABEL} label"
            )
        elif match["prefix"] != "O" and issue["url"] not in sub_issue_urls:
            errors.append(f"{issue['url']}: {match['id']} is not a sub-issue of its objective")

    for identifier, users in uses.items():
        live = []
        for issue in users:
            if not is_removed(issue):
                live.append(issue["url"])
        if len(live) > 1:
            errors.append(f"{identifier} is used by more than one issue: {', '.join(live)}")
    if errors:
        raise SystemExit("\n".join(errors))

    # Open objectives on the board are ranked in board order; the rest are unranked.
    position = {url: index for index, url in enumerate(board)}
    ranked = []
    for objective in objectives:
        if "completed" not in objective and objective["url"] in position:
            ranked.append(objective)
    ranked.sort(key=lambda objective: position[objective["url"]])
    for rank, objective in enumerate(ranked, 1):
        objective["rank"] = rank

    # The key results are added last so that they come last in each entry of the file.
    for objective in objectives:
        objective["key_results"] = key_results_of[objective["id"]]
    objectives.sort(key=id_number)
    return objectives, find_warnings(uses, objectives)


def find_warnings(uses, objectives):
    """Return warnings about identifiers and objectives that are allowed but look wrong."""
    warnings = []
    numbers_used = defaultdict(set)
    for identifier, users in uses.items():
        match = IDENTIFIER.fullmatch(identifier)
        numbers_used[match["prefix"]].add(int(match["number"]))
        removed = []
        live = []
        for issue in users:
            if is_removed(issue):
                removed.append(issue["url"])
            else:
                live.append(issue["url"])
        if removed and live:
            warnings.append(
                f"{identifier} was removed from the roadmap ({removed[0]})"
                f" but is used again by {live[0]}"
            )

    for prefix, numbers in numbers_used.items():
        for number in range(1, max(numbers)):
            if number not in numbers:
                warnings.append(f"{prefix}{number} was skipped: no issue has that identifier")

    for objective in objectives:
        count = len(objective["key_results"])
        if count == 0 or count > MAX_KEY_RESULTS:
            warnings.append(
                f"{objective['id']} has {count} key results;"
                f" objectives should have between 1 and {MAX_KEY_RESULTS}"
            )
    return warnings


def pull(repo, project, path):
    """Print any warnings and write the snapshot of the roadmap, unless it has not changed."""
    objectives, warnings = build_roadmap(fetch_issues(repo), fetch_board(project))
    for warning in warnings:
        print(warning)

    if Path(path).exists():
        old = load(path)
        same_source = old.get("repository") == repo and old.get("project") == project
        if same_source and old["objectives"] == objectives:
            return
    snapshot = {
        "repository": repo,
        "project": project,
        "as_of": datetime.date.today(),
        "objectives": objectives,
    }
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
    # Ranked objectives come first, in rank order, then the rest in identifier order.
    # The template lists completed objectives separately.
    ranked = []
    others = []
    for objective in snapshot["objectives"]:
        if "rank" in objective:
            ranked.append(objective)
        else:
            others.append(objective)
    ranked.sort(key=lambda objective: objective["rank"])
    template = env.get_template("roadmap.md")
    return template.render(
        doc=snapshot, text=text, objectives=ranked + others, n_ranked=len(ranked)
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    pull_parser = commands.add_parser("pull")
    pull_parser.add_argument("repo", help="the repository holding the issues, as OWNER/NAME")
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
        pull(args.repo, args.project, args.yaml)
    else:
        text = load(args.text or Path(args.yaml).with_name("text.yaml"))
        Path(args.output).write_text(render(load(args.yaml), text))


if __name__ == "__main__":
    main()
