# The Astropy Roadmap

The roadmap is a set of objectives, each with measurable key results, maintained by the
Astropy Strategic Planning and Organizing Committee (SPOC).

The roadmap lives in the issues of this repository. Each objective is an issue with the
`objective` label whose title starts with its identifier, such as `O3: ...`, and each of
its key results is a sub-issue with the `key result` label, titled `KR3.1: ...`,
`KR3.2: ...` and so on. Identifiers are chosen by hand, take the next unused number, and are
never renumbered or reused. The SPOC ranks the open objectives by ordering them on the
roadmap project board; objectives not on the board are unranked. Closing an issue as
completed marks its entry done, and closing it as not planned keeps it in the roadmap,
marked not planned, as a record. An issue opened by mistake is taken out of the roadmap by
removing its label.

A weekly workflow runs `python roadmap.py`, which writes `roadmap.yaml`, a snapshot
of the issues, and opens a pull request with the changes. It stops, and reports the
problems in an issue, if a labelled issue's title has no identifier, a key result is not
a sub-issue of an objective or its identifier does not match that objective, or an
identifier is used twice. Issues with an identifier but no label, skipped numbers, and
objectives with no planned key results are listed as warnings in the pull request.

`text.yaml` holds the wording of the published page, which Read the Docs renders from the
two files. The repository and project board are set at the top of `roadmap.py`.
