"""Sphinx configuration for the roadmap site.

The page is rendered from roadmap.yaml and text.yaml at the start of every build, so no
generated file is kept in the repository. The theme is the one used by astropy.org.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import roadmap

doc = roadmap.load(ROOT / "roadmap.yaml")
text = roadmap.load_text(ROOT / "text.yaml")
Path(__file__).with_name("index.md").write_text(roadmap.render(doc, text, None))

project = text["title"]
copyright = "The Astropy Developers"
extensions = ["myst_parser"]
myst_enable_extensions = ["tasklist"]
myst_heading_anchors = 3

html_theme = "astropy-unified"
html_title = ""
html_sidebars = {"**": []}
html_theme_options = {"show_prev_next": False}
# Read the Docs sets the clone URL; use it for the GitHub link in the header.
if clone := os.environ.get("READTHEDOCS_GIT_CLONE_URL"):
    html_theme_options["github_url"] = clone.removesuffix(".git")
