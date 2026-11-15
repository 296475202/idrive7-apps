# zh-apps-kit

The Chinese layer of `296475202/idrive7-apps`, a fork of
`cauliflowermossgrape/idrive7-apps`.

The fork's default branch holds only this folder and
`.github/workflows/sync-apps-zh.yml`. Every run of that workflow throws away the
branch it checked out, fetches upstream's `main`, applies `patch.py` from here
and force-pushes the result as **`zh-apps`**. That branch is source only: BMW's
`oap-sdk` cannot be committed or shipped in a package, so the head unit builds
every app from the source itself — the same publishing model as upstream
(`docs/PUBLISHING.md`).

## The source to add on the car

```json
{"id": "idrive7-apps-zh", "type": "github",
 "repo": "296475202/idrive7-apps", "channel": "branch:zh-apps"}
```

MGU Store reads `mgu-repo.json` from the tip of that branch, so each app the car
installs is built on the unit, in Chinese, with the BM3 fallback in place.

## What `patch.py` changes

1. `kit/localization/credit.zh-CN.json` — the fork's credit file
   (`Translation by: LEON HAU`).
2. `apps/live_adjustments/bm3_profiles.js` — `F4C9L8G7B` added to the multimap
   ROM list.
3. `apps/live_adjustments/bm3_protocol.js` — `identify()`'s marker read wrapped
   in try/catch, so a flash-locked DME (NRC 33) falls back to
   `config.bm3RomFallback` instead of failing the KM3 tab.
4. `apps/live_adjustments/app.json` — `config.bm3RomFallback = "F4C9L8G7B"`.
5. `mgu-repo.json` — the unit's build gets `--language zh-CN`.
6. `kit/tools/test_zh.py` — its credit assertions are rewritten from the credit
   file, so the workflow's sanity step stays honest.
7. Every `apps/<id>/app.json` — `x.y.z` → `x.y.(z+1)`, so this fork's version is
   always one patch above upstream and the store never sees it as older
   (`js/catalog.js` compares only the first three parts).

Every step is idempotent except the version bump, which is deliberately one-shot:
each run starts from a clean upstream tree, so one run means one bump.

## Run it

Actions → *sync upstream and publish zh apps* → Run workflow. The schedule is
`41 3 * * *` UTC. An unchanged tree is not pushed, so the car only sees a new
version when upstream actually changed.

## Locally

`make_catalog.py` is not used by the workflow. It packages `dist/<id>@*.mgu`
into `<id>@<x.y.z>.tgz` plus a schema-2 `catalog.json`, for the fallback where
the car reads the fork as a `file` or `https` source instead of a branch.
