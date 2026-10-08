#!/usr/bin/env python3
"""Maintain the roadmap from its canonical YAML file.

    python roadmap.py validate roadmap.yaml
    python roadmap.py sync roadmap.yaml --repo OWNER/REPO [--dry-run] [--yes]
    python roadmap.py render roadmap.yaml roadmap.md [--repo OWNER/REPO] [--check]

The YAML file defines the objectives and key results and is edited only by
pull request. Entries are never removed from it or renumbered: an entry that
no longer applies gets a ``retired`` field with the reason. Progress lives in
GitHub, with one issue per objective and one sub-issue per key result; closing
an issue as completed is the record that the entry is done.

``validate`` checks the structure of the YAML file. ``sync`` makes the issues
match it: missing ones are created, titles, bodies and labels are updated, and
retired entries are closed as not planned. It never closes anything as
completed and never deletes. ``render`` writes the markdown document from the
YAML and, with ``--repo``, the issue state; ``--check`` instead fails if the
document on disk is not what would be written. Both need an authenticated
``gh`` when ``--repo`` is given.
"""
import argparse
import datetime
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

The objectives and key results are defined in [`roadmap.yaml`](roadmap.yaml), and changes to their wording or priority are made by pull request to that file. This document is generated from it and from the GitHub issues that track progress: one issue per objective, linked from the line under its heading, with one sub-issue per key result, linked from the end of the key result. Status updates, links to funded work, and links to implementation pull requests belong in the issues. A key result is complete when its issue has been closed as completed, and an objective is complete when the SPOC closes its issue, after which it is listed under completed objectives below. Entries that no longer apply are retired rather than deleted.

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
        if "retired" in entry and not isinstance(entry["retired"], str):
            errors.append(f"{where}: 'retired' must be the reason, as a string")
        if "completed" in entry and not isinstance(entry["completed"], datetime.date):
            errors.append(f"{where}: 'completed' must be a date such as 2026-10-08")
        return True

    for field in ("title", "revision", "introduction"):
        if not isinstance(doc.get(field), str):
            errors.append(f"top level: {field!r} must be a string")
    objectives = doc.get("objectives")
    if not isinstance(objectives, list):
        raise SystemExit(f"{path}: 'objectives' must be a list")
    for i, obj in enumerate(objectives, 1):
        where = f"objective {i}"
        if not check(obj, where, {"id", "title", "priority", "key_results", "retired", "completed"}, "title"):
            continue
        if obj.get("id") != f"O{i}":
            errors.append(f"{where}: id must be O{i}, found {obj.get('id')!r}")
        if "priority" in obj and obj["priority"] not in PRIORITIES:
            errors.append(f"{where}: priority must be one of {', '.join(PRIORITIES)}")
        key_results = obj.get("key_results")
        if not isinstance(key_results, list) or not key_results:
            errors.append(f"{where}: 'key_results' must be a non-empty list")
            continue
        for j, kr in enumerate(key_results, 1):
            where = f"objective {i}, key result {j}"
            if check(kr, where, {"id", "text", "retired", "completed"}, "text") and kr.get("id") != f"R{i}.{j}":
                errors.append(f"{where}: id must be R{i}.{j}, found {kr.get('id')!r}")
    if errors:
        raise SystemExit("\n".join(f"{path}: {e}" for e in errors))
    return doc


def issues(repo):
    """Return {identifier: issue} for every roadmap issue in the repository."""
    found = run("issue", "list", "-R", repo, "-l", "roadmap", "-s", "all", "-L", "1000",
                "--json", "number,title,body,state,stateReason,labels")
    return {m[1]: issue for issue in found if (m := re.match(r"(O\d+|R\d+\.\d+):", issue["title"]))}


def entry_url(repo, doc_path, obj):
    anchor = re.sub(r"[^\w\s-]", "", f"{obj['id']} {obj['title']}".lower()).replace(" ", "-")
    return f"https://github.com/{repo}/blob/main/{doc_path}#{anchor}"


def sync(doc, repo, doc_path, dry):
    existing = issues(repo)
    changes = []

    def ensure(entry, title, body, labels, retired, parent=None):
        """Create or update the issue for an entry; return its number, or None in a dry run."""
        if issue := existing.get(entry["id"]):
            want = {"title": title, "body": body,
                    "labels": sorted(labels + ["retired"] * retired)}
            have = {"title": issue["title"], "body": issue["body"].replace("\r\n", "\n").rstrip(),
                    "labels": sorted(label["name"] for label in issue["labels"])}
            patch = {k: v for k, v in want.items() if v != have[k]}
            if retired and issue["state"] == "OPEN":
                patch.update(state="closed", state_reason="not_planned")
            elif not retired and issue["stateReason"] == "NOT_PLANNED":
                patch.update(state="open")
            if patch:
                changes.append(f"update  #{issue['number']} {entry['id']}: {', '.join(patch)}")
                dry or run("api", "-X", "PATCH", f"repos/{repo}/issues/{issue['number']}", payload=patch)
            return issue["number"]
        changes.append(f"create  {title}")
        if dry:
            return None
        payload = {"title": title, "body": body, "labels": labels + ["retired"] * retired}
        issue = run("api", "-X", "POST", f"repos/{repo}/issues", payload=payload)
        if parent:
            # The endpoint wants the database id of the sub-issue, not its number.
            run("api", "-X", "POST", f"repos/{repo}/issues/{parent}/sub_issues",
                payload={"sub_issue_id": issue["id"]})
        if retired:
            run("api", "-X", "PATCH", f"repos/{repo}/issues/{issue['number']}",
                payload={"state": "closed", "state_reason": "not_planned"})
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
                "issue as completed when the objective has been achieved.")
        number = ensure(obj, f"{obj['id']}: {obj['title']}", body, ["roadmap", "objective"], "retired" in obj)
        for kr in obj["key_results"]:
            body = (f"Key result **{kr['id']}** of objective **{obj['id']}**"
                    f"{f' (#{number})' if number else ''}: {kr['text']}\n\n**Roadmap entry:** {url}\n\n"
                    "Close this issue as completed when the key result has been achieved, with a "
                    "comment pointing at the evidence.")
            # A retired objective retires its key results too.
            ensure(kr, f"{kr['id']}: {kr['text']}", body, ["roadmap", "key result"],
                   "retired" in kr or "retired" in obj, parent=number)
    print("\n".join(changes) or "nothing to do")


def render(doc, repo):
    state = issues(repo) if repo else {}

    def status(entry):
        """Return 'retired', 'done' or 'open', and the issue number if known."""
        issue = state.get(entry["id"])
        number = issue and issue["number"]
        if "retired" in entry:
            return "retired", number
        if "completed" in entry or issue and issue["stateReason"] == "COMPLETED":
            return "done", number
        return "open", number

    def link(number):
        return f" [[#{number}](https://github.com/{repo}/issues/{number})]" if number else ""

    def objective(obj):
        status_, number = status(obj)
        done = [status(kr)[0] == "done" for kr in obj["key_results"] if "retired" not in kr]
        notes = []
        if "priority" in obj:
            notes.append(f"Priority: {obj['priority']}")
        if number:
            notes.append(f"Tracking issue: [#{number}](https://github.com/{repo}/issues/{number})")
        notes.append(f"{sum(done)} of {len(done)} key results complete")
        out = [f"### {obj['id']} {obj['title']}", "", f"*{' · '.join(notes)}*", ""]
        for kr in obj["key_results"]:
            kr_status, kr_number = status(kr)
            if kr_status == "retired":
                out.append(f"- ~~**{kr['id']}** {kr['text']}~~ Retired: {kr['retired']}{link(kr_number)}")
            else:
                out.append(f"- [{'x' if kr_status == 'done' else ' '}] **{kr['id']}** {kr['text']}{link(kr_number)}")
        return out + [""]

    groups = {"open": [], "done": [], "retired": []}
    for obj in doc["objectives"]:
        groups[status(obj)[0]].append(obj)
    today = datetime.date.today().isoformat()
    out = [f"# {doc['title']}", "",
           "<!-- Generated by roadmap.py from roadmap.yaml; edit those instead of this file. -->", "",
           f"**Latest revision: {doc['revision']}**" + (f" · *Status from GitHub issues as of {today}*" if repo else ""), "",
           "## Introduction", "", doc["introduction"].rstrip(), "",
           HOW_TO_READ, "## Objectives", ""]
    for obj in groups["open"]:
        out += objective(obj)
    if groups["done"]:
        out += ["## Completed objectives", ""]
        for obj in groups["done"]:
            out += objective(obj)
    if groups["retired"]:
        out += ["## Retired objectives", ""]
        out += [f"- **{obj['id']}** {obj['title']}. Retired: {obj['retired']}" for obj in groups["retired"]] + [""]
    return "\n".join(out)


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
    sub.choices["render"].add_argument("output", help="markdown file to write")
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
        text = render(doc, args.repo)
        if args.check:
            if open(args.output).read() != text:
                raise SystemExit(f"{args.output} is out of date; run: python roadmap.py render {args.yaml} {args.output}")
            print(f"{args.output} is up to date")
        else:
            open(args.output, "w").write(text)


if __name__ == "__main__":
    main()
