"""Build guide.html from README.md.

    python3 tools/build.py

Needs pandoc (https://pandoc.org). Each <!-- widget:NAME --> marker in the
Markdown becomes an interactive widget in the HTML; on GitHub it is invisible.
"""

import pathlib
import re
import subprocess

here = pathlib.Path(__file__).resolve().parent
root = here.parent

body = subprocess.run(
    ["pandoc", "-f", "gfm", "-t", "html", str(root / "README.md")],
    check=True, capture_output=True, text=True).stdout
body = re.sub(r"<!--\s*widget:([\w-]+)\s*-->",
              r'<div data-widget="\1"></div>', body)

template = (here / "template.html").read_text()
(root / "guide.html").write_text(template.replace("{{CONTENT}}", body))
print("wrote", root / "guide.html")
