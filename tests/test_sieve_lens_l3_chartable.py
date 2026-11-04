"""L3: the pinned character table (sieve-lens v0.21.0).

Test ids L3-T01..T08 follow the character-table part of the
implementation request. The table ships as
``sieve_lens_ext/chartable_v1.json`` — a byte-exact copy of the
standard table, pinned by sha256 — with a fail-closed loader in
``sieve_lens_ext/chartable.py``: the file is read lazily (never at
import), its sha256 is verified against the pin on every load, a
missing, tampered or malformed table is a hard ``ChartableError``
(never a silent fallback), and every call returns a fresh dict. The
observation pipeline does not consume the table in this version; the
loader only establishes the pinned source of the standard inside
Lens.
"""

import hashlib
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest
import zipfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import sieve_lens  # noqa: E402
from sieve_lens_ext.redact_bridge import HOMOGLYPH_TWINS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    _chartable = importlib.import_module("sieve_lens_ext.chartable")
    CHARTABLE_V1_SHA256 = getattr(_chartable, "CHARTABLE_V1_SHA256", None)
    load_chartable_v1 = getattr(_chartable, "load_chartable_v1", None)
    ChartableError = getattr(_chartable, "ChartableError", None)
except ImportError:
    _chartable = None
    CHARTABLE_V1_SHA256 = None
    load_chartable_v1 = None
    ChartableError = None

_EXPECTED_SHA256 = (
    "c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605")
_TABLE_PART = "sieve_lens_ext/chartable_v1.json"


class L3Base(unittest.TestCase):
    def _require_module(self):
        if _chartable is None or load_chartable_v1 is None \
                or ChartableError is None:
            self.fail("sieve_lens_ext.chartable is not implemented yet")


def _kind_points(entries):
    points = set()
    for entry in entries:
        if isinstance(entry, list):
            lo, hi = int(entry[0], 16), int(entry[1], 16)
            points.update(range(lo, hi + 1))
        else:
            points.add(int(entry, 16))
    return points


# ----------------------------------------------------------------------
# L3-T01 — the table ships in the wheel and the sdist (real build)
# ----------------------------------------------------------------------

class TestL3T01ShippedTable(L3Base):
    def test_wheel_and_sdist_carry_the_table(self):
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.setuptools.package-data]", text)
        self.assertIn('sieve_lens_ext = ["chartable_v1.json"]', text)

        if importlib.util.find_spec("setuptools") is None:
            self.skipTest(
                "setuptools is required to build the wheel and the sdist "
                "for this pin (install the 'test' extra: "
                "pip install -e '.[test]')")

        outdir = Path(tempfile.mkdtemp())
        srcdir = Path(tempfile.mkdtemp()) / "src"
        shutil.copytree(
            REPO_ROOT, srcdir,
            ignore=shutil.ignore_patterns(
                ".git", "build", "dist", "__pycache__", "*.egg-info"))
        build = (
            "import sys\n"
            "from setuptools import build_meta\n"
            "target = sys.argv[1]\n"  # build_* rewrites sys.argv
            "build_meta.build_wheel(target)\n"
            "build_meta.build_sdist(target)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", build, str(outdir)],
            cwd=srcdir, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

        wheels = list(outdir.glob("*.whl"))
        sdists = list(outdir.glob("*.tar.gz"))
        self.assertEqual(len(wheels), 1, wheels)
        self.assertEqual(len(sdists), 1, sdists)
        with zipfile.ZipFile(wheels[0]) as zf:
            self.assertIn(_TABLE_PART, zf.namelist())
        with tarfile.open(sdists[0]) as tf:
            members = [m.name for m in tf.getmembers()]
            self.assertTrue(
                any(m.endswith(_TABLE_PART) for m in members), members)


# ----------------------------------------------------------------------
# L3-T02 — schema and structure of the shipped table
# ----------------------------------------------------------------------

class TestL3T02Schema(L3Base):
    def test_load_returns_pinned_schema_and_sections(self):
        self._require_module()
        table = load_chartable_v1()
        self.assertEqual(table["schema"], "sieve-chartable/1")
        self.assertEqual(table["version"], 1)
        self.assertIsInstance(table["description"], str)
        for key in ("dashes", "fullwidth_ascii", "invisible", "spaces",
                    "twins"):
            self.assertIn(key, table)
        inv = table["invisible"]
        self.assertEqual(sorted(inv),
                         ["bidi_control", "tag", "variation_selector",
                          "zero_width"])
        self.assertEqual(len(_kind_points(inv["zero_width"])), 5)
        self.assertEqual(len(_kind_points(inv["bidi_control"])), 9)
        self.assertEqual(len(_kind_points(inv["tag"])), 128)
        self.assertEqual(len(_kind_points(inv["variation_selector"])), 256)
        self.assertEqual(len(table["twins"]), 102)
        self.assertEqual(len(table["dashes"]), 9)
        self.assertEqual(table["spaces"], ["00A0", "3000"])


# ----------------------------------------------------------------------
# L3-T03 — the sha256 pin is fail-closed
# ----------------------------------------------------------------------

class TestL3T03DigestPin(L3Base):
    def test_digest_pin_is_fail_closed(self):
        self._require_module()
        raw = (REPO_ROOT / _TABLE_PART).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), _EXPECTED_SHA256)
        self.assertEqual(CHARTABLE_V1_SHA256, _EXPECTED_SHA256)
        with self.assertRaises(ChartableError):
            _chartable.load_chartable_v1_bytes(raw + b"\n")
        data = json.loads(raw.decode("utf-8"))
        data["twins"]["FF10"] = "Z"
        tampered = json.dumps(data, ensure_ascii=False,
                              sort_keys=True).encode("utf-8")
        self.assertNotEqual(hashlib.sha256(tampered).hexdigest(),
                            _EXPECTED_SHA256)
        with self.assertRaises(ChartableError):
            _chartable.load_chartable_v1_bytes(tampered)


# ----------------------------------------------------------------------
# L3-T04 — a missing table is a hard error, not an empty result
# ----------------------------------------------------------------------

class TestL3T04Missing(L3Base):
    def test_missing_table_is_a_hard_error(self):
        self._require_module()
        original = _chartable._TABLE_FILE
        with tempfile.TemporaryDirectory() as d:
            _chartable._TABLE_FILE = str(Path(d) / "chartable_v1.json")
            try:
                with self.assertRaises(ChartableError):
                    load_chartable_v1()
            finally:
                _chartable._TABLE_FILE = original


# ----------------------------------------------------------------------
# L3-T05 — every call returns a fresh dict
# ----------------------------------------------------------------------

class TestL3T05FreshDict(L3Base):
    def test_each_call_returns_a_fresh_dict(self):
        self._require_module()
        first = load_chartable_v1()
        first["twins"]["0FF1"] = "Z"
        first["invisible"]["zero_width"].append("1234")
        second = load_chartable_v1()
        self.assertNotIn("0FF1", second["twins"])
        self.assertNotIn("1234", second["invisible"]["zero_width"])
        self.assertEqual(second, load_chartable_v1())


# ----------------------------------------------------------------------
# L3-T06 — the table is value-equivalent to the observation tables
# (the core invisible constants and the look-alike twins)
# ----------------------------------------------------------------------

class TestL3T06Equivalence(L3Base):
    def test_invisible_and_twins_match_the_observation_tables(self):
        self._require_module()
        table = load_chartable_v1()
        inv = table["invisible"]
        kinds = {
            "zero_width": sieve_lens.ZERO_WIDTH,
            "bidi_control": sieve_lens.BIDI_CONTROL,
            "tag": sieve_lens.TAG_CHARS,
            "variation_selector": sieve_lens.VARIATION_SELECTORS,
        }
        union = set()
        for kind, charset in kinds.items():
            points = _kind_points(inv[kind])
            self.assertEqual(points, set(charset), kind)
            union |= points
        self.assertEqual(union, set(sieve_lens.INVISIBLE))

        twins = {int(k, 16): v for k, v in table["twins"].items()}
        self.assertEqual(twins, dict(HOMOGLYPH_TWINS))

        fa = table["fullwidth_ascii"]
        lo, hi = int(fa["from"], 16), int(fa["to"], 16)
        base = int(fa["base"], 16)
        self.assertGreaterEqual(lo, 0xFF01)
        self.assertLessEqual(hi, 0xFF5E)
        for cp, target in twins.items():
            if lo <= cp <= hi:
                self.assertEqual(target, chr(base + cp - lo))

        self.assertFalse(union & set(twins))
        self.assertFalse(union & {int(s, 16) for s in table["spaces"]})
        self.assertFalse(union & {int(s, 16) for s in table["dashes"]})
        self.assertFalse(set(twins) & {int(s, 16) for s in table["spaces"]})
        self.assertFalse(set(twins) & {int(s, 16) for s in table["dashes"]})
        self.assertFalse(
            {int(s, 16) for s in table["spaces"]}
            & {int(s, 16) for s in table["dashes"]})


# ----------------------------------------------------------------------
# L3-T07 — the table is read lazily: importing the module opens
# nothing, loading opens the file exactly then
# ----------------------------------------------------------------------

class TestL3T07Lazy(L3Base):
    def test_import_reads_nothing_and_load_reads_the_file(self):
        self._require_module()
        snippet = (
            "import sys\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "reads = []\n"
            "def hook(event, args):\n"
            "    if event == 'open' and isinstance(args[0], str):\n"
            "        reads.append(args[0])\n"
            "sys.addaudithook(hook)\n"
            "import sieve_lens_ext.chartable as c\n"
            "assert not any('chartable_v1.json' in r for r in reads), reads\n"
            "c.load_chartable_v1()\n"
            "assert any('chartable_v1.json' in r for r in reads), reads\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("OK", result.stdout)


# ----------------------------------------------------------------------
# L3-T08 — public surface: the pinned constant and the loader live in
# the extension package, collide with nothing, and stay stdlib-only
# ----------------------------------------------------------------------

class TestL3T08Surface(L3Base):
    def test_public_names_collisions_and_stdlib_only(self):
        self._require_module()
        self.assertEqual(CHARTABLE_V1_SHA256, _EXPECTED_SHA256)
        self.assertTrue(issubclass(ChartableError, Exception))
        self.assertFalse(hasattr(sieve_lens, "load_chartable_v1"))
        self.assertFalse(hasattr(sieve_lens, "CHARTABLE_V1_SHA256"))
        self.assertFalse(hasattr(sieve_lens, "ChartableError"))
        import sieve_lens_ext
        self.assertFalse(hasattr(sieve_lens_ext, "load_chartable_v1"))
        self.assertEqual(
            getattr(sieve_lens_ext, "__all__", None), None)
        import ast
        tree = ast.parse(
            (REPO_ROOT / "sieve_lens_ext/chartable.py").read_text(
                encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        self.assertLessEqual(
            imports,
            {"__future__", "hashlib", "json", "os", "re", "typing"})


if __name__ == "__main__":
    unittest.main()
