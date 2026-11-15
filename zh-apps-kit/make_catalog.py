#!/usr/bin/env python3
"""Turn this fork's built Chinese apps into a store catalog (docs/PUBLISHING.md, section 2).

Run at the repository root after `python3 kit/tools/build.py --language zh-CN`:

    python3 zh-apps-kit/make_catalog.py --out publish

The build writes dist/<id>@<x.y.z>-zh.cn.N.tgz. A catalog entry must name
exactly `<id>@<x.y.z>.tgz` (js/catalog.js rejects anything else), so each
built package is copied to that name and its sha256 and size recorded. The
result is publish/catalog.json plus one .tgz per app, which is what the
`zh-apps` branch of this fork publishes; the car reads it as an https source:

    {"id": "idrive7-apps-zh", "type": "https",
     "url": "https://raw.githubusercontent.com/<owner>/idrive7-apps-cn/zh-apps/catalog.json"}
"""

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

BUILT = "^[A-Za-z0-9_.-]+@[0-9]+\\.[0-9]+\\.[0-9]+-zh\\.cn\\.[0-9]+\\.tgz$"


def fail(message):
    print("zh-apps-kit: " + message, file=sys.stderr)
    sys.exit(1)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="publish", help="folder for catalog.json and the packages")
    parser.add_argument("--dist", default="dist", help="the build's output folder")
    args = parser.parse_args()

    dist = ROOT / args.dist
    out = ROOT / args.out
    if not dist.is_dir():
        fail("%s not found: build the apps first" % args.dist)
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.tgz"):
        stale.unlink()

    pattern = re.compile(BUILT)
    components = []
    for package in sorted(dist.glob("*.tgz")):
        if not pattern.match(package.name):
            continue
        ident, built = package.name[:-len(".tgz")].split("@", 1)
        version = built.split("-", 1)[0]
        manifest = ROOT / "apps" / ident / "app.json"
        if not manifest.is_file():
            fail("no apps/%s/app.json for %s" % (ident, package.name))
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        name = "%s@%s.tgz" % (ident, version)
        target = out / name
        shutil.copyfile(package, target)
        entry = {
            "id": ident,
            "kind": "app",
            "version": version,
            "title": doc.get("title") or doc.get("name") or ident,
            "artifact": {
                "name": name,
                "size": target.stat().st_size,
                "sha256": sha256_of(target),
                "url": name,
            },
            "uninstallable": True,
        }
        for key in ("description", "requires", "mguHmi"):
            if doc.get(key):
                entry[key] = doc[key]
        components.append(entry)

    if not components:
        fail("no <id>@<x.y.z>-zh.cn.N.tgz in %s: build with --language zh-CN" % args.dist)

    catalog = {"schema": 2, "components": components}
    (out / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    total = sum(c["artifact"]["size"] for c in components)
    print("zh-apps-kit: %d apps, %.1f MiB -> %s/catalog.json" % (len(components), total / 1048576.0, args.out))
    for c in components:
        print("  %-18s %-8s %s" % (c["id"], c["version"], c["artifact"]["name"]))


if __name__ == "__main__":
    main()
