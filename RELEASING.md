# Releasing MCO

MCO is published through npm only. Do not publish to PyPI.

This guide records the manual release path that works when GitHub Actions cannot
publish because `NPM_TOKEN` is missing or npm requires web-based 2FA.

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

If the tag already exists, do not recreate it. Verify it instead:

```bash
git ls-remote --tags origin refs/tags/vX.Y.Z
```

## 3. Publish npm from a clean tag checkout

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

Then publish:

```bash
npm publish --access public --auth-type=web
```

## 4. npm web auth and 2FA

Use a real TTY for npm web-auth publish prompts. In non-TTY command runners, npm
may print `https://www.npmjs.com/auth/cli/***` with the auth id redacted, which
is not usable.

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

## 5. Verify the published package

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
