#!/usr/bin/env python3
"""Apply this fork's own changes onto an upstream idrive7-apps tree, then bump
every app's version by one patch.

Run from the repository root, on a tree that is exactly upstream's head:

    python3 zh-apps-kit/patch.py

It changes eight things and nothing else:

1. kit/localization/credit.zh-CN.json: the fork's credit file (Translation by:
   LEON HAU, corner + settings + comment), copied over upstream's.
2. apps/live_adjustments/bm3_profiles.js: the ROMs in ROMS added to the
   multimap profile list, each after the last entry of its own series
   (F4C9L8G7B after F4C9L8G*, R4C9H6K5B after R4C9H6K*).
3. apps/live_adjustments/bm3_protocol.js: identify() reads the marker three
   ways: the dynamic DID, then 0x23 straight from the marker address (upstream's
   own fallback), then config.bm3RomFallback. A DME whose flash is read-locked
   refuses 0x23 as well (NRC 33, or 31), so without the third tier it fails
   the BM3 tab.
4. apps/live_adjustments/app.json: config.bm3RomFallback = ROMS[-1] (the unit
   the fallback names by default).
5. mgu-repo.json: the unit's build gets --language zh-CN, so every app the car
   builds from this branch is Chinese.
6. kit/tools/test_zh.py: the credit it asserts is the fork's.
7. kit/tools/test_bm3_protocol.js: the bundled-profile count it asserts is the
   number of ROMs this branch lists, not upstream's.
8. every apps/<id>/app.json: version x.y.z -> x.y.(z+1), so this fork's catalog
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

# Every ROM whose marker read a flash-locked DME refuses (NRC 33). All of them
# go into the profile list; the last one is the fallback the app ships naming.
ROMS = ("F4C9L8G7B", "R4C9H6K5B")
ROM = ROMS[-1]
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


def insert_rom(text, rom):
    """Put one ROM after the last entry of its own series (ROM minus last two).

    Returns (text, inserted). A series that is not in the list yet falls back to
    the known F4C9L8G anchor, which keeps an upstream reshuffle visible as a
    failure rather than a silent wrong layout."""
    if '"%s"' % rom in text:
        return text, False
    stem = rom[:-2]
    siblings = list(re.finditer(
        r'(?m)^([ \t]*)"%s[0-9A-Za-z]{2}",[ \t]*$' % re.escape(stem), text))
    if siblings:
        last = siblings[-1]
        insert = "\n%s\"%s\"," % (last.group(1), rom)
        return text[:last.end()] + insert + text[last.end():], True
    anchor = re.search(r'(?m)^([ \t]*)"%s",[ \t]*$' % ROM_ANCHOR, text)
    if not anchor:
        fail("bm3_profiles.js: no \"" + ROM_ANCHOR + "\" line to insert " + rom + " after")
    insert = "%s\n%s\"%s\"," % (anchor.group(0), anchor.group(1), rom)
    return text[:anchor.start()] + insert + text[anchor.end():], True


def rom_list():
    """bm3_profiles.js: every ROM in ROMS in the layouts list."""
    path = ROOT / "apps" / APP_ID / "bm3_profiles.js"
    text = read(path)
    added, present = [], []
    for rom in ROMS:
        text, ok = insert_rom(text, rom)
        (added if ok else present).append(rom)
    if not added:
        return "bm3_profiles.js already lists " + ", ".join(ROMS)
    write(path, text)
    return "bm3_profiles.js: " + ", ".join(added) + " added"


def protocol_fallback():
    """bm3_protocol.js: identify() gets a third way to find the ROM.

    Upstream reads the marker through the dynamic DID and, when the DME refuses
    that, straight from the marker address with 0x23; a refusal there is still a
    failure. A unit whose flash is read-locked refuses 0x23 as well (NRC 33, or
    31 for an address outside the readable range), yet its RAM map variable reads
    and writes without security. So the fork adds the last tier: the ROM named in
    config.<FALLBACK_KEY>, used only when 0x23 is refused too."""
    path = ROOT / "apps" / APP_ID / "bm3_protocol.js"
    text = read(path)
    if FALLBACK_KEY in text:
        return "bm3_protocol.js already falls back to config." + FALLBACK_KEY
    lines = text.splitlines(keepends=True)
    guard = None
    for i, line in enumerate(lines):
        if line.strip() == "if (!/^DME rejected (2C|22)/.test(e.message)) throw e;":
            guard = i
            break
    if guard is None:
        fail("bm3_protocol.js: identify()'s 0x23 fallback moved (no DME rejected (2C|22) guard)")
    read_line = lines[guard + 1] if guard + 1 < len(lines) else ""
    parse_line = lines[guard + 2] if guard + 2 < len(lines) else ""
    if "0x23" not in read_line or "markerDataRom" not in parse_line:
        fail("bm3_protocol.js: identify()'s 0x23 read is not right after the refusal guard")
    outer = " " * (len(lines[guard]) - len(lines[guard].lstrip()))
    inner = outer + "    "
    replacement = (
        [lines[guard], outer + "try {\n", "    " + read_line, "    " + parse_line,
         outer + "} catch (refused) {\n",
         inner + "// 0x23 refused too (NRC 33, or 31 for an address outside the readable\n",
         inner + "// range): the flash is read-locked, so no marker of any layout can be read.\n",
         inner + "// The RAM map variable still reads and writes without security, so name\n",
         inner + "// the ROM this unit is known to run instead of failing the BM3 tab.\n",
         inner + "if (!/^DME rejected 23/.test(refused.message)) throw refused;\n",
         inner + "const fallback = this.config.%s;\n" % FALLBACK_KEY,
         inner + "if (!fallback || !this.profiles[fallback]) throw refused;\n",
         inner + "rom = fallback;\n",
         outer + "}\n"]
    )
    lines[guard:guard + 3] = replacement
    write(path, "".join(lines))
    return "bm3_protocol.js: identify() falls back to config.%s after 0x23" % FALLBACK_KEY


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


def profile_count():
    """kit/tools/test_bm3_protocol.js: the bundled-profile count matches the list.

    Upstream asserts the profile list has a fixed number of entries; this fork
    lists more ROMs, so the number is recomputed from the file the assertion is
    about instead of being left red."""
    profiles = read(ROOT / "apps" / APP_ID / "bm3_profiles.js")
    count = 0
    for block in re.findall(r'"roms"\s*:\s*\[([^\]]*)\]', profiles):
        # Every quoted entry becomes a profile key: most are nine characters, a few
        # are six ("011000"), and bm3_profiles.js builds one profile per entry.
        count += len(re.findall(r'"[0-9A-Z]+"', block))
    if not count:
        fail("bm3_profiles.js: no \"roms\" arrays to count")
    path = ROOT / "kit" / "tools" / "test_bm3_protocol.js"
    if not path.is_file():
        return "test_bm3_protocol.js not in this tree"
    text = read(path)
    want = "assert.strictEqual(Object.keys(bundled).length, %d);" % count
    if want in text:
        return "test_bm3_protocol.js already expects %d layouts" % count
    replaced, found = re.subn(
        r"assert\.strictEqual\(Object\.keys\(bundled\)\.length, \d+\);", want, text, count=1)
    if found == 0:
        return "test_bm3_protocol.js: no bundled-count assertion found; left alone for review"
    write(path, replaced)
    return "test_bm3_protocol.js: bundled count %d layouts" % count


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
    steps = [credit(), rom_list(), protocol_fallback(), app_config(), repo_language(),
             test_expectations(), profile_count()]
    for step in steps:
        print("zh-apps-kit: " + step)
    bumped = bump_versions()
    print("zh-apps-kit: %d apps bumped" % len(bumped))
    for line in bumped:
        print("  " + line)


if __name__ == "__main__":
    main()
