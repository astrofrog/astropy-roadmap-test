# The Astropy Roadmap

The roadmap is a set of objectives, each with measurable key results, maintained by the
Astropy Strategic Planning and Organizing Committee (SPOC).

- `roadmap.yaml` is the canonical record of the objectives and key results. Change it by
  pull request. Identifiers are never renumbered or reused.
- `text.yaml` holds the wording of the published page and of the GitHub tracking issues.
- `roadmap.py` validates the two files, creates and updates one tracking issue per
  objective and one sub-issue per key result, and renders the page. Run
  `python roadmap.py --help` for the commands.
- `docs/` is the Sphinx configuration that Read the Docs builds into the published page,
  rendering it from the YAML at build time.

Progress is tracked in the issues: closing a key result issue marks it done, and the SPOC
closes an objective issue when the objective has been achieved.
