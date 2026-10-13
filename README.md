# The Astropy Roadmap

The roadmap is a set of objectives, each with measurable key results, maintained by the
Astropy Strategic Planning and Organizing Committee (SPOC).

The roadmap lives in GitHub. Each objective is an issue on the roadmap project board, and
its key results are sub-issues of that issue. Every title starts with the entry's
identifier, such as `O3: ...` or `R3.2: ...`; identifiers are chosen by hand, take the
next unused number, and are never renumbered or reused. The SPOC ranks the open objectives
by ordering them on the board. Closing an issue as completed marks its entry done, and
closing it as not planned removes it from the roadmap.

A weekly workflow runs `python roadmap.py pull`, which writes `roadmap.yaml`, a snapshot
of the issues, and opens a pull request with the changes. It stops with a list of
problems if an identifier is missing, does not match its objective, or is used twice.
`text.yaml` holds the wording of the published page, which Read the Docs renders from the
two files with `python roadmap.py render`.
