"""
Sieve Lens extensions.

Extensions add support for additional document formats by registering
custom extractors with a SieveLensEngine instance. All extensions are
optional and require their own external dependencies.

Available extensions:
  - pdf : PDF support via pypdf  (install with: pip install sieve-lens[pdf])
"""