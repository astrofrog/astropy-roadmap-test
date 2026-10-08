#!/usr/bin/env python3
"""Open GitHub tracking issues for the roadmap: one issue per objective and one
sub-issue per key result. Re-runnable: issues are matched by the identifier at
the start of their title (``O3:`` or ``R3.2:``) and only missing ones are made.
Requires an authenticated ``gh``.

    python open_issues.py roadmap.md [--repo astropy/astropy-project] [--dry-run]
"""
import argparse
import json
import re
import subprocess

ROADMAP_PATH = "roadmap/roadmap.md"


def run(*cmd, payload=None):
    out = subprocess.run(["gh", *cmd, *(["--input", "-"] if payload else [])],
                         input=json.dumps(payload) if payload else None,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else None


def parse(text):
    """Return [(category, objective id, title, line number, [(kr id, kr text), ...]), ...]."""
    objectives, category = [], None
    for lineno, line in enumerate(text.splitlines()):
        if m := re.match(r"## (.+)", line):
            category = m[1]
        elif m := re.match(r"### (O\d+) (.+)", line):
            objectives.append((category, m[1], m[2], lineno, []))
        elif m := re.match(r"- \*\*(R\d+\.\d+)\*\* (.+)", line):
            objectives[-1][4].append((m[1], m[2]))
    return objectives


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("roadmap")
    p.add_argument("--repo", default="astropy/astropy-project")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    repo, dry = args.repo, args.dry_run
    url = f"https://github.com/{repo}/blob/main/{ROADMAP_PATH}"

    text = open(args.roadmap).read()
    objectives = parse(text)
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
    labels |= {f"category: {c.lower()}": "bfd4f2" for c, *_ in objectives}
    for name, color in labels.items():
        dry or run("label", "create", name, "-R", repo, "--color", color, "--force")

    lines = text.split("\n")
    for category, oid, title, lineno, key_results in reversed(objectives):
        anchor = re.sub(r"[^\w\s-]", "", f"{oid} {title}".lower()).replace(" ", "-")
        body = (f"**Category:** {category}\n**Roadmap entry:** {url}#{anchor}\n\n## Key results\n\n"
                + "".join(f"- **{rid}** {rtext}\n" for rid, rtext in key_results)
                + "\nEach key result is tracked as a sub-issue of this issue. Changes to the "
                "wording or priority of the objective are made by pull request to the roadmap; "
                "progress updates and links to funded work and implementation PRs belong here.\n")
        category_label = f"category: {category.lower()}"
        number, _ = create(f"{oid}: {title}", body, ["roadmap", "objective", category_label])
        for rid, rtext in key_results:
            body = (f"Key result **{rid}** of objective **{oid}** (#{number}): {rtext}\n\n"
                    f"**Roadmap entry:** {url}#{anchor}\n\nClose this issue when the key result "
                    "has been achieved, with a comment pointing at the evidence.\n")
            _, child_id = create(f"{rid}: {rtext}", body, ["roadmap", "key result", category_label])
            # Attach newly created key results; the endpoint wants the database id, not the number.
            if child_id is not None and not dry:
                run("api", "-X", "POST", f"repos/{repo}/issues/{number}/sub_issues",
                    payload={"sub_issue_id": child_id})
        # Record the issue under the heading unless a Tracking line is already there.
        if number and "Tracking:" not in lines[lineno + 2]:
            lines[lineno + 1:lineno + 1] = ["", f"*Tracking: {repo}#{number}*"]

    if not dry:
        open(args.roadmap, "w").write("\n".join(lines))


if __name__ == "__main__":
    main()
