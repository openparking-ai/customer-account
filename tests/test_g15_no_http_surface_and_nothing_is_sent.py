"""G15 -- this module has no HTTP surface and sends nothing.

No web framework, no HTTP server, no HTTP client and no mail or SMS client is
imported anywhere in the package -- read from the AST of every source file
under ``src/``, never from a grep, so a name inside a docstring (this one
names several) is not a hit and an import inside a function is. The
standalone claim in one test: an integrator embeds this behind whatever
surface they have; this module offers none and delivers nothing.

Controls: an ``import smtplib`` planted into the command line.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "customer_account"

#: Top-level module names that would give this package a network. The
#: standard library's own are here too: a module that imported `http.server`
#: or `smtplib` would have grown a surface without adding a dependency.
FORBIDDEN_IMPORTS = frozenset({
    "http", "smtplib", "email", "imaplib", "poplib", "socket", "socketserver", "ssl",
    "urllib", "xmlrpc", "wsgiref", "asyncio",
    "flask", "fastapi", "uvicorn", "starlette", "aiohttp", "django", "bottle", "tornado",
    "requests", "httpx", "twilio", "boto3", "sendgrid",
})


def imports_in(path: Path) -> set[str]:
    """Every top-level module name imported by ``path``, at any depth."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def source_files() -> tuple[Path, ...]:
    return tuple(sorted(SRC.rglob("*.py")))


@pytest.mark.guarantee("G15")
def test_no_source_file_imports_anything_that_could_serve_or_send():
    files = source_files()
    assert len(files) >= 8, f"the walk found only {len(files)} source files"
    hits = {
        str(path.relative_to(ROOT)): sorted(imports_in(path) & FORBIDDEN_IMPORTS)
        for path in files
    }
    assert {k: v for k, v in hits.items() if v} == {}


@pytest.mark.guarantee("G15")
def test_the_walk_reads_real_imports_and_is_not_fooled_by_a_docstring(tmp_path):
    """The control: a planted import is found, at module level and inside a
    function; the same name in a docstring or a comment is not."""
    planted = tmp_path / "planted.py"
    planted.write_text('"""mentions smtplib and flask in prose."""\n'
                       "# import fastapi\n"
                       "def f():\n    import smtplib\n    return smtplib\n"
                       "from http import server\n")
    assert imports_in(planted) & FORBIDDEN_IMPORTS == {"smtplib", "http"}
    clean = tmp_path / "clean.py"
    clean.write_text('"""smtplib flask http.server"""\nimport hashlib\n')
    assert imports_in(clean) & FORBIDDEN_IMPORTS == set()
    # and the real command line is in the set the first test walks
    assert SRC / "cli.py" in source_files()
    assert "argparse" in imports_in(SRC / "cli.py"), "the walk reads the real file"
