# Contributing to Sieve Lens

Thank you for considering contributing to Sieve Lens!

## Design Principles

- **Determinism**: All observations must be reproducible. Avoid time, randomness,
  and environment-dependent state.
- **Zero Dependencies**: Use only the Python standard library.
- **Explainability**: Every observation must include location and evidence.
- **Observation, not Judgment**: The engine reports facts. It never declares
  "this is an attack" or "this is safe".

## How to Contribute

1. Fork the repository.
2. Create a feature branch.
3. Make changes with clear commit messages.
4. Ensure all tests pass:
   ```bash
   python -m unittest discover -s tests -p "test_sieve_lens.py" -v
5. Submit a pull request.

## Reporting Issues
Please include:

Python version

Minimal document (or base64-encoded bytes) to reproduce

Expected vs actual observation mask

Evidence output if available