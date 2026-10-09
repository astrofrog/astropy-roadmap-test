#!/usr/bin/env python3
"""Maintain the roadmap from its canonical YAML files.

    python roadmap.py validate roadmap.yaml
    python roadmap.py sync roadmap.yaml --repo OWNER/REPO --site URL [--dry-run] [--yes]
    python roadmap.py pull roadmap.yaml --repo OWNER/REPO [--dry-run]
    python roadmap.py render roadmap.yaml roadmap.md [--repo OWNER/REPO] [--check]

``roadmap.yaml`` defines the objectives and key results; ``text.yaml`` next to
it (or the file given with ``--text``) holds the page wording and the issue
body templates. Both are edited only by pull request. Identifiers are never
renumbered or reused; an entry that no longer applies is removed, leaving a
gap. Progress lives in GitHub, with one issue per objective and one sub-issue
per key result, and a closed issue is the record that its entry is done.

``validate`` checks the structure of both files. ``sync`` makes the issues
match the YAML: missing ones are created, titles, bodies and labels are
updated, and issues for entries no longer in the file are closed; it never
deletes. It then does what ``pull`` does on its own: records each entry's
tracking issue number as ``issue`` and the date its issue was closed as
``completed`` in the YAML file, so the file is a complete record and rendering
needs no network. Those two fields are written by the script, not by hand.
``render`` writes the markdown document from the YAML, or from live issue
state with ``--repo``; ``--check`` instead fails if the document on disk is
not what would be written. The documentation build in ``docs/`` calls it at
build time. ``gh`` must be authenticated whenever ``--repo`` is given.
"""

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path

import jinja2
from ruamel.yaml import YAML, YAMLError

yaml = YAML(typ="safe")

LABELS = {"roadmap": "0e8a16", "objective": "1d76db", "key result": "5319e7"}
PRIORITIES = ("high", "medium", "low")


def today():
    return datetime.datetime.now(tz=datetime.UTC).date().isoformat()


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
        if "completed" in entry and not isinstance(entry["completed"], datetime.date):
            errors.append(f"{where}: 'completed' must be a date such as 2026-10-01")
        if "issue" in entry and not isinstance(entry["issue"], int):
            errors.append(f"{where}: 'issue' must be an issue number")
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

    if not isinstance(doc.get("revision"), str):
        errors.append("top level: 'revision' must be a string")
    if "status_as_of" in doc and not isinstance(doc["status_as_of"], datetime.date):
        errors.append("top level: 'status_as_of' must be a date")
    if "repository" in doc and not isinstance(doc["repository"], str):
        errors.append("top level: 'repository' must be a string such as astropy/astropy-project")
    objectives = doc.get("objectives")
    if not isinstance(objectives, list):
        raise SystemExit(f"{path}: 'objectives' must be a list")
    n = 0
    for i, obj in enumerate(objectives, 1):
        where = f"objective {i}"
        if not check(
            obj, where, {"id", "title", "priority", "key_results", "issue", "completed"}, "title"
        ):
            continue
        n = number(obj, "O", where, n)
        if obj.get("priority") not in PRIORITIES:
            errors.append(f"{where}: priority must be one of {', '.join(PRIORITIES)}")
        key_results = obj.get("key_results")
        if not isinstance(key_results, list) or not key_results:
            errors.append(f"{where}: 'key_results' must be a non-empty list")
            continue
        m = 0
        for j, kr in enumerate(key_results, 1):
            where = f"objective {i}, key result {j}"
            if check(kr, where, {"id", "text", "issue", "completed"}, "text"):
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
    found = run(
        "issue",
        "list",
        "-R",
        repo,
        "-l",
        "roadmap",
        "-s",
        "all",
        "-L",
        "1000",
        "--json",
        "number,title,body,state,labels,closedAt",
    )
    return {m[1]: issue for issue in found if (m := re.match(r"(O\d+|R\d+\.\d+):", issue["title"]))}


def entry_url(site, obj):
    anchor = re.sub(r"[^\w\s-]", "", f"{obj['id']} {obj['title']}".lower()).replace(" ", "-")
    return f"{site.rstrip('/')}/#{anchor}"


def sync(doc, text, repo, site, dry):
    existing = issues(repo)
    changes = []
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
                changes.append(f"update  #{issue['number']} {entry['id']}: {', '.join(patch)}")
                dry or run(
                    "api", "-X", "PATCH", f"repos/{repo}/issues/{issue['number']}", payload=patch
                )
            return issue["number"]
        changes.append(f"create  {title}")
        if dry:
            return None
        payload = {"title": title, "body": body, "labels": labels}
        issue = run("api", "-X", "POST", f"repos/{repo}/issues", payload=payload)
        if parent:
            # The endpoint wants the database id of the sub-issue, not its number.
            run(
                "api",
                "-X",
                "POST",
                f"repos/{repo}/issues/{parent}/sub_issues",
                payload={"sub_issue_id": issue["id"]},
            )
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
            changes.append(f"close   #{issue['number']} {entry_id}: no longer in the roadmap")
            dry or run(
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/{issue['number']}",
                payload={"state": "closed", "state_reason": "not_planned"},
            )
    print("\n".join(changes) or "nothing to do")


def pull(path, repo, dry):
    """Record issue numbers and completion dates from GitHub in the YAML file.

    Returns the list of changes. The file is rewritten in place, keeping its
    formatting, and only when something changed.
    """
    state = issues(repo)
    rt = YAML()
    rt.preserve_quotes = True
    rt.width = 10**6
    doc = rt.load(Path(path).read_text())
    changes = []

    def record(entry):
        issue = state.get(entry["id"])
        if not issue:
            return
        closed = (
            datetime.date.fromisoformat(issue["closedAt"][:10])
            if issue["state"] == "CLOSED"
            else None
        )
        if entry.get("issue") != issue["number"]:
            entry.insert(
                list(entry).index("key_results") if "key_results" in entry else len(entry),
                "issue",
                issue["number"],
            )
            changes.append(f"{entry['id']}: tracking issue #{issue['number']}")
        if closed and entry.get("completed") != closed:
            entry.insert(list(entry).index("issue") + 1, "completed", closed)
            changes.append(f"{entry['id']}: completed {closed}")
        elif not closed and "completed" in entry:
            del entry["completed"]
            changes.append(f"{entry['id']}: reopened")

    for obj in doc["objectives"]:
        record(obj)
        for kr in obj["key_results"]:
            record(kr)
    if doc.get("repository") != repo:
        doc.pop("repository", None)
        doc.insert(1, "repository", repo)
        changes.append(f"tracking issues are in {repo}")
    if changes:
        doc.pop("status_as_of", None)
        doc.insert(2, "status_as_of", datetime.date.fromisoformat(today()))
        if not dry:
            with Path(path).open("w") as f:
                rt.dump(doc, f)
    return changes


def collect(doc, repo):
    """Return the objectives with their issue state folded in, split into open and completed."""
    state = issues(repo) if repo else {}

    def status(entry):
        """Fold in the issue number and completion date, from the YAML or from GitHub."""
        issue = state.get(entry["id"])
        number = issue["number"] if issue else entry.get("issue")
        completed = entry.get("completed")
        if issue:
            completed = issue["closedAt"][:10] if issue["state"] == "CLOSED" else None
        return {
            **entry,
            "done": completed is not None,
            "completed": completed,
            "number": number,
            "url": (
                f"https://github.com/{repo or doc['repository']}/issues/{number}"
                if number and (repo or "repository" in doc)
                else None
            ),
        }

    objectives = []
    for obj in doc["objectives"]:
        obj = status(obj)
        obj["key_results"] = [status(kr) for kr in obj["key_results"]]
        obj["n_done"] = sum(kr["done"] for kr in obj["key_results"])
        objectives.append(obj)
    return ([o for o in objectives if not o["done"]], [o for o in objectives if o["done"]])


def to_markdown(doc, text, repo, open_, completed):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(Path(__file__).resolve().parent / "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    status = (
        f"Status from GitHub issues as of {today()}"
        if repo
        else f"Completion status last updated {doc['status_as_of']}"
        if "status_as_of" in doc
        else None
    )
    return env.get_template("roadmap.md").render(
        doc=doc, text=text, status=status, open=open_, completed=completed
    )


def render(doc, text, repo):
    return to_markdown(doc, text, repo, *collect(doc, repo))


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
        if name != "validate":
            sp.add_argument(
                "--repo", required=name != "render", help="GitHub repository as owner/name"
            )
        if name in ("sync", "pull"):
            sp.add_argument(
                "--dry-run", action="store_true", help="report changes without making them"
            )
    sub.choices["sync"].add_argument(
        "--site", required=True, help="URL of the published roadmap page, for links in issue bodies"
    )
    sub.choices["sync"].add_argument(
        "--yes", action="store_true", help="do not ask for confirmation"
    )
    sub.choices["render"].add_argument("output", help="markdown file to write")
    sub.choices["render"].add_argument(
        "--check",
        action="store_true",
        help="exit with an error if the output file is not up to date",
    )
    args = p.parse_args()

    doc = load(args.yaml)
    text_path = args.text or Path(args.yaml).with_name("text.yaml")
    text = load_text(text_path)
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
        print("\n".join(pull(args.yaml, args.repo, args.dry_run)) or "status unchanged")
    elif args.command == "pull":
        print("\n".join(pull(args.yaml, args.repo, args.dry_run)) or "status unchanged")
    else:
        rendered = render(doc, text, args.repo)
        if args.check:
            if Path(args.output).read_text() != rendered:
                raise SystemExit(
                    f"{args.output} is out of date; run: python roadmap.py render {args.yaml} {args.output}"
                )
            print(f"{args.output} is up to date")
        else:
            Path(args.output).write_text(rendered)


if __name__ == "__main__":
    main()
