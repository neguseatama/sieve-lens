# The Pinned Character Table (chartable v1)

Sieve Lens ships the character table the Sieve tools share as
`sieve_lens_ext/chartable_v1.json`. The copy in this package is the
standard; other Sieve tools carry byte-exact copies pinned to this
file by sha256, and changes to the standard are made here — never by
editing a copy.

## What the table holds

| Section | Content |
|---|---|
| `invisible` | the invisible characters, by kind: `zero_width` (5 code points), `bidi_control` (9), `tag` (U+E0000–U+E007F, 128), `variation_selector` (U+FE00–U+FE0F and U+E0100–U+E01EF, 256) — 398 in total |
| `twins` | 102 look-alike code points and their ASCII twins (Cyrillic, Greek, fullwidth digits and fullwidth letters) |
| `fullwidth_ascii` | the fullwidth ASCII range U+FF01–U+FF5E and its ASCII base U+0021 |
| `spaces` | the folding spaces U+00A0 and U+3000 |
| `dashes` | the folding dashes U+2010–U+2015, U+2212, U+30FC and U+FF70 |

The invisible characters are removed, the twins and the fullwidth
range fold to their ASCII twins, the folding spaces fold to the ASCII
space, and (opt-in) the folding dashes fold to the ASCII hyphen-minus.
The four steps share no code point, so one translation pass is
equivalent to running them in order, and no printable ASCII character
is ever a mapping key.

## The pin

- sha256 of the shipped file:
  `c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605`
- size: 2,693 bytes
- schema: `sieve-chartable/1`, version 1

The digest is a property any user can verify on the shipped artifact;
the loader verifies it again on every load.

## The loader

`sieve_lens_ext/chartable.py` exposes:

- `CHARTABLE_V1_SHA256` — the pinned digest;
- `load_chartable_v1()` — reads the packaged file, verifies the sha256
  pin on the exact bytes, validates the structure, and returns a fresh
  dict per call, so callers cannot corrupt each other's view through
  mutation;
- `load_chartable_v1_bytes(raw)` and `parse_chartable_v1(data)` — the
  byte-level and object-level entries behind it;
- `ChartableError` — raised hard when the table is missing, tampered
  with, or malformed. There is no fallback and no silent degradation.

The file is read lazily: importing the module opens nothing. The
observation pipeline does not consume the table yet; this module
establishes the pinned source of the standard inside Lens.
