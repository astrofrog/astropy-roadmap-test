# The Astropy Roadmap

The roadmap is a set of objectives, each with measurable key results, maintained by the
Astropy Strategic Planning and Organizing Committee (SPOC).

The roadmap lives in the issues of this repository. Each objective is an issue with the
`objective` label whose title starts with its identifier, such as `O3: ...`, and its key
results are sub-issues of that issue, titled `R3.1: ...`, `R3.2: ...` and so on. Identifiers are chosen by hand, take
the next unused number, and are never renumbered or reused. The SPOC ranks the open
objectives by ordering them on the roadmap project board; objectives not on the board are
unranked. Closing an issue as completed marks its entry done, and closing it as not
planned removes it from the roadmap; the closed issue keeps its identifier in use.

A weekly workflow runs `python roadmap.py pull`, which writes `roadmap.yaml`, a snapshot
of the issues, and opens a pull request with the changes. It stops, and reports the
problems in an issue, if an objective's title has no identifier, an `O` issue lacks the
label, a key result's identifier does not match its objective, a key result is not a
sub-issue of its objective, or an identifier is used twice. Skipped
numbers, reused identifiers, and objectives without key results or with more than five
are listed as warnings in the pull request.

`text.yaml` holds the wording of the published page, which Read the Docs renders from the
two files with `python roadmap.py render`.
