#!/usr/bin/env python3
"""Snapshot the roadmap from GitHub, and render it for the documentation.

    python roadmap.py

The roadmap lives in the issues of the GitHub repository set in REPOSITORY. Every issue with the
``objective`` label is an objective, titled with its identifier such as
``O3: ...``. Every issue with the ``key result`` label is a key result, titled
``KR3.1: ...``, ``KR3.2: ...`` and so on, and is a sub-issue of its objective.
Identifiers are never renumbered or reused. An issue closed as completed marks
its entry done, and one closed for any other reason marks it not planned; both
stay in the roadmap as a record. An issue opened by mistake is taken out of the
roadmap by removing its label. Open objectives on the project board set in
PROJECT are ranked by their order there; open objectives not on the board are
unranked.

Running this script writes all of this to the YAML snapshot in SNAPSHOT,
leaving the file alone if nothing has changed. It exits without writing if the
issues are inconsistent, and prints a warning for anything that is allowed but
probably a mistake. ``gh`` must be authenticated with the ``read:project``
scope. The documentation build in ``docs/`` calls ``render``, which returns the
markdown page from the snapshot and the page wording in TEXT.
"""

import datetime
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import jinja2
from ruamel.yaml import YAML

REPOSITORY = "astrofrog/astropy-roadmap-test"
PROJECT = "https://github.com/users/astrofrog/projects/5"
HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "roadmap.yaml"
TEXT = HERE / "text.yaml"

yaml = YAML(typ="safe", pure=True)
yaml.sort_base_mapping_type_on_output = False
yaml.default_flow_style = False
yaml.width = 10**6

PROJECT_URL = re.compile(
    r"https://github\.com/(?P<owner>users|orgs)/(?P<login>[^/]+)/projects/(?P<number>\d+)/?"
)
IDENTIFIER = re.compile(r"(?P<prefix>O|KR\d+\.)(?P<number>\d+)")
TITLE = re.compile(rf"(?P<id>{IDENTIFIER.pattern}):\s*(?P<title>.+)")
OBJECTIVE_LABEL = "objective"
KEY_RESULT_LABEL = "key result"

# Every issue in a repository, open and closed, with its labels and parent issue.
ISSUES_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        title url state stateReason closedAt
        labels(first: 20) { nodes { name } }
        parent { url }
      }
    }
  }
}
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
    """Return every issue in the repository, open and closed."""
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


def labels(issue):
    """Return the names of an issue's labels."""
    names = set()
    for label in issue["labels"]["nodes"]:
        names.add(label["name"])
    return names


def make_entry(issue, match):
    """Return the snapshot entry for an issue whose title matched TITLE."""
    entry = {"id": match["id"], "title": match["title"], "url": issue["url"]}
    if issue["state"] == "CLOSED":
        closed = datetime.date.fromisoformat(issue["closedAt"][:10])
        if issue["stateReason"] == "COMPLETED":
            entry["completed"] = closed
        else:
            entry["not_planned"] = closed
    return entry


def is_open(entry):
    return "completed" not in entry and "not_planned" not in entry


def id_number(entry):
    """Return the last number in an entry's identifier: 3 for O3, 2 for KR3.2."""
    return int(IDENTIFIER.fullmatch(entry["id"])["number"])


def build_roadmap(issues, board):
    """Return the snapshot's objectives, or exit listing every error in the issues."""
    errors = []
    objectives_by_url = {}
    # Objectives whose title is wrong; their key results are skipped, not reported too.
    broken_objective_urls = set()
    key_result_issues = []
    for issue in issues:
        match = TITLE.fullmatch(issue["title"].strip())
        if OBJECTIVE_LABEL in labels(issue):
            if match is None or match["prefix"] != "O":
                errors.append(
                    f"{issue['url']}: {issue['title']!r} should start with"
                    " an identifier such as O1:"
                )
                broken_objective_urls.add(issue["url"])
            else:
                objectives_by_url[issue["url"]] = make_entry(issue, match)
        elif KEY_RESULT_LABEL in labels(issue):
            if match is None or not match["prefix"].startswith("KR"):
                errors.append(
                    f"{issue['url']}: {issue['title']!r} should start with"
                    " an identifier such as KR1.1:"
                )
            else:
                key_result_issues.append((issue, match))

    key_results_by_url = defaultdict(list)
    for issue, match in key_result_issues:
        parent = issue["parent"]
        objective = None
        if parent is not None:
            if parent["url"] in broken_objective_urls:
                continue
            objective = objectives_by_url.get(parent["url"])
        if objective is None:
            errors.append(f"{issue['url']}: {match['id']} is not a sub-issue of an objective")
        elif match["prefix"] != f"KR{id_number(objective)}.":
            errors.append(
                f"{issue['url']}: {match['id']} is a key result of {objective['id']},"
                f" so its identifier should start with KR{id_number(objective)}."
            )
        else:
            key_results_by_url[parent["url"]].append(make_entry(issue, match))

    urls_by_id = defaultdict(list)
    for url, objective in objectives_by_url.items():
        urls_by_id[objective["id"]].append(url)
        for key_result in key_results_by_url[url]:
            urls_by_id[key_result["id"]].append(key_result["url"])
    for identifier, urls in urls_by_id.items():
        if len(urls) > 1:
            errors.append(f"{identifier} is used by more than one issue: {', '.join(urls)}")
    if errors:
        raise SystemExit("\n".join(errors))

    # Open objectives on the board are ranked in board order; the rest are unranked.
    position = {url: index for index, url in enumerate(board)}
    ranked = []
    for url, objective in objectives_by_url.items():
        if is_open(objective) and url in position:
            ranked.append(objective)
    ranked.sort(key=lambda objective: position[objective["url"]])
    for rank, objective in enumerate(ranked, 1):
        objective["rank"] = rank

    # The key results are added last so that they come last in each entry of the file.
    objectives = []
    for url, objective in objectives_by_url.items():
        objective["key_results"] = sorted(key_results_by_url[url], key=id_number)
        objectives.append(objective)
    return sorted(objectives, key=id_number)


def find_warnings(issues, objectives):
    """Return warnings about issues and objectives that are allowed but look wrong."""
    warnings = []
    for issue in issues:
        match = TITLE.fullmatch(issue["title"].strip())
        if match is not None and not labels(issue) & {OBJECTIVE_LABEL, KEY_RESULT_LABEL}:
            warnings.append(
                f"{issue['url']}: {match['id']} has neither the {OBJECTIVE_LABEL} nor the"
                f" {KEY_RESULT_LABEL} label, so it is not part of the roadmap"
            )

    numbers_used = defaultdict(set)
    for objective in objectives:
        numbers_used["O"].add(id_number(objective))
        for key_result in objective["key_results"]:
            numbers_used[f"KR{id_number(objective)}."].add(id_number(key_result))
    for prefix, numbers in numbers_used.items():
        for number in range(1, max(numbers)):
            if number not in numbers:
                warnings.append(f"{prefix}{number} was skipped: no issue has that identifier")

    for objective in objectives:
        if "not_planned" in objective:
            continue
        planned = False
        for key_result in objective["key_results"]:
            if "not_planned" not in key_result:
                planned = True
        if not planned:
            warnings.append(f"{objective['id']} has no planned key results")
    return warnings


def pull():
    """Print any warnings and write the snapshot of the roadmap, unless it has not changed."""
    issues = fetch_issues(REPOSITORY)
    objectives = build_roadmap(issues, fetch_board(PROJECT))
    for warning in find_warnings(issues, objectives):
        print(warning)

    # Leave the file alone, including its date, if only the date would change.
    if SNAPSHOT.exists():
        old = load(SNAPSHOT)
        old.pop("as_of")
        if old == {"objectives": objectives}:
            return
    snapshot = {"as_of": datetime.date.today(), "objectives": objectives}
    with SNAPSHOT.open("w") as f:
        f.write("# Written by roadmap.py from GitHub; do not edit.\n")
        yaml.dump(snapshot, f)


def load(path):
    return yaml.load(path.read_text())


def render():
    """Return the markdown page from the snapshot and the page wording."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(HERE / "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    snapshot = load(SNAPSHOT)
    # Open objectives are listed with the ranked ones first, in rank order, and the
    # unranked ones after them in identifier order.
    ranked = []
    unranked = []
    completed = []
    not_planned = []
    for objective in snapshot["objectives"]:
        if "completed" in objective:
            completed.append(objective)
        elif "not_planned" in objective:
            not_planned.append(objective)
        elif "rank" in objective:
            ranked.append(objective)
        else:
            unranked.append(objective)
    ranked.sort(key=lambda objective: objective["rank"])
    template = env.get_template("roadmap.md")
    return template.render(
        as_of=snapshot["as_of"],
        project=PROJECT,
        text=load(TEXT),
        open_objectives=ranked + unranked,
        completed=completed,
        not_planned=not_planned,
        n_ranked=len(ranked),
    )


if __name__ == "__main__":
    pull()
