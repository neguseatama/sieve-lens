# 🔐 CI/CD & Security Guide

Sieve Lens has **zero external runtime dependencies**. All observations are
performed using the Python standard library.

## CI Pipeline

`.github/workflows/test.yml` runs the full test suite on Python 3.9–3.12 for
every push and pull request, then runs `examples/demo.py` as a sanity check.

```yaml
name: Sieve Lens CI Pipeline

on:
  push:
    branches: [ "main", "develop" ]
  pull_request:
    branches: [ "main", "develop" ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.9", "3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Run Test Suite
        run: python -m unittest discover -s tests -p "test_sieve_lens.py" -v
      - name: Run Demo
        run: python examples/demo.py

## Required GitHub Secrets
None. Sieve Lens does not require any cloud credentials, API keys, or
external services.

## Security Considerations
No third-party libraries at runtime.

Deterministic outputs: SHA-256 hashing is not used, but all
observations are content-addressed and reproducible.

No execution of document content: The engine parses XML and HTML
structurally; it never evaluates expressions, scripts, or macros.

Input validation: extraction failures are caught and returned as
H1=0 masks, not propagated as exceptions.

Static character tables: no dynamic code loading.

## Reporting a Vulnerability
Follow SECURITY.md. Do not open a public issue. Email neguse.cat@gmail.com
with reproduction steps.