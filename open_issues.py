#!/usr/bin/env python3
"""Open GitHub tracking issues for the roadmap: one issue per objective and one
sub-issue per key result. Re-runnable: issues are matched by the identifier at
the start of their title (``O3:`` or ``R3.2:``) and only missing ones are made.
Requires an authenticated ``gh``.

    python open_issues.py roadmap.md --repo OWNER/REPO [--dry-run]
"""
import argparse
import json
import re
import subprocess

ROADMAP_PATH = "roadmap/roadmap.md"


def run(*cmd, payload=None):
    result = subprocess.run(["gh", *cmd, *(["--input", "-"] if payload else [])],
                            input=json.dumps(payload) if payload else None,
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"gh {' '.join(cmd)} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def parse(text):
    """Return [(objective id, title, line number, [(kr id, kr text, line number), ...]), ...].

    A trailing issue link on a key result line, as written back by this script, is not part of the text.
    Either wrapper, ``[...]`` or the earlier ``(...)``, is recognized.
    """
    objectives = []
    for lineno, line in enumerate(text.splitlines()):
        if m := re.match(r"### (O\d+) (.+)", line):
            objectives.append((m[1], m[2], lineno, []))
        elif m := re.match(r"- \*\*(R\d+\.\d+)\*\* (.+?)(?: [(\[]\[#\d+\]\([^)]*\)[)\]])?$", line):
            objectives[-1][3].append((m[1], m[2], lineno))
    return objectives


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("roadmap")
    p.add_argument("--repo", required=True, help="target repository as owner/name")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    repo, dry = args.repo, args.dry_run
    url = f"https://github.com/{repo}/blob/main/{ROADMAP_PATH}"

    text = open(args.roadmap).read()
    objectives = parse(text)
    n_kr = sum(len(o[3]) for o in objectives)
    if not dry:
        answer = input(f"Create up to {len(objectives)} objective issues and {n_kr} key result "
                       f"sub-issues in {repo}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            raise SystemExit("aborted")
    existing = {} if dry else {
        m[1]: issue["number"]
        for issue in run("issue", "list", "-R", repo, "-l", "roadmap", "-s", "all",
                         "-L", "1000", "--json", "number,title")
        if (m := re.match(r"(O\d+|R\d+\.\d+):", issue["title"]))
    }

    def create(title, body, labels):
        """Return (issue number, database id); the id is None if the issue already existed."""
        if number := existing.get(title.split(":")[0]):
            print(f"exists  #{number} {title}")
            return number, None
        if dry:
            print(f"create  {title}  [{', '.join(labels)}]")
            return 0, 0
        issue = run("api", "-X", "POST", f"repos/{repo}/issues",
                    payload={"title": title, "body": body, "labels": labels})
        print(f"created #{issue['number']} {title}")
        return issue["number"], issue["id"]

    labels = {"roadmap": "0e8a16", "objective": "1d76db", "key result": "5319e7"}
    for name, color in labels.items():
        dry or run("label", "create", name, "-R", repo, "--color", color, "--force")

    tracking, links = [], []
    for oid, title, lineno, key_results in objectives:
        anchor = re.sub(r"[^\w\s-]", "", f"{oid} {title}".lower()).replace(" ", "-")
        body = (f"**Roadmap entry:** {url}#{anchor}\n\n## Key results\n\n"
                + "".join(f"- **{rid}** {rtext}\n" for rid, rtext, _ in key_results)
                + "\nEach key result is tracked as a sub-issue of this issue. Changes to the "
                "wording or priority of the objective are made by pull request to the roadmap; "
                "progress updates and links to funded work and implementation PRs belong here.\n")
        number, _ = create(f"{oid}: {title}", body, ["roadmap", "objective"])
        for rid, rtext, kr_lineno in key_results:
            body = (f"Key result **{rid}** of objective **{oid}** (#{number}): {rtext}\n\n"
                    f"**Roadmap entry:** {url}#{anchor}\n\nClose this issue when the key result "
                    "has been achieved, with a comment pointing at the evidence.\n")
            child, child_id = create(f"{rid}: {rtext}", body, ["roadmap", "key result"])
            links.append((kr_lineno, child))
            # Attach newly created key results; the endpoint wants the database id, not the number.
            if child_id is not None and not dry:
                run("api", "-X", "POST", f"repos/{repo}/issues/{number}/sub_issues",
                    payload={"sub_issue_id": child_id})
        tracking.append((lineno, number))

    # Link each key result line to its issue, then record each objective issue under its
    # heading unless a Tracking line is already there, inserting from the bottom up so
    # earlier line numbers stay valid.
    lines = text.split("\n")
    link = lambda number: f"[#{number}](https://github.com/{repo}/issues/{number})"
    for lineno, number in links:
        if number:
            stripped = re.sub(r" [(\[]\[#\d+\]\([^)]*\)[)\]]$", "", lines[lineno])
            lines[lineno] = f"{stripped} [{link(number)}]"
    for lineno, number in reversed(tracking):
        if not number:
            continue
        if lineno + 2 < len(lines) and lines[lineno + 2].startswith("*Tracking"):
            lines[lineno + 2] = f"*Tracking issue: {link(number)}*"
        else:
            lines[lineno + 1:lineno + 1] = ["", f"*Tracking issue: {link(number)}*"]
    if not dry:
        open(args.roadmap, "w").write("\n".join(lines))


if __name__ == "__main__":
    main()
