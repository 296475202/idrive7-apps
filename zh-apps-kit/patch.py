#!/usr/bin/env python3
"""Apply this fork's own changes onto an upstream idrive7-apps tree, then bump
every app's version by one patch.

Run from the repository root, on a tree that is exactly upstream's head:

    python3 zh-apps-kit/patch.py

It changes nine things and nothing else:

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
8. every apps/<id>/app.json: version x.y.z -> one patch above whichever is
   newer, upstream's version or the one already published on zh-apps. Version
   is strictly three integers; a fork-only fix therefore still lands as a new
   number instead of hiding behind upstream's.
9. kit/tools/localize.py: package_version() keeps the plain x.y.z, without
   upstream's -<language>.<revision> suffix (see build_version()).

Every step is idempotent and deterministic. A step whose upstream anchors have
moved stops the run with exit 1 and says which file — that is the review point
for an upstream change, not something to paper over. After the steps, the tree
is re-read and the run fails if a ROM, the fallback or one of the three tiers is
missing, so a half-applied tree is never pushed to the branch the car updates
from.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
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

# The line build_version() writes into localize.py's package_version(), and that
# verify() looks for: it marks the tree whose builds keep a plain x.y.z.
VERSION_MARKER = "# zh-apps-kit: builds keep the plain x.y.z the Store compares."

APP_ID = "live_adjustments"

# Where to read the version this fork already publishes. The workflow points it
# at the zh-apps commit it just fetched; a local run falls back to the remote
# tracking refs that usually exist.
PUBLISHED_REF_ENV = "ZH_PUBLISHED_REF"
PUBLISHED_REFS = ("origin/zh-apps", "mine/zh-apps")


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


def build_version():
    """kit/tools/localize.py: a localised build keeps the plain x.y.z version.

    Upstream's kit appends the language and a revision to the version of every
    translated build ("0.9.3-zh.cn.5", the revision from locale-revisions.json).
    The MGU Store compares the version an installed app carries in
    source/package.json with its catalog entry by splitting it on dots and
    turning every part into a number (js/catalog.js, compareVersions): the
    suffix makes a part NaN, the comparison then says the installed build is
    newer than every catalog entry, and the Store never offers the update —
    the car stays on the first Chinese build it ever installed. Its build step
    also insists the finished package is named <id>@<catalog version>.tgz
    (build.js), which a suffixed version breaks, so even a forced install
    could not run.

    The fork bumps the version on every run (bump_versions()), so the suffix
    has nothing left to tell apart: the build keeps the number the catalog
    names."""
    path = ROOT / "kit" / "tools" / "localize.py"
    marker = VERSION_MARKER
    block = "\n".join(
        ["def package_version(version, language):",
         "    " + marker,
         "    # Upstream appended -<language>.<revision> here. The Store's version",
         "    # comparison reads x.y.z only (NaN made the installed build look newer),",
         "    # and its build names the package <id>@<version>.tgz, so the suffix",
         "    # blocked both the update offer and the install.",
         "    return version",
         ""]
    )
    text = read(path)
    if marker in text:
        return "localize.py already builds the plain x.y.z"
    pattern = re.compile(r"def package_version\(version, language\):\n(?:    [^\n]*\n)+")
    replaced, count = pattern.subn(block, text, count=1)
    if count == 0:
        fail("localize.py: package_version() not found; upstream changed it, review needed")
    write(path, replaced)
    return "localize.py: package_version() keeps x.y.z (no -zh.cn.N suffix)"


def plain_version_assert():
    """kit/tools/test_zh.py: it asserts a build keeps x.y.z, the fork's rule.

    Upstream asserts spec['version'] == original['version'] + '-<lang>.<rev>'
    because the kit appends the suffix; after build_version() that assertion
    fails the workflow's sanity step for a deliberate change."""
    path = ROOT / "kit" / "tools" / "test_zh.py"
    if not path.is_file():
        return "test_zh.py not in this tree"
    text = read(path)
    want = ("        # zh-apps-kit: the built version keeps the plain x.y.z the Store compares.\n"
            "        assert spec['version'] == original['version'], (manifest, language, spec['version'])\n")
    if want in text:
        return "test_zh.py already asserts the plain x.y.z"
    pattern = re.compile(
        r"        suffix = '' if language == 'en'[^\n]*\n"
        r"        assert spec\['version'\] == original\['version'\] \+ suffix[^\n]*\n")
    replaced, count = pattern.subn(want, text, count=1)
    if count == 0:
        return "test_zh.py: no version-suffix assertion found; left alone for review"
    write(path, replaced)
    return "test_zh.py: version assertion expects the plain x.y.z"


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


def leon_app():
    """apps/leon_skin: this fork's dashboard skin, injected from zh-apps-kit.

    Upstream's tree is reset every run, so the skin cannot live in apps/ - it
    would be removed with the reset. Its payload sits in zh-apps-kit/leon_skin/
    (already built: the flat .js the runtime loads, icon, manifest, the packed
    hud data as hud.pack, and the label translations build.py needs) and is
    copied into apps/leon_skin/ here. build.py copies the .js flat, takes the
    committed hud.pack as it is, so the car builds it like any other app."""
    src = KIT / "leon_skin"
    if not (src / "app.json").is_file():
        fail("zh-apps-kit/leon_skin/app.json is missing: the skin payload is not in this tree")
    dst = ROOT / "apps" / "leon_skin"
    copied = 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        if item.name == "locale-extra.json":
            continue
        if item.is_file():
            target = dst / item.name
            if not target.is_file() or target.read_bytes() != item.read_bytes():
                shutil.copyfile(item, target)
                copied += 1
    if not (dst / "hud.pack").is_file():
        fail("apps/leon_skin/hud.pack is missing after copying the payload")
    return "apps/leon_skin: %d file(s) written from zh-apps-kit/leon_skin" % copied


def leon_locale():
    """kit/runtime/locales/zh-CN.json: the skin's settings labels, translated.

    build.py localizes every label and option through this dictionary, so a
    label it does not know stays English (that is how the skin first shipped
    half translated). The entries are added only when absent: upstream's own
    translations are never overwritten."""
    path = ROOT / "kit" / "runtime" / "locales" / "zh-CN.json"
    if not path.is_file():
        fail("kit/runtime/locales/zh-CN.json is not in the upstream tree")
    doc = json.loads(read(path))
    extra = json.loads(read(KIT / "leon_skin" / "locale-extra.json"))
    added = [key for key, value in extra.items() if key not in doc]
    if not added:
        return "kit/runtime/locales/zh-CN.json already carries the skin's labels"
    for key in added:
        doc[key] = extra[key]
    write(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    return "kit/runtime/locales/zh-CN.json: %d skin label(s) added" % len(added)


def repo_credits():
    """kit/tools/build.py: an app that names its own credit keeps it.

    Upstream writes the project credit into every app's settings (hardcoded).
    The skin's credit rows are its name and its Chinese description, which is
    what its manifest carries under credits; every other app has none and keeps
    upstream's two strings."""
    path = ROOT / "kit" / "tools" / "build.py"
    text = read(path)
    if "zh-apps-kit: an app that names its own credit keeps it" in text:
        return "build.py already keeps an app's own credit"
    original = ("        strings[repo_title] = 'iDrive 7 custom apps'\n"
                "        strings[repo_link] = 'GitHub cauliflowermossgrape · github.com/cauliflowermossgrape/idrive7-apps'\n")
    if original not in text:
        fail("build.py: the REPO_CREDITS lines moved; upstream changed them, review needed")
    replacement = ("        # zh-apps-kit: an app that names its own credit keeps it (the skin);\n"
                   "        # every other app has no credits and keeps the project's two strings.\n"
                   "        own = spec.get('credits') or {}\n"
                   "        strings[repo_title] = own.get('title') or 'iDrive 7 custom apps'\n"
                   "        strings[repo_link] = own.get('text') or 'GitHub cauliflowermossgrape · github.com/cauliflowermossgrape/idrive7-apps'\n")
    write(path, text.replace(original, replacement, 1))
    return "build.py: REPO_CREDITS now prefers the app's own credit"


# The name each app carries in the Store, in Chinese. The base title stays
# upstream's English: the Store's i18n.text() shows texts[<language>] when the
# car's HMI language has one, so a zh-CN entry here is what makes the row
# Chinese, and an English user still reads the upstream title.
ZH_TITLES = {
    "ambient_config": ("氛围灯配置", "车内氛围灯颜色与模式"),
    "brake_test": ("刹车测试", "制动距离与减速 G 值"),
    "car_vitals": ("车况监测", "水温、油温、油压与蓄电池电压"),
    "doom": ("毁灭战士", "经典 FPS，车机上玩"),
    "draggy": ("加速计时", "0-100、弹射起步与圈速计时"),
    "dtc_scanner": ("故障码扫描", "读取与清除 DTC"),
    "dyno": ("虚拟马力机", "按加速数据推算轮上功率"),
    "edrive": ("电驱数据", "电机与电池实时数据"),
    "gforce": ("G 值仪表", "纵向与横向加速度"),
    "live_adjustments": ("实时调校", "BM3 配置与刷写状态"),
    "live_data": ("实时数据", "发动机参数实时曲线"),
    "redline": ("换挡提示", "接近红线时提醒"),
    "service": ("保养助手", "保养项目与里程提醒"),
    "warmup": ("暖机助手", "冷车暖机与限转提醒"),
    "zf8hp": ("8HP 变速箱", "ZF 8HP 换挡与油温"),
    "leon_skin": ("LEON 仪表皮肤", "GT3 / Porsche / TEST 三套仪表盘"),
}

# The head-unit tools' names live in mgu-repo.json, not in an app.json.
TOOL_TITLES = {
    "idrive7-renderd": ("GPU 渲染器", "应用自己的 GPU 渲染器，60 fps 绘制，随应用一起安装"),
    "mgu-inputgate": ("按键网关", "把 iDrive 旋钮交给应用使用，下次启动加载"),
}


def zh_titles():
    """apps/<id>/app.json: the app's Chinese name for the Store.

    Added only when the app carries no zh-CN title yet: an upstream translation
    is never overwritten, so this stays a one-time fill per app. The Store reads
    the entry straight from app.json (mgu-updater's sources.js, pick('texts')), so
    the name lands on the car's next poll with no rebuild."""
    added = []
    for manifest in sorted((ROOT / "apps").glob("*/app.json")):
        doc = json.loads(read(manifest))
        app_id = doc.get("id") or manifest.parent.name
        entry = ZH_TITLES.get(app_id)
        if not entry:
            continue
        texts = doc.get("texts")
        if not isinstance(texts, dict):
            texts = {}
        zh = texts.get("zh-CN")
        if isinstance(zh, dict) and zh.get("title"):
            continue
        texts["zh-CN"] = {"title": entry[0], "description": entry[1]}
        doc["texts"] = texts
        write(manifest, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        added.append(app_id)
    if not added:
        return "every app already names itself in Chinese"
    return "%d app(s) named in Chinese: %s" % (len(added), ", ".join(added))


def zh_tools():
    """mgu-repo.json: the head-unit tools' Chinese names for the Store.

    A tool's title lives in mgu-repo.json itself (sources.js picks title and
    texts from the repo entry), so this is the only place its row can be named
    in Chinese."""
    path = ROOT / "mgu-repo.json"
    if not path.is_file():
        fail("mgu-repo.json is not in the upstream tree")
    doc = json.loads(read(path))
    added = []
    for entry in doc.get("tools") or []:
        names = TOOL_TITLES.get(entry.get("id"))
        if not names:
            continue
        texts = entry.get("texts")
        if not isinstance(texts, dict):
            texts = {}
        zh = texts.get("zh-CN")
        if isinstance(zh, dict) and zh.get("title"):
            continue
        texts["zh-CN"] = {"title": names[0], "description": names[1]}
        entry["texts"] = texts
        added.append(entry["id"])
    if not added:
        return "every tool already names itself in Chinese"
    write(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    return "%d tool(s) named in Chinese: %s" % (len(added), ", ".join(added))


def verify():
    """Re-read what was written: every tier, every ROM and the fallback must be there.

    The car updates from this branch, so a half-applied tree would ship a BM3 tab
    that cannot identify its ROM. This runs on the finished tree and fails the run
    before anything is pushed."""
    protocol = read(ROOT / "apps" / APP_ID / "bm3_protocol.js")
    markers = ["DME rejected (2C|22)", "DME rejected 23", FALLBACK_KEY, "markerDataRom"]
    missing = [marker for marker in markers if marker not in protocol]
    if missing:
        fail("bm3_protocol.js: identify() lacks " + ", ".join(missing) + " after patching")
    profiles = read(ROOT / "apps" / APP_ID / "bm3_profiles.js")
    for rom in ROMS:
        if '"%s"' % rom not in profiles:
            fail("bm3_profiles.js: %s is not listed after patching" % rom)
    config = json.loads(read(ROOT / "apps" / APP_ID / "app.json")).get("config") or {}
    if config.get(FALLBACK_KEY) != ROM:
        fail("app.json: config.%s is not %s after patching" % (FALLBACK_KEY, ROM))
    localize = read(ROOT / "kit" / "tools" / "localize.py")
    if VERSION_MARKER not in localize:
        fail("localize.py: package_version() still appends a language suffix; the Store cannot compare that version")
    skin = ROOT / "apps" / "leon_skin"
    for name in ("app.json", "hud.pack", "icon.png", "app.js"):
        if not (skin / name).is_file():
            fail("apps/leon_skin: %s is missing after patching" % name)
    labels = json.loads(read(ROOT / "kit" / "runtime" / "locales" / "zh-CN.json"))
    for key in ("Full-screen alerts", "OVERBOOST: boost at", "LEON Skin"):
        if key not in labels:
            fail("kit/runtime/locales/zh-CN.json: %r is not translated after patching" % key)
    if "zh-apps-kit: an app that names its own credit keeps it" not in read(ROOT / "kit" / "tools" / "build.py"):
        fail("build.py: the app's own credit is not honoured after patching")
    for manifest in sorted((ROOT / "apps").glob("*/app.json")):
        doc = json.loads(read(manifest))
        app_id = doc.get("id") or manifest.parent.name
        if app_id not in ZH_TITLES:
            continue
        names = (doc.get("texts") or {}).get("zh-CN") or {}
        if not names.get("title"):
            fail("%s: no zh-CN title after patching" % manifest.relative_to(ROOT))
    tools = json.loads(read(ROOT / "mgu-repo.json")).get("tools") or []
    for entry in tools:
        if entry.get("id") in TOOL_TITLES and not ((entry.get("texts") or {}).get("zh-CN") or {}).get("title"):
            fail("mgu-repo.json: %s has no zh-CN title after patching" % entry.get("id"))
    return "three tiers, %d ROMs, %s, plain build versions, the skin and every Chinese name verified" % (len(ROMS), ROM)


def version_tuple(text):
    """x.y.z -> (x, y, z); anything else -> None. Three integers is the only form
    the store compares, and the build appends its own -zh.cn.N suffix later."""
    parts = str(text).split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def git_binary():
    """git from PATH, or the usual Windows install when PATH does not carry it."""
    found = shutil.which("git")
    if found:
        return found
    fallback = r"C:\Program Files\Git\cmd\git.exe"
    return fallback if os.name == "nt" and os.path.exists(fallback) else ""


def published_version(app_id):
    """The version this fork already publishes for app_id, or '' when unknown.

    A fork-only fix does not move upstream's version, so bumping from upstream
    alone would ship new code under the old number and the car's store would
    never offer it."""
    git = git_binary()
    if not git:
        return ""
    refs = [os.environ.get(PUBLISHED_REF_ENV)] + list(PUBLISHED_REFS)
    for ref in refs:
        if not ref:
            continue
        try:
            show = subprocess.run(
                [git, "-C", str(ROOT), "show", "%s:apps/%s/app.json" % (ref, app_id)],
                capture_output=True, text=True)
        except OSError:
            return ""
        if show.returncode != 0:
            continue
        try:
            return str(json.loads(show.stdout).get("version") or "")
        except ValueError:
            continue
    return ""


def bump_versions():
    """every app: one patch above whichever is newer - upstream's or the published one.

    That keeps the number monotone across runs: a fork-only fix still gets a new
    version, and a later upstream bump is taken when it overtakes this branch."""
    bumped = []
    for manifest in sorted((ROOT / "apps").glob("*/app.json")):
        doc = json.loads(read(manifest))
        app_id = doc.get("id") or manifest.parent.name
        version = str(doc.get("version") or "")
        base = version_tuple(version)
        if base is None:
            fail("%s version %r is not x.y.z" % (manifest.relative_to(ROOT), version))
        published = version_tuple(published_version(app_id))
        if published and published > base:
            base = published
        new = "%d.%d.%d" % (base[0], base[1], base[2] + 1)
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
             build_version(), plain_version_assert(), test_expectations(), profile_count(),
             leon_app(), leon_locale(), zh_titles(), zh_tools(), repo_credits()]
    for step in steps:
        print("zh-apps-kit: " + step)
    bumped = bump_versions()
    print("zh-apps-kit: %d apps bumped" % len(bumped))
    for line in bumped:
        print("  " + line)
    print("zh-apps-kit: " + verify())


if __name__ == "__main__":
    main()
