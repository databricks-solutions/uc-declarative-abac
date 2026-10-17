"""Sphinx configuration for the UC Declarative ABAC documentation site.

Pages are written in MyST Markdown and rendered with the Read the Docs theme. The project
version is read from ``pyproject.toml`` so building the docs never needs to import the
package. ``smartquotes_action`` deliberately omits dash conversion: the docs must never
contain en or em dashes, and Sphinx would otherwise render ``--`` and ``---`` as dashes.
"""

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_GITHUB_URL = "https://github.com/databricks-solutions/uc-declarative-abac"

project = "UC Declarative ABAC"
author = "Liam Perritt"
copyright = "Liam Perritt and contributors"
release = tomllib.loads(_PYPROJECT.read_text())["project"]["version"]
version = release

extensions = [
    "myst_parser",
    "sphinx_copybutton",
    "sphinx.ext.extlinks",
]

source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build"]
templates_path = ["_templates"]

myst_enable_extensions = ["colon_fence", "deflist", "attrs_inline"]
myst_heading_anchors = 3

smartquotes_action = "qe"

extlinks = {"issue": (f"{_GITHUB_URL}/issues/%s", "issue #%s")}

copybutton_prompt_text = r"\$ "
copybutton_prompt_is_regexp = True

html_theme = "sphinx_rtd_theme"
html_title = "UC Declarative ABAC"
html_logo = "_static/logo.svg"
html_favicon = "_static/favicon.svg"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_show_sphinx = False
html_theme_options = {
    "logo_only": True,
    "navigation_depth": 3,
    "collapse_navigation": False,
    "prev_next_buttons_location": "both",
    "style_external_links": True,
    "style_nav_header_background": "#1B3139",
}
html_context = {
    "display_github": True,
    "github_user": "liamperritt",
    "github_repo": "uc-declarative-abac",
    "github_version": "main",
    "conf_py_path": "/docs/",
}

linkcheck_anchors_ignore_for_url = [r"https://github\.com/.*"]
