# 🚀 Deployment Guide

Sieve Lens is a lightweight, zero-dependency Python library.

## 1. Installation

```bash
git clone https://github.com/neguseatama/sieve-lens.git
cd sieve-lens
pip install .

Or from PyPI (once published):

pip install sieve-lens


## 2. Container Build

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY sieve_lens.py ./
COPY tests/ ./tests/
COPY examples/ ./examples/

RUN pip install --no-cache-dir .

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_sieve_lens.py"]


## 3. Serverless Deployment
Sieve Lens has no ML model, no external dependencies, and no network calls
at runtime. It is well suited to containerized serverless platforms
(Cloud Run, AWS Fargate, Lambda container images).

Memory and CPU requirements depend on document size.
For typical documents (< 1 MB), memory usage is under 50 MB and processing
time is in the millisecond range. Actual capacity should be benchmarked
against the target corpus.


## 4. Security Considerations
The engine only reads files. It never writes, executes, or renders them.

It does not open network sockets.

It does not evaluate code or templates embedded in documents.

Character tables are static; no dynamic code is loaded.

The container runs as a non-root user in the provided Dockerfile.


## 5. Handling Untrusted Files
Sieve Lens is not a sandbox. If a document format is known to have
exploitable parsers in the Python standard library, the recommendation is to
run Sieve Lens in a container with:

read-only filesystem for the input volume

no network access

dropped capabilities

strict resource limits

This isolates any parser-level risk from the host environment.