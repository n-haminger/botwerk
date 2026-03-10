# Botwerk Roadmap

Botwerk is a fork of [ductor](https://github.com/PleasePrompto/ductor) (v0.13.0),
maintained independently at [n-haminger/botwerk](https://github.com/n-haminger/botwerk).

## Completed

### Fork Setup (Phase 1-3)
- [x] Create independent GitHub repo `n-haminger/botwerk`
- [x] Rebase on upstream v0.13.0 + consolidate all custom feature branches
- [x] Full rename: `ductor` -> `botwerk` (package, imports, env vars, paths, branding, docs)
- [x] Preserve upstream as read-only remote for selective cherry-picks
- [x] Update LICENSE with dual copyright (PleasePrompto original + n-haminger fork)

### Integrated Custom Features (from ductor fork)
- [x] Matrix/Element transport (full implementation with media, streaming, buttons)
- [x] Linux user isolation for sub-agent CLI subprocesses
- [x] Interagent API port configurability
- [x] `!interrupt` command for immediate CLI interruption
- [x] `update_check` config toggle
- [x] CLI timeout session preservation
- [x] Transport-neutral refactoring and setup parity

## In Progress

### Phase 4: Update System (PyPI -> GitHub Releases)
- [ ] Implement `check_github_releases()` in `botwerk_bot/infra/version.py`
- [ ] Update `UpdateObserver` to poll GitHub Releases API instead of PyPI
- [ ] Change upgrade command to install from GitHub Release assets (`.whl`)
- [ ] Update `/upgrade` Telegram command and `botwerk upgrade` CLI
- [ ] Test end-to-end upgrade flow

### Phase 5: CI/CD
- [ ] Add `test.yml` workflow (pytest + ruff on push/PR to main)
- [ ] Add `release.yml` workflow (build + GitHub Release on `v*` tags)
- [ ] Set up branch protection rules on main

### Phase 6: Branding
- [ ] Create botwerk logo / bot avatar
- [x] Update README: remove ductor images, PyPI badges, add fork description, GitHub install
- [x] Delete obsolete ductor-branded images (logo_text.png, welcome.png, screenshots)
- [ ] Update bot welcome screens and onboarding text

## Planned

### Phase 7: First Release
- [ ] Bump version to 1.0.0
- [ ] Tag `v1.0.0` and verify release workflow
- [ ] Test clean install from GitHub Release

### Upstream Sync Strategy
- Upstream (`PleasePrompto/ductor`) is kept as a read-only remote
- Cherry-pick useful upstream changes as needed: `git cherry-pick <hash>`
- No automatic merging — all upstream changes are reviewed manually

### Future Features
- [ ] Discord transport (WIP in upstream, partially ported)
- [ ] Enhanced multi-agent coordination
- [ ] Improved background task delegation
- [ ] Web dashboard for agent monitoring

---

*Last updated: 2026-03-10*
