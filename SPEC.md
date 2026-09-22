# Sieve Lens Engine Specification v0

- **Version**: 0.0.1
- **Status**: Initial Specification
- **Scope**: Invisible content observation in `.txt` / `.md` / `.html` / `.docx`

---

## 1. Core Architecture and Pipeline

Sieve Lens evaluates a single document D through a pipeline of seven
observation hypotheses H1 to H7 and returns a deterministic observation mask.

[ Document ]
|
v
H1 (Parseability)
|
v
[ Format-specific extraction ]
|
v
H2..H7 (evidence collection)
|
v
7-bit Mask: H1 H2 H3 H4 - H5 H6 H7
|
v
[ Observation Report (human-readable) ]


---

## 2. Hypothesis Definitions

### H1: Parseability

- **Definition**: The document can be read and parsed by the format-specific extractor.
- **Rule**: If extraction raises an exception, return mask `0000-000` immediately.

### H2: Zero-Width Density

- **Character set**: `U+200B, U+200C, U+200D, U+2060, U+FEFF` (BOM stripped if leading).
- **Metric**: `count / total_characters` over body text.
- **Threshold**: `>= 0.01` (default).

### H3: Bidi Controls

- **Character set**: `U+202A..U+202E`, `U+2066..U+2069`.
- **Rule**: H3 = 1 if any bidi control character is present in the body text.

### H4: Format Concealment

- **Detection**: HTML inline style attributes matching:
  - `display:none`
  - `visibility:hidden`
  - `opacity:0`
  - `font-size:0`
  - `left/top/right/bottom: -NNNN+`
  - `hidden` attribute, `aria-hidden="true"`
- **Rule**: H4 = 1 if any element with these properties contains non-trivial text.

### H5: Out-of-Band Channel

- **Sources**: HTML comments, DOCX comments, DOCX core properties (`dc:subject`,
  `dc:description`, `cp:keywords`), HTML `alt` / `title` / `aria-label`.
- **Minimum length**: 10 characters (to avoid flagging short author names).
- **Rule**: H5 = 1 if any out-of-band segment meets the minimum length.

### H6: Script Mixing

- **Rule**: H6 = 1 if any whitespace-delimited token contains both Latin and
  (Cyrillic or Greek) characters (homoglyph attack signature).

### H7: Contiguous Payload

- **Character set**: Union of ZERO_WIDTH, BIDI_CONTROL, TAG_CHARS, VARIATION_SELECTORS.
- **Metric**: Longest run of consecutive invisible characters.
- **Threshold**: `>= 16` (default).
- **Decoding**: Zero-width runs are decoded as bit sequences (`U+200B`=0, `U+200C`=1)
  and converted to ASCII if the bit length is a multiple of 8.

---

## 3. Mask Outputs

- **Parse failure**: `0000-000`
- **Successful observation**: `H1H2H3H4-H5H6H7`

Example: `1101-101` means H1=1, H2=1, H3=0, H4=1 / H5=1, H6=0, H7=1.

---

## 4. Default Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `zero_width_density_threshold` | 0.01 | ~1% is well above natural noise |
| `payload_min_length` | 16 | 16 contiguous invisible chars is essentially never accidental |
| `oob_min_length` | 10 | Filters out short author names and titles |

---

## 5. Design Constraints

- **Deterministic**: no randomness, no time, no environment dependence.
- **Zero dependencies**: Python standard library only.
- **Observation, not judgment**: the engine reports evidence; it does not
  classify intent.
- **Scope**: v0 supports `.txt`, `.md`, `.html`, `.htm`, `.docx`.