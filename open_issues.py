#!/usr/bin/env python3
"""Open GitHub tracking issues for the roadmap: one issue per objective and one
sub-issue per key result. Re-runnable: issues are matched by the identifier at
the start of their title (``O3:`` or ``R3.2:``) and only missing ones are made.
Requires an authenticated ``gh``. Run from the repository root so that the
roadmap path matches its location on GitHub, which is used for links in issue
bodies. A dry run does not contact GitHub, so it reports every issue as new.

    python open_issues.py roadmap.md --repo OWNER/REPO [--dry-run]
"""
import argparse
import json
import re
import subprocess

OBJECTIVE_RE = re.compile(r"### (O\d+) (.+)")
# A trailing issue link, as written back by this script, is not part of the key result text.
KEY_RESULT_RE = re.compile(r"- \*\*(R\d+\.\d+)\*\* (.+?)(?: \[\[#\d+\]\([^)]*\)\])?$")


def run(*cmd, payload=None):
    result = subprocess.run(["gh", *cmd, *(["--input", "-"] if payload else [])],
                            input=json.dumps(payload) if payload else None,
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"gh {' '.join(cmd)} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def parse(lines):
    """Return [(objective id, title, line number, [(kr id, kr text, line number), ...]), ...]."""
    objectives, seen = [], set()
    for lineno, line in enumerate(lines):
        if m := OBJECTIVE_RE.match(line):
            objectives.append((m[1], m[2], lineno, []))
        elif m := KEY_RESULT_RE.match(line):
            if not objectives or not m[1].startswith("R" + objectives[-1][0][1:] + "."):
                raise SystemExit(f"line {lineno + 1}: {m[1]} is not under its objective")
            objectives[-1][3].append((m[1], m[2], lineno))
        else:
            continue
        if m[1] in seen:
            raise SystemExit(f"line {lineno + 1}: duplicate identifier {m[1]}")
        seen.add(m[1])
    return objectives


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("roadmap", help="path to the roadmap markdown file, relative to the repository root")
    p.add_argument("--repo", required=True, help="target repository as owner/name")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    repo, dry = args.repo, args.dry_run
    url = f"https://github.com/{repo}/blob/main/{args.roadmap}"

    def link(number):
        return f"[#{number}](https://github.com/{repo}/issues/{number})"

    lines = open(args.roadmap).read().split("\n")
    objectives = parse(lines)
    n_kr = sum(len(o[3]) for o in objectives)
    if not dry:
        answer = input(f"Create up to {len(objectives)} objective issues and {n_kr} key result "
                       f"sub-issues in {repo}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            raise SystemExit("aborted")

    for name, color in {"roadmap": "0e8a16", "objective": "1d76db", "key result": "5319e7"}.items():
        dry or run("label", "create", name, "-R", repo, "--color", color, "--force")
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

    tracking = []
    for oid, title, lineno, key_results in objectives:
        anchor = re.sub(r"[^\w\s-]", "", f"{oid} {title}".lower()).replace(" ", "-")
        body = (f"**Roadmap entry:** {url}#{anchor}\n\n## Key results\n\n"
                + "".join(f"- **{rid}** {rtext}\n" for rid, rtext, _ in key_results)
                + "\nEach key result is tracked as a sub-issue of this issue. Changes to the "
                "wording or priority of the objective are made by pull request to the roadmap; "
                "progress updates and links to funded work and implementation PRs belong here.\n")
        number, _ = create(f"{oid}: {title}", body, ["roadmap", "objective"])
        tracking.append((lineno, number))
        for rid, rtext, kr_lineno in key_results:
            body = (f"Key result **{rid}** of objective **{oid}** (#{number}): {rtext}\n\n"
                    f"**Roadmap entry:** {url}#{anchor}\n\nClose this issue when the key result "
                    "has been achieved, with a comment pointing at the evidence.\n")
            child, child_id = create(f"{rid}: {rtext}", body, ["roadmap", "key result"])
            # Attach newly created key results; the endpoint wants the database id, not the number.
            if child_id is not None and not dry:
                run("api", "-X", "POST", f"repos/{repo}/issues/{number}/sub_issues",
                    payload={"sub_issue_id": child_id})
            if child:
                lines[kr_lineno] = f"- **{rid}** {rtext} [{link(child)}]"

    # Record each objective issue under its heading, replacing an existing Tracking line
    # if the next non-blank line is one. Work bottom up so earlier line numbers stay valid.
    for lineno, number in reversed(tracking):
        if not number:
            continue
        nxt = lineno + 1
        while nxt < len(lines) and not lines[nxt].strip():
            nxt += 1
        if nxt < len(lines) and lines[nxt].startswith("*Tracking"):
            lines[nxt] = f"*Tracking issue: {link(number)}*"
        else:
            lines[lineno + 1:lineno + 1] = ["", f"*Tracking issue: {link(number)}*"]
    if not dry:
        open(args.roadmap, "w").write("\n".join(lines))


if __name__ == "__main__":
    main()
