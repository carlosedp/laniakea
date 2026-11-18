"""Entry points for the web patcher (web/index.html runs this under Pyodide).

Same patch files and build code as `laniakea patcher build`; only the assembler differs
(tools/xtasm.py instead of GNU binutils, byte-identical, see tests/test_xtasm.py).

    catalog()                    -> JSON: patches, options, presets, known official images
    identify(path)               -> JSON: {"version": "3.7"} or {"error": "..."}
    build(path, selection, out)  -> JSON: {"name", "log", "version", "tags"} or {"error": "..."}
        selection = JSON list of {"name": patch, "values": {option: value}}
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LANIAKEA_ASM", "py")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import patcher  # noqa: E402
import symbols  # noqa: E402
from patchlib import Firmware, PatchError  # noqa: E402

# shown in the web UI (diagnostic patches and `quiet` stay CLI-only)
WEB_PATCHES = ["banks", "usability", "cv_to_y", "led_dedupe", "led_menus", "chords", "quantizer"]


def _spec_values(spec: str) -> tuple[str, dict]:
    name, _, opts = spec.partition(":")
    return name, dict(kv.split("=", 1) for kv in filter(None, opts.split(",")))


def catalog() -> str:
    patches = []
    for name in WEB_PATCHES:
        mod = patcher.load_patch(name)
        defaults = _spec_values(f"{name}:{patcher.DEFAULTS[name]}")[1] if name in patcher.DEFAULTS else {}
        patches.append({
            "name": name,
            "description": mod.DESCRIPTION,
            "doc": (mod.__doc__ or "").strip(),
            "targets": mod.TARGETS,
            "options": [{"key": k, "default": defaults.get(k, d), "type": type(d).__name__ if d is not None else "str",
                         "help": h, "choices": getattr(mod, "CHOICES", {}).get(k),
                         "range": getattr(mod, "RANGES", {}).get(k)}
                        for k, (d, h) in mod.OPTIONS.items()],
            "library": list(getattr(mod, "LIBRARY", {})),       # quantizer scale names
        })
    presets = {k: [dict(zip(("name", "values"), _spec_values(s))) for s in v]
               for k, v in patcher.PRESETS.items() if k == "recommended"}
    known = {sha: ver for sha, (ver, _sym) in symbols.BY_SHA256.items()}
    return json.dumps({"patches": patches, "presets": presets, "known": known})


def identify(path: str) -> str:
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if sha in symbols.BY_SHA256:
        return json.dumps({"version": symbols.BY_SHA256[sha][0], "sha256": sha})
    return json.dumps({"error": "not an official image this patcher knows", "sha256": sha,
                       "supported": sorted({v for v, _s in symbols.BY_SHA256.values()})})


def build(path: str, selection: str, out: str) -> str:
    log: list[str] = []
    try:
        fw = Firmware(path)
        parsed = []
        items = {}
        for item in json.loads(selection):          # a patch named twice: the last one wins (as the CLI)
            items.pop(item["name"], None)
            items[item["name"]] = item
        for item in items.values():
            name = item["name"]
            mod = patcher.load_patch(name)
            values = {k: d for k, (d, _h) in mod.OPTIONS.items()}
            for k, v in (item.get("values") or {}).items():
                if k not in mod.OPTIONS:
                    raise SystemExit(f"{name}: unknown option {k!r}")
                values[k] = patcher.parse_value(str(v), mod.OPTIONS[k][0])
            missing = [k for k, v in values.items() if v is None or v == ""]
            if missing:
                raise SystemExit(f"{name}: option(s) required: {', '.join(missing)}")
            parsed.append((name, mod, values))
        name = patcher.apply_all(fw, patcher.order(parsed), log=log.append)
        fw.save(Path(out))
        log.extend("    " + l for l in fw.log)
        return json.dumps({"name": name, "log": log, "version": fw.version, "tags": fw.tags})
    except (SystemExit, PatchError, ValueError) as e:
        return json.dumps({"error": str(e), "log": log})
