"""The skill script must run anywhere Python 3.10+ is installed: no third-party imports."""
import ast
import sys

from conftest import SAMPLES, SCRIPT, run_cli


def test_imports_are_standard_library_only():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    assert names, "script imports nothing?"
    stdlib = set(sys.stdlib_module_names)
    assert names <= stdlib, names - stdlib


def test_runs_in_isolated_mode():
    p = run_cli(str(SAMPLES / "q3_report.md"), "--format", "json", flags=("-I",))
    assert p.returncode == 1 and '"mismatches": 10' in p.stdout


def test_help_works_in_isolated_mode():
    p = run_cli("--help", flags=("-I",))
    assert p.returncode == 0 and "usage:" in p.stdout


def test_no_network_or_process_modules():
    source = SCRIPT.read_text(encoding="utf-8")
    for banned in ("socket", "urllib", "http", "subprocess", "requests"):
        assert f"import {banned}" not in source
