# Releasing a new version

Friends get GravelMaps from GitHub Releases, and the app offers each new release to them itself.
A release is built by GitHub Actions (`.github/workflows/release.yml`) when a version tag is pushed.

1. Bump `__version__` in `gravelmaps/__init__.py`, e.g. `0.2.0` → `0.3.0`.
2. Commit, tag the same version, push both:

   ```bash
   git commit -am "Release 0.3.0"
   git tag v0.3.0
   git push && git push origin v0.3.0
   ```

3. In about 15 minutes the [Releases page](https://github.com/luke-villaluz/GravelMaps/releases) has
   GravelMaps 0.3.0 with `GravelMaps-arm64.dmg` and `GravelMaps-x86_64.dmg`. Open copies of the
   app show "New version available" the next time they're online.

The workflow stops if the tag and `__version__` disagree, or if the tests fail. The install
instructions at the top of each release come from `packaging/release-notes.md`; the list of
changes under them is generated from the commits.

## Building the app locally

```bash
.venv/bin/pip install -r requirements-build.txt
PYTHON=.venv/bin/python packaging/build_app.sh --dmg   # dist/GravelMaps.app and dist/GravelMaps-<arch>.dmg
```

It's signed ad hoc (no Apple Developer account), so the first open needs System Settings →
Privacy & Security → Open Anyway, like the downloaded one. `brew install create-dmg` gives the DMG
its drag-to-Applications layout; without it the DMG is plain but works the same.

`packaging/make_icon.py` redraws the icon.
