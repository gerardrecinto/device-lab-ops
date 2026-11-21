"""Render docs/index.html from docs/index.template.html and the real output of `devicelab demo`."""

import html
import io
import pathlib
import sys
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from devicelab import demo  # noqa: E402


def render():
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo.run()
    tpl = (ROOT / "docs" / "index.template.html").read_text()
    return tpl.replace("<!--DEMO-->", html.escape(buf.getvalue().rstrip()))


if __name__ == "__main__":
    (ROOT / "docs" / "index.html").write_text(render())
    print("wrote docs/index.html")
