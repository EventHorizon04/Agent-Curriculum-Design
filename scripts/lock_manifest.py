"""Print the experiment lock manifest: what the system was, when it was locked.

The research plan asks for a record of model name and version, temperature,
prompt files and code constants every time the system is locked. This gathers
them from the running code, so the record cannot drift from what runs.

    uv run python scripts/lock_manifest.py          # Markdown on stdout
    uv run python scripts/lock_manifest.py --json   # JSON on stdout

The repo is public and `.env` holds credentials, so the Settings section is
deny-by-default: a field is printed only when its name is not on the deny list
and its value is a short bool/int/float/str.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from curriculum_agent.config import SLOTS, Settings

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "curriculum_agent"

_DENY_NAME_PARTS = (
    "key",
    "secret",
    "password",
    "token",
    "dsn",
    "url",
    "host",
    "user",
    "bucket",
    "endpoint",
)
_MAX_STR_LEN = 80

_CONSTANT_MODULE_GLOBS = (
    "stages/need_dedup.py",
    "stages/need_grouping.py",
    "stages/need_merge.py",
    "stages/single_*.py",
    "stages/smart_*.py",
    "stages/plo_review*.py",
)
_CAP_NAME = re.compile(r"(MAX_TOKENS|MAX_REASONING_TOKENS|REASONING_MAX_TOKENS)$")


def _is_allowed_name(name: str) -> bool:
    lowered = name.lower()
    if lowered.endswith("max_tokens"):
        return True
    return not any(part in lowered for part in _DENY_NAME_PARTS)


def _is_allowed_value(value: Any) -> bool:
    if isinstance(value, bool | int | float):
        return True
    if isinstance(value, str):
        return len(value) <= _MAX_STR_LEN and "://" not in value
    return False


def safe_settings(settings: Settings) -> dict[str, Any]:
    """Settings fields that are safe to print. Deny by default."""
    out: dict[str, Any] = {}
    for name in type(settings).model_fields:
        if not _is_allowed_name(name):
            continue
        value = getattr(settings, name)
        if _is_allowed_value(value):
            out[name] = value
    return out


def _run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def git_info() -> dict[str, Any]:
    _, head = _run(["git", "rev-parse", "HEAD"])
    _, branch = _run(["git", "branch", "--show-current"])
    _, porcelain = _run(["git", "status", "--porcelain"])
    return {"commit": head, "branch": branch, "dirty": bool(porcelain), "status": porcelain}


def slot_info(settings: Settings) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slot in SLOTS:
        provider = getattr(settings, slot.provider_field)
        model = getattr(settings, slot.model_field)
        rows.append(
            {
                "slot": slot.name,
                "provider": provider,
                "model": model,
                "disabled": not provider,
                "disableable": slot.disableable,
            }
        )
    return rows


def _module_level_names(path: Path, pattern: re.Pattern[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and pattern.search(target.id):
                names.append(target.id)
    return names


def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    return ".".join(rel.parts)


def token_caps() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    paths = sorted((SRC / "stages").glob("*.py")) + [SRC / "llm.py"]
    for path in paths:
        names = _module_level_names(path, _CAP_NAME)
        if not names:
            continue
        module = importlib.import_module(_module_name(path))
        for name in names:
            value = getattr(module, name, None)
            if isinstance(value, int) and not isinstance(value, bool):
                rows.append({"module": _module_name(path), "name": name, "value": value})
    return rows


def temperature_sites() -> list[dict[str, Any]]:
    """Every `temperature=` / `temperature:` in the source, with its line."""
    sites: list[dict[str, Any]] = []
    pattern = re.compile(r"\btemperature\s*[=:]\s*([^,)\s]+)")
    for path in sorted(SRC.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            match = pattern.search(line)
            if match:
                sites.append(
                    {
                        "file": path.relative_to(ROOT).as_posix(),
                        "line": lineno,
                        "value": match.group(1),
                    }
                )
    return sites


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_files() -> list[dict[str, str]]:
    root = SRC / "prompts"
    files = sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return [{"path": p.relative_to(ROOT).as_posix(), "sha256": _sha256(p)} for p in files]


def prompt_inventory() -> dict[str, Any]:
    inventory = ROOT / "docs" / "prompt-inventory.md"
    code, output = _run([sys.executable, "scripts/dump_prompts.py", "--check"])
    return {
        "path": "docs/prompt-inventory.md",
        "sha256": _sha256(inventory) if inventory.exists() else None,
        "check": "current" if code == 0 else "STALE",
        "check_output": output[-300:],
    }


def code_constants() -> list[dict[str, Any]]:
    pattern = re.compile(r"^_*[A-Z][A-Z0-9_]*$")
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for glob in _CONSTANT_MODULE_GLOBS:
        for path in sorted(SRC.glob(glob)):
            if path in seen:
                continue
            seen.add(path)
            module = importlib.import_module(_module_name(path))
            for name in _module_level_names(path, pattern):
                value = getattr(module, name, None)
                if _is_allowed_value(value):
                    rows.append({"module": _module_name(path), "name": name, "value": value})
    return rows


def build_manifest(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings if settings is not None else Settings()
    return {
        "git": git_info(),
        "slots": slot_info(settings),
        "token_caps": token_caps(),
        "temperature": temperature_sites(),
        "prompts": prompt_files(),
        "prompt_inventory": prompt_inventory(),
        "constants": code_constants(),
        "settings": safe_settings(settings),
    }


def _md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def render_markdown(m: dict[str, Any]) -> str:
    git = m["git"]
    out: list[str] = ["# Lock manifest", ""]
    if git["dirty"]:
        out += ["**WARNING: working tree is DIRTY. This lock does not match the commit.**", ""]
    out += [
        "## Git",
        f"- commit: `{git['commit']}`",
        f"- branch: `{git['branch']}`",
        f"- working tree: {'DIRTY' if git['dirty'] else 'clean'}",
    ]
    if git["dirty"]:
        out += ["", "```", git["status"], "```"]
    out += ["", "## LLM slots (resolved)"]
    out += _md_table(
        ["slot", "provider", "model", "disabled"],
        [
            [
                s["slot"],
                s["provider"] or "(empty)",
                s["model"] or "-",
                "yes" if s["disabled"] else "no",
            ]
            for s in m["slots"]
        ],
    )
    out += ["", "## Token caps (module constants)"]
    out += _md_table(
        ["module", "name", "value"], [[c["module"], c["name"], c["value"]] for c in m["token_caps"]]
    )
    out += ["", "## Temperature"]
    if m["temperature"]:
        out += _md_table(
            ["file", "line", "value"],
            [[t["file"], t["line"], t["value"]] for t in m["temperature"]],
        )
        out += ["", "Calls not listed pass no temperature (provider default)."]
    else:
        out += ["not set in code (provider default)"]
    out += ["", "## Prompt files (sha256)"]
    out += _md_table(["path", "sha256"], [[p["path"], p["sha256"]] for p in m["prompts"]])
    inv = m["prompt_inventory"]
    out += [
        "",
        f"- `{inv['path']}` sha256: `{inv['sha256']}`",
        f"- `dump_prompts.py --check`: {inv['check']}",
        "",
        "## Code constants",
    ]
    out += _md_table(
        ["module", "name", "value"], [[c["module"], c["name"], c["value"]] for c in m["constants"]]
    )
    out += ["", "## Settings knobs"]
    out += _md_table(["field", "value"], [[k, v] for k, v in sorted(m["settings"].items())])
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the experiment lock manifest.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    args = parser.parse_args()
    # Thai values appear in Settings; a cp1252 console would crash on them.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    manifest = build_manifest()
    if args.json:
        sys.stdout.write(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n")
    else:
        sys.stdout.write(render_markdown(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
