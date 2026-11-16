"""Shared helpers: load the single-file script as a module and run it as a subprocess."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "tallycheck" / "scripts" / "tallycheck.py"
SAMPLES = ROOT / "samples"


def _load():
    spec = importlib.util.spec_from_file_location("tallycheck_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["tallycheck_script"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def tc():
    return _load()


def clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("TALLYCHECK_LANG", "LC_ALL", "LC_MESSAGES", "LANG")}
    env.update(extra)
    return env


def run_cli(*args: str, env: dict | None = None, cwd: Path = ROOT, flags: tuple = ()):
    return subprocess.run([sys.executable, *flags, str(SCRIPT), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env if env is not None else clean_env(),
                          cwd=str(cwd), timeout=60)


@pytest.fixture()
def cli():
    return run_cli


@pytest.fixture()
def check(tc):
    """check(markdown, lang='en', source=None) -> list of findings (dicts)."""
    def _check(text: str, lang: str = "en", source=None):
        ctx = tc.Ctx(lang, source)
        ctx.file = "t.md"
        tc.check_text(ctx, text)
        return ctx
    return _check


def findings_by_line(ctx, check_code: str | None = None) -> dict:
    out = {}
    for f in ctx.findings:
        if check_code is None or f["check"] == check_code:
            out[f["line"]] = f
    return out


def load_json(proc) -> dict:
    return json.loads(proc.stdout)
