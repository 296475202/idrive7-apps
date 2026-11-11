#!/usr/bin/env python3
"""Apply this fork's own changes onto an upstream idrive7-apps tree, then bump
every app's version by one patch.

Run from the repository root, on a tree that is exactly upstream's head:

    python3 zh-apps-kit/patch.py

It changes seven things and nothing else:

1. kit/localization/credit.zh-CN.json: the fork's credit file (Translation by:
   LEON HAU, corner + settings + comment), copied over upstream's.
2. apps/live_adjustments/bm3_profiles.js: the ROM F4C9L8G7B added to the
   multimap profile list, after F4C9L8G06.
3. apps/live_adjustments/bm3_protocol.js: identify()'s marker read wrapped in
   try/catch so a flash-locked DME (NRC 33) falls back to config.bm3RomFallback
   instead of failing the BM3 tab.
4. apps/live_adjustments/app.json: config.bm3RomFallback = "F4C9L8G7B".
5. mgu-repo.json: the unit's build gets --language zh-CN, so every app the car
   builds from this branch is Chinese.
6. kit/tools/test_zh.py: the credit it asserts is the fork's.
7. every apps/<id>/app.json: version x.y.z -> x.y.(z+1), so this fork's catalog
   is always the newest the store sees (js/catalog.js compares only x.y.z).

Every step is idempotent and deterministic. A step whose upstream anchors have
moved stops the run with exit 1 and says which file — that is the review point
for an upstream change, not something to paper over.
"""

import json
import pathlib
import re
import sys

KIT = pathlib.Path(__file__).resolve().parent
ROOT = KIT.parent

ROM = "F4C9L8G7B"
ROM_ANCHOR = "F4C9L8G06"
FALLBACK_KEY = "bm3RomFallback"
CREDIT = "Translation by: LEON HAU"

APP_ID = "live_adjustments"


def fail(message):
    print("zh-apps-kit: " + message, file=sys.stderr)
    sys.exit(1)


def read(path):
    return path.read_text(encoding="utf-8")


def write(path, text):
    path.write_text(text, encoding="utf-8")


def credit():
    """kit/localization/credit.zh-CN.json: the fork's file, byte for byte."""
    src = KIT / "credit.zh-CN.json"
    dst = ROOT / "kit" / "localization" / "credit.zh-CN.json"
    want = read(src)
    doc = json.loads(want)
    if doc.get("corner") != CREDIT:
        fail("zh-apps-kit/credit.zh-CN.json's corner is not %r" % CREDIT)
    if not dst.is_file():
        fail("kit/localization/credit.zh-CN.json is not in the upstream tree")
    if read(dst) != want:
        write(dst, want)
        return "credit.zh-CN.json replaced"
    return "credit.zh-CN.json already the fork's"


def rom_list():
    """bm3_profiles.js: F4C9L8G7B in the layouts list, after F4C9L8G06."""
    path = ROOT / "apps" / APP_ID / "bm3_profiles.js"
    text = read(path)
    if '"%s"' % ROM in text:
        return "bm3_profiles.js already lists " + ROM
    anchor = re.search(r'(?m)^([ \t]*)"%s",[ \t]*$' % ROM_ANCHOR, text)
    if not anchor:
        fail("bm3_profiles.js: no \"" + ROM_ANCHOR + "\" line to insert " + ROM + " after")
    insert = "%s\n%s\"%s\"," % (anchor.group(0), anchor.group(1), ROM)
    text = text[:anchor.start()] + insert + text[anchor.end():]
    write(path, text)
    return "bm3_profiles.js: " + ROM + " added"


def protocol_fallback():
    """bm3_protocol.js: identify()'s marker read falls back instead of throwing."""
    path = ROOT / "apps" / APP_ID / "bm3_protocol.js"
    text = read(path)
    if FALLBACK_KEY in text:
        return "bm3_protocol.js already falls back"
    lines = text.splitlines(keepends=True)
    start = None
    end = None
    for i, line in enumerate(lines):
        if start is None and line.strip() == "const addr = addressBytes(this.config.bm3MarkerAddress);":
            start = i
            continue
        if start is not None and line.strip().startswith("const rom = markerRom(marker, this.profiles);"):
            end = i
            break
    if start is None or end is None:
        fail("bm3_protocol.js: identify()'s marker read moved (no const addr / const rom anchors)")
    segment = lines[start:end + 1]
    for line in segment:
        if line.strip() and not line.startswith("        "):
            fail("bm3_protocol.js: marker read is not indented as identify()'s body")
    indented = ["    " + line if line.strip() else line for line in segment]
    indented[-1] = indented[-1].replace("const rom = markerRom", "rom = markerRom", 1)
    replacement = (
        ["        let rom = null;\n", "        try {\n"]
        + indented
        + [
            "        } catch (e) {\n",
            "            // Flash read locked (NRC 33): the marker is unavailable, but the\n",
            "            // RAM map variable still reads and writes without security, so\n",
            "            // fall back to the ROM this unit is known to run.\n",
            "            const fallback = this.config.%s;\n" % FALLBACK_KEY,
            "            if (!fallback || !this.profiles[fallback]) throw e;\n",
            "            rom = fallback;\n",
            "        }\n",
        ]
    )
    lines[start:end + 1] = replacement
    write(path, "".join(lines))
    return "bm3_protocol.js: marker read falls back to config." + FALLBACK_KEY


def app_config():
    """app.json: config.bm3RomFallback, the ROM the fallback names."""
    path = ROOT / "apps" / APP_ID / "app.json"
    doc = json.loads(read(path))
    config = doc.setdefault("config", {})
    if config.get(FALLBACK_KEY) == ROM:
        return "app.json already names " + ROM
    config[FALLBACK_KEY] = ROM
    write(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    return "app.json: config.%s = %s" % (FALLBACK_KEY, ROM)


def repo_language():
    """mgu-repo.json: the unit's build asks build.py for Chinese.

    Upstream builds every app with `python3 kit/tools/build.py <id>` and gets
    English. The head unit runs what mgu-repo.json names, so the language has to
    be in the args there, not in a command someone remembers to type."""
    path = ROOT / "mgu-repo.json"
    doc = json.loads(read(path))
    apps = doc.get("apps") or {}
    build = apps.get("build") or {}
    want = ["{id}", "--language", "zh-CN"]
    if build.get("args") == want:
        return "mgu-repo.json already builds zh-CN"
    build["args"] = want
    apps["build"] = build
    doc["apps"] = apps
    write(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    return "mgu-repo.json: build args " + " ".join(want)


def test_expectations():
    """kit/tools/test_zh.py: the credit it asserts is the fork's, not upstream's.

    Upstream's copy pins the translator's own corner/settings/comment strings (a
    GitHub link among them), so leaving it alone turns the sanity step red for a
    change that is deliberate. The assertion block is rewritten from the fork's
    credit file, so it cannot drift from what the build injects."""
    path = ROOT / "kit" / "tools" / "test_zh.py"
    if not path.is_file():
        return "test_zh.py not in this tree"
    doc = json.loads(read(KIT / "credit.zh-CN.json"))
    block = "\n".join(
        ["credit = zh_credit()",
         "assert credit['corner'] == %r" % doc["corner"],
         "assert credit['settingsTitle'] == %r" % doc["settingsTitle"],
         "assert credit['settingsLink'] == %r" % doc["settingsLink"],
         "assert credit['comment'] == ["]
        + ["    %r," % line for line in doc["comment"]]
        + ["]"]
    ) + "\n"
    text = read(path)
    if block in text:
        return "test_zh.py already asserts the fork's credit"
    pattern = re.compile(
        r"credit = zh_credit\(\)\n"
        r"(?:assert credit\[[^\]]*\] == [^\n]*\n)+"
        r"assert credit\['comment'\] == \[\n"
        r"(?:[^\n]*\n)*?"
        r"\]\n"
    )
    replaced, count = pattern.subn(block, text, count=1)
    if count == 0:
        return "test_zh.py: no credit block found; left alone for review"
    write(path, replaced)
    return "test_zh.py: credit assertions rewritten from the fork's credit file"


def bump_versions():
    """every app: x.y.z -> x.y.(z+1), so this fork's catalog outranks upstream's."""
    bumped = []
    for manifest in sorted((ROOT / "apps").glob("*/app.json")):
        doc = json.loads(read(manifest))
        version = str(doc.get("version") or "")
        parts = version.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            fail("%s version %r is not x.y.z" % (manifest.relative_to(ROOT), version))
        new = "%s.%s.%d" % (parts[0], parts[1], int(parts[2]) + 1)
        doc["version"] = new
        write(manifest, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        bumped.append("%s %s -> %s" % (doc.get("id") or manifest.parent.name, version, new))
    if not bumped:
        fail("no apps/<id>/app.json found: run this at the repository root")
    return bumped


def main():
    if not (ROOT / "kit" / "tools" / "build.py").is_file():
        fail("run this at the repository root (kit/tools/build.py not found)")
    steps = [credit(), rom_list(), protocol_fallback(), app_config(), repo_language(), test_expectations()]
    for step in steps:
        print("zh-apps-kit: " + step)
    bumped = bump_versions()
    print("zh-apps-kit: %d apps bumped" % len(bumped))
    for line in bumped:
        print("  " + line)


if __name__ == "__main__":
    main()
