# Releasing MCO

MCO is published through npm only. Do not publish to PyPI. The normal path is a
GitHub Release from the matching version tag; the publish workflow gates and
publishes that exact tag. The manual path remains available when GitHub Actions
cannot publish because `NPM_TOKEN` is missing or npm requires web-based 2FA.

## Preview package (CI artifact)

Pull requests run the **Preview package** GitHub Actions workflow
(`.github/workflows/preview-package.yml`). It builds and uploads an installable
npm tarball as a workflow artifact. It does **not** publish to the npm registry.

1. Open the PR **Checks** tab → **Preview package** → **Artifacts**
2. Download `mco-preview-package-<run_id>` and extract the `.tgz` inside
3. Install locally (Python 3.10+ required on PATH):

```bash
tmp=$(mktemp -d)
npm install /path/to/tt-a1i-mco-X.Y.Z.tgz --prefix "$tmp" --no-audit --no-fund
"$tmp/node_modules/.bin/mco" --help
```

For same-repository pull requests, a separate job with only `pull-requests: write`
permission makes a best-effort PR comment with the install hint. A denied comment
never blocks the preview build. That job never checks out or executes PR code.
Fork PRs receive the same instructions through the workflow summary without
granting untrusted code a write-capable token.

## 1. Prepare the release PR

Start from the current remote main branch, not from a stale local `main`.

```bash
git fetch origin main --tags
git switch -c release/vX.Y.Z origin/main
```

Update the version in all package metadata:

- `package.json`
- `pyproject.toml`
- `runtime/__init__.py`

Add a `CHANGELOG.md` entry for the release date and version.

Run the release gate before opening the PR:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
npm pack --dry-run
```

Commit, push, open the PR, wait for GitHub checks, then merge it.

## 2. Tag the merged commit

After the release PR is merged, verify the remote main branch has the intended
version.

```bash
git fetch origin main --tags
git show --no-patch --oneline origin/main
git show origin/main:package.json | node -e "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>console.log(JSON.parse(s).version))"
```

Create and push the tag from `origin/main`.

```bash
git tag -a vX.Y.Z origin/main -m "vX.Y.Z"
git push origin vX.Y.Z
```

The release workflow accepts only a tag matching `v<package.json version>` and
requires a dated changelog heading. The same guard can be checked locally:

```bash
GITHUB_REF=refs/tags/vX.Y.Z python3 scripts/check_release_ref.py
```

If the tag already exists, do not recreate it. Verify it instead:

```bash
git ls-remote --tags origin refs/tags/vX.Y.Z
```

## 3. Publish through a GitHub Release

Create the release as a Draft, inspect its tag and notes, then publish it. The
`Publish npm` workflow runs the full gate, publishes the package, waits for npm
`latest` to match, and performs a clean registry install smoke.

```bash
gh release create vX.Y.Z --draft --title "vX.Y.Z" --notes-file docs/releases/vX.Y.Z.md
gh release edit vX.Y.Z --draft=false
```

Watch the workflow through completion. If `npm publish` succeeds but a later
verification step fails, choose Re-run failed jobs on that same workflow run.
The preflight skips `npm publish` only after the registry confirms the exact
version, then continues with the `latest` and clean-install checks.

If the package was not published or the retry still fails, return the GitHub
Release to Draft while investigating so GitHub and npm do not continue
advertising different latest versions.

## 4. Manual fallback: publish npm from a clean tag checkout

Check the currently published version first.

```bash
npm view @tt-a1i/mco version dist-tags --json
```

Publish from a clean temporary clone of the tag, not from a dirty working tree.

```bash
tmp=$(mktemp -d /tmp/mco-publish.XXXXXX)
git clone --depth 1 --branch vX.Y.Z https://github.com/mco-org/mco.git "$tmp"
cd "$tmp"
node -p "require('./package.json').version"
npm pack --dry-run
```

Then publish from a real terminal/TTY:

```bash
npm publish --access public --auth-type=web
```

## 5. npm web auth and 2FA

The repository `NPM_TOKEN` must identify an npm account or granular automation
token with write access to `@tt-a1i/mco`. The publish workflow runs `npm whoami`
before `npm publish`; if that check fails, replace the secret before retrying.
An existing package may return `E404 Not Found` when the token is valid but lacks
scope or package permission, so also verify the token owner appears here:

```bash
npm view @tt-a1i/mco maintainers --json
```

Publishing the prepared Draft GitHub Release triggers the npm workflow. If the
registry confirms the package was not published and that workflow fails, return
the release to Draft before using this manual fallback.

Use a real TTY for npm web-auth publish prompts. Do not pipe `npm publish`
through `tee`, and do not run it through a non-interactive command runner for the
final publish step. In non-TTY mode npm may print
`https://www.npmjs.com/auth/cli/***` with the auth id redacted; that URL is not
usable and cannot be recovered from the npm debug log because the log is redacted
too.

If npm reports `E401 Unauthorized`, log in first:

```bash
npm login --auth-type=web
npm whoami
```

If npm reports `EOTP` during `npm publish`, rerun publish in a TTY:

```bash
npm publish --access public --auth-type=web
```

Expected TTY prompt:

```text
Authenticate your account at:
https://www.npmjs.com/auth/cli/<auth-id>
Press ENTER to open in the browser...
```

Open the URL, finish the browser confirmation, then let the same publish command
continue. A successful publish ends with:

```text
+ @tt-a1i/mco@X.Y.Z
```

If publish returns `E404 Not Found` with `do not have permission`, first check
whether the shell is actually logged in as a maintainer:

```bash
npm whoami
npm view @tt-a1i/mco maintainers --json
```

In the observed failure case, `E404` followed a stale or missing npm session; a
fresh `npm login --auth-type=web` fixed it.

The working manual sequence for the v0.10.6 release was:

```bash
cd "$tmp"
npm whoami
npm publish --access public --auth-type=web
```

If `npm publish` asks for web auth, keep that same command running, open the
printed `https://www.npmjs.com/auth/cli/<auth-id>` URL, complete the browser
confirmation, and return to the terminal. Do not start a second non-TTY publish
attempt while the first publish is waiting.

## 6. Verify the published package

Confirm the registry state:

```bash
npm view @tt-a1i/mco version dist-tags --json
```

Run a clean install smoke:

```bash
tmp=$(mktemp -d /tmp/mco-npm-test.XXXXXX)
npm install @tt-a1i/mco@X.Y.Z --prefix "$tmp"
"$tmp/node_modules/.bin/mco" --help
```

The release is complete only after npm shows `latest` pointing at the new
version and the clean install smoke succeeds.
