#!/usr/bin/env python3
"""Maintain the roadmap from its canonical YAML files.

    python roadmap.py validate roadmap.yaml
    python roadmap.py sync roadmap.yaml --repo OWNER/REPO --site URL [--dry-run] [--yes]
    python roadmap.py pull roadmap.yaml --repo OWNER/REPO [--project URL] [--dry-run]
    python roadmap.py render roadmap.yaml roadmap.md

``roadmap.yaml`` defines the objectives and key results; ``text.yaml`` next to
it (or the file given with ``--text``) holds the page wording and the issue
body templates. Both are edited only by pull request, never by this script.
Identifiers are never renumbered or reused; an entry that no longer applies is
removed, leaving a gap. Progress lives in GitHub, with one issue per objective
and one sub-issue per key result, and a closed issue is the record that its
entry is done. Open objectives are ranked by the order of their issues on a
GitHub project board, which adds new objective issues itself through its
built-in auto-add workflow (filter ``is:issue label:objective``).

``validate`` checks the structure of both files. ``sync`` makes the issues
match the YAML: missing ones are created, titles, descriptions and labels are
updated, and issues for entries no longer in the file are closed; it never
deletes. ``pull`` goes the other way: it writes
``status.yaml`` next to the roadmap (or the file given with ``--status``), a
cache of what GitHub records: each entry's issue number, the date its issue
was closed, and, with ``--project``, the rank of each open objective on the
board. The cache is rewritten in full and is not edited by hand. Both commands
print one line per change and nothing else, so the output can serve as a
change log. ``render`` writes the markdown document from the YAML files alone,
without the status if ``status.yaml`` is missing; the documentation build in
``docs/`` calls it at build time. ``gh`` must be authenticated for ``sync`` and
``pull``, with the ``read:project`` scope for ``--project``.
"""

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path

import jinja2
from ruamel.yaml import YAML, YAMLError

yaml = YAML(typ="safe", pure=True)
# Write each status entry on one line.
yaml.default_flow_style = None
yaml.sort_base_mapping_type_on_output = False

LABELS = {"roadmap": "0e8a16", "objective": "1d76db", "key result": "5319e7"}
PROJECT_URL = re.compile(r"https://github\.com/(users|orgs)/([^/]+)/projects/(\d+)/?")


def today():
    return datetime.datetime.now(tz=datetime.UTC).date()


def run(*cmd, payload=None):
    result = subprocess.run(
        ["gh", *cmd, *(["--input", "-"] if payload else [])],
        input=json.dumps(payload) if payload else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit(f"gh {' '.join(cmd)} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def load(path):
    """Return the parsed YAML file, or exit listing every structural problem."""
    try:
        doc = yaml.load(Path(path).read_text())
    except YAMLError as exc:
        raise SystemExit(
            f"{path}: not valid YAML (an unquoted colon in a title is the usual cause)\n{exc}"
        )
    errors = []

    def check(entry, where, fields, text_field):
        if not isinstance(entry, dict):
            errors.append(f"{where}: expected a mapping")
            return False
        for key in entry.keys() - fields:
            errors.append(f"{where}: unknown field {key!r}")
        if not isinstance(entry.get(text_field), str) or not entry[text_field].strip():
            errors.append(
                f"{where}: {text_field!r} must be a non-empty string"
                " (quote it if it contains a colon)"
            )
        return True

    def number(entry, prefix, where, previous):
        """Return the number following prefix in the entry's id, which must exceed the previous one."""
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", str(entry.get("id")))
        if not m:
            errors.append(
                f"{where}: id {entry.get('id')!r} should be {prefix} followed by a number"
            )
            return previous
        if int(m[1]) <= previous:
            errors.append(
                f"{where}: id {entry['id']} is out of order; new entries take the next unused number"
            )
        return int(m[1])

    for key in doc.keys() - {"revision", "objectives"}:
        errors.append(f"top level: unknown field {key!r}")
    if not isinstance(doc.get("revision"), str):
        errors.append("top level: 'revision' must be a string")
    objectives = doc.get("objectives")
    if not isinstance(objectives, list):
        raise SystemExit(f"{path}: 'objectives' must be a list")
    n = 0
    for i, obj in enumerate(objectives, 1):
        where = f"objective {i}"
        if not check(obj, where, {"id", "title", "key_results"}, "title"):
            continue
        n = number(obj, "O", where, n)
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


def load_text(path):
    """Return the parsed wording file, or exit listing every problem."""
    try:
        text = yaml.load(Path(path).read_text())
    except YAMLError as exc:
        raise SystemExit(f"{path}: not valid YAML\n{exc}")
    errors = []
    for field in ("title", "footer"):
        if not isinstance(text.get(field), str):
            errors.append(f"{field!r} must be a string")
    for i, section in enumerate(text.get("sections") or [], 1):
        if not isinstance(section, dict) or not all(
            isinstance(section.get(k), str) for k in ("title", "text")
        ):
            errors.append(f"section {i}: must have a 'title' and a 'text', both strings")
    for kind in ("objective", "key_result"):
        if not isinstance((text.get("issues") or {}).get(kind), str):
            errors.append(f"issues.{kind} must be a template string")
    if errors:
        raise SystemExit("\n".join(f"{path}: {e}" for e in errors))
    return text


def issues(repo):
    """Return {identifier: issue} for every roadmap issue in the repository."""
    fields = "number,title,body,state,labels,closedAt"
    found = run(*f"issue list -R {repo} -l roadmap -s all -L 1000 --json {fields}".split())
    return {m[1]: issue for issue in found if (m := re.match(r"(O\d+|R\d+\.\d+):", issue["title"]))}


def project_items(url):
    """Return the project's issues as (repository, number), in board order."""
    m = PROJECT_URL.fullmatch(url)
    if not m:
        raise SystemExit(f"{url}: expected a URL such as https://github.com/orgs/NAME/projects/1")
    owner = {"users": "user", "orgs": "organization"}[m[1]]
    query = f"""
    query($login: String!, $number: Int!, $after: String) {{
      {owner}(login: $login) {{ projectV2(number: $number) {{
        items(first: 100, after: $after, orderBy: {{field: POSITION, direction: ASC}}) {{
          pageInfo {{ hasNextPage endCursor }}
          nodes {{ content {{ ... on Issue {{ number repository {{ nameWithOwner }} }} }} }}
        }}
      }} }}
    }}"""
    items, after = [], None
    while True:
        variables = {"login": m[2], "number": int(m[3]), "after": after}
        project = run("api", "graphql", payload={"query": query, "variables": variables})
        project = project["data"][owner]["projectV2"]
        page = project["items"]
        # Draft issues and pull requests have no issue content and are skipped.
        items += [
            (c["repository"]["nameWithOwner"], c["number"])
            for node in page["nodes"]
            if (c := node["content"]) and "number" in c
        ]
        if not page["pageInfo"]["hasNextPage"]:
            return items
        after = page["pageInfo"]["endCursor"]


def entry_url(site, obj):
    anchor = re.sub(r"[^\w\s-]", "", f"{obj['id']} {obj['title']}".lower()).replace(" ", "-")
    return f"{site.rstrip('/')}/#{anchor}"


def sync(doc, text, repo, site, dry):
    existing = issues(repo)
    quiet = True

    def report(line):
        nonlocal quiet
        quiet = False
        print(line, flush=True)

    def api(method, path, **payload):
        return run("api", "-X", method, f"repos/{repo}/{path}", payload=payload)

    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    body_of = {kind: env.from_string(text["issues"][kind]) for kind in ("objective", "key_result")}

    def ensure(entry, title, body, labels, parent=None):
        """Create or update the issue for an entry; return its number, or None in a dry run."""
        if issue := existing.pop(entry["id"], None):
            want = {"title": title, "body": body, "labels": sorted(labels)}
            have = {
                "title": issue["title"],
                "body": issue["body"].replace("\r\n", "\n").rstrip(),
                "labels": sorted(label["name"] for label in issue["labels"]),
            }
            if patch := {k: v for k, v in want.items() if v != have[k]}:
                what = " and ".join(patch).replace("body", "description")
                report(f"updated #{issue['number']} {entry['id']}: {what}")
                dry or api("PATCH", f"issues/{issue['number']}", **patch)
            return issue["number"]
        if dry:
            report(f"created {title}")
            return None
        issue = api("POST", "issues", title=title, body=body, labels=labels)
        report(f"created #{issue['number']} {title}")
        if parent:
            # The endpoint wants the database id of the sub-issue, not its number.
            api("POST", f"issues/{parent}/sub_issues", sub_issue_id=issue["id"])
        return issue["number"]

    for name, color in LABELS.items():
        dry or run("label", "create", name, "-R", repo, "--color", color, "--force")
    for obj in doc["objectives"]:
        url = entry_url(site, obj)
        body = body_of["objective"].render(**obj, url=url).strip()
        number = ensure(obj, f"{obj['id']}: {obj['title']}", body, ["roadmap", "objective"])
        for kr in obj["key_results"]:
            body = (
                body_of["key_result"]
                .render(**kr, objective={**obj, "number": number}, url=url)
                .strip()
            )
            ensure(kr, f"{kr['id']}: {kr['text']}", body, ["roadmap", "key result"], parent=number)
    # Whatever is left was removed from the YAML, including the key results of a removed objective.
    for entry_id, issue in existing.items():
        if issue["state"] == "OPEN":
            report(f"closed  #{issue['number']} {entry_id}: removed from the roadmap")
            dry or api(
                "PATCH", f"issues/{issue['number']}", state="closed", state_reason="not_planned"
            )
    if quiet:
        print("issues already match the roadmap")


def load_status(path):
    """Return the status cache, or an empty one if it has not been written yet."""
    path = Path(path)
    return (yaml.load(path.read_text()) or {}) if path.exists() else {}


def pull(doc, path, repo, project, dry):
    """Write the status cache from GitHub, printing one line per change.

    The file is written only when something changed, so that ``as_of`` is the
    date the status last changed.
    """
    state = issues(repo)
    entries = {}
    for entry in (e for obj in doc["objectives"] for e in [obj, *obj["key_results"]]):
        if issue := state.get(entry["id"]):
            entries[entry["id"]] = {"issue": issue["number"]}
            if issue["state"] == "CLOSED":
                entries[entry["id"]]["completed"] = datetime.date.fromisoformat(
                    issue["closedAt"][:10]
                )
    if project:
        open_objectives = {
            e["issue"]: entry_id
            for entry_id, e in entries.items()
            if entry_id.startswith("O") and "completed" not in e
        }
        ranking = [
            open_objectives[n]
            for r, n in project_items(project)
            if r == repo and n in open_objectives
        ]
        for rank, entry_id in enumerate(ranking, 1):
            entries[entry_id]["rank"] = rank
    old = load_status(path)
    new = {"repository": repo, "project": project, "entries": entries}
    if all(old.get(key) == value for key, value in new.items()):
        print("status already recorded")
        return
    if old.get("repository") != repo:
        print(f"tracking issues are in {repo}")
    if old.get("project") != project:
        print(f"objectives are ranked on {project}" if project else "objectives are not ranked")
    before = old.get("entries") or {}
    for entry_id, e in entries.items():
        b = before.get(entry_id, {})
        if b.get("issue") != e["issue"]:
            print(f"{entry_id} is tracked in #{e['issue']}")
        if "completed" in e and b.get("completed") != e["completed"]:
            print(f"{entry_id} completed on {e['completed']}")
        elif "completed" in b and "completed" not in e:
            print(f"{entry_id} reopened, no longer complete")
    for entry_id in before.keys() - entries.keys():
        print(f"{entry_id} is no longer tracked")

    def ranking(entries):
        return sorted(
            (i for i, e in entries.items() if "rank" in e), key=lambda i: entries[i]["rank"]
        )

    if (order := ranking(entries)) != ranking(before):
        print(f"ranking is now {', '.join(order)}" if order else "no objectives are ranked")
    if not dry:
        with Path(path).open("w") as f:
            f.write("# Written by roadmap.py pull from GitHub; do not edit.\n")
            new = {"repository": repo, "project": project, "as_of": today(), "entries": entries}
            yaml.dump({k: v for k, v in new.items() if v is not None}, f)


def render(doc, text, status):
    """Return the markdown document from the roadmap, the wording, and the status cache."""
    github = status.get("repository")
    entries = status.get("entries") or {}

    def with_status(entry):
        """Add the cached status, issue link, and completion flag to an entry."""
        entry = {**entry, **entries.get(entry["id"], {})}
        if number := entry.get("issue"):
            entry["link"] = f"[#{number}](https://github.com/{github}/issues/{number})"
        return {**entry, "done": "completed" in entry}

    objectives = []
    for obj in doc["objectives"]:
        obj = with_status(obj)
        obj["key_results"] = [with_status(kr) for kr in obj["key_results"]]
        obj["n_done"] = sum(kr["done"] for kr in obj["key_results"])
        objectives.append(obj)
    # Ranked objectives first, in rank order; the rest keep their order in the file.
    objectives.sort(key=lambda obj: obj.get("rank", len(objectives) + 1))
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(Path(__file__).resolve().parent / "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template("roadmap.md").render(
        doc=doc,
        text=text,
        status=status,
        objectives=objectives,
        n_ranked=sum("rank" in obj for obj in objectives),
    )


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("validate", "sync", "pull", "render"):
        sp = sub.add_parser(name)
        sp.add_argument("yaml", help="the canonical roadmap YAML file")
        sp.add_argument(
            "--text", help="the wording file; default: text.yaml next to the roadmap file"
        )
        if name in ("pull", "render"):
            sp.add_argument(
                "--status", help="the status cache; default: status.yaml next to the roadmap file"
            )
        if name in ("sync", "pull"):
            sp.add_argument("--repo", required=True, help="GitHub repository as owner/name")
            sp.add_argument(
                "--dry-run", action="store_true", help="report changes without making them"
            )
    sub.choices["sync"].add_argument(
        "--site", required=True, help="URL of the published roadmap page, for links in issue bodies"
    )
    sub.choices["pull"].add_argument(
        "--project", help="URL of the GitHub project board that ranks the objectives"
    )
    sub.choices["sync"].add_argument(
        "--yes", action="store_true", help="do not ask for confirmation"
    )
    sub.choices["render"].add_argument("output", help="markdown file to write")
    args = p.parse_args()

    doc = load(args.yaml)
    text_path = args.text or Path(args.yaml).with_name("text.yaml")
    text = load_text(text_path)
    status_path = getattr(args, "status", None) or Path(args.yaml).with_name("status.yaml")
    if args.command == "validate":
        n = sum(len(o["key_results"]) for o in doc["objectives"])
        print(
            f"{args.yaml}: {len(doc['objectives'])} objectives, {n} key results; "
            f"{text_path}: {len(text['sections'])} sections; no problems found"
        )
    elif args.command == "sync":
        if not (args.dry_run or args.yes):
            answer = input(f"Create and update roadmap issues in {args.repo}? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                raise SystemExit("aborted")
        sync(doc, text, args.repo, args.site, args.dry_run)
    elif args.command == "pull":
        pull(doc, status_path, args.repo, args.project, args.dry_run)
    else:
        Path(args.output).write_text(render(doc, text, load_status(status_path)))


if __name__ == "__main__":
    main()
