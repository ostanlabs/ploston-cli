# Publishing to PyPI

This guide explains how to publish `ploston-cli` to TestPyPI and PyPI.

## Prerequisites

1. **PyPI Account**: Create accounts on both [PyPI](https://pypi.org) and [TestPyPI](https://test.pypi.org)
2. **API Tokens**: Generate API tokens for both platforms
3. **uv**: Install [uv](https://github.com/astral-sh/uv) package manager

## Setup API Tokens

### 1. Create PyPI API Token

1. Go to https://pypi.org/manage/account/token/
2. Click "Add API token"
3. Name: `ploston-cli-publish`
4. Scope: Select "Entire account" (first time) or specific project
5. Copy the token (starts with `pypi-`)

### 2. Create TestPyPI API Token

1. Go to https://test.pypi.org/manage/account/token/
2. Click "Add API token"
3. Name: `ploston-cli-test-publish`
4. Scope: Select "Entire account" (first time) or specific project
5. Copy the token (starts with `pypi-`)

### 3. Configure GitHub Secrets

Add these secrets to your GitHub repository:

1. Go to **Settings → Secrets and variables → Actions**
2. Add repository secrets:
   - `PYPI_API_TOKEN` - Your PyPI token
   - `TEST_PYPI_API_TOKEN` - Your TestPyPI token

### 4. Create GitHub Environments

1. Go to **Settings → Environments**
2. Create environment `pypi`:
   - Add protection rules (optional): require reviewers
3. Create environment `testpypi`:
   - No protection rules needed for testing

## Publishing Methods

### Method 1: GitHub Actions (Recommended)

#### Publish to TestPyPI (Manual)

1. Go to **Actions → Publish to PyPI**
2. Click "Run workflow"
3. Select target: `testpypi`
4. Click "Run workflow"

#### Publish to PyPI (On Release)

1. Go to **Releases → Create a new release**
2. Create a new tag (e.g., `v1.0.0`)
3. Fill in release notes
4. Click "Publish release"
5. The workflow automatically publishes to PyPI

### Method 2: Local Publishing

#### Setup Local Credentials

Create `~/.pypirc`:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-YOUR_PYPI_TOKEN

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-YOUR_TESTPYPI_TOKEN
```

Or use environment variables:

```bash
export UV_PUBLISH_TOKEN=pypi-YOUR_TOKEN
```

#### Publish to TestPyPI

```bash
# Build and publish
make publish-test

# Or manually:
uv build
uv publish --publish-url https://test.pypi.org/legacy/
```

#### Publish to PyPI

```bash
# Build and publish
make publish

# Or manually:
uv build
uv publish
```

## Testing the Published Package

### From TestPyPI

```bash
# Create a test environment
python -m venv test-env
source test-env/bin/activate

# Install from TestPyPI (with PyPI fallback for dependencies)
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ ploston-cli

# Test
ploston version
```

### From PyPI

```bash
pip install ploston-cli
ploston version
```

## Version Management

Before publishing, update the version in:

1. `pyproject.toml`: `version = "X.Y.Z"`
2. `src/ploston_cli/main.py`: `__version__ = "X.Y.Z"`

Follow [Semantic Versioning](https://semver.org/):
- MAJOR: Breaking changes
- MINOR: New features (backward compatible)
- PATCH: Bug fixes (backward compatible)

## Troubleshooting

### "File already exists"

PyPI doesn't allow re-uploading the same version. Bump the version number.

### "Invalid API token"

- Verify the token is correct
- Check token scope includes the project
- Ensure no extra whitespace in the token

### Dependencies not found on TestPyPI

TestPyPI doesn't have all packages. Use `--extra-index-url`:

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ ploston-cli
```

## Checklist Before Publishing

- [ ] All tests pass: `make check`
- [ ] Version updated in `pyproject.toml` and `main.py`
- [ ] CHANGELOG updated (if applicable)
- [ ] README is up to date
- [ ] Test on TestPyPI first
- [ ] Create GitHub release with tag matching version

