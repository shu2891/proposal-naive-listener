"""Behavioral invariants for exposure, evidence provenance and ledger preservation."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("reveal.py")


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def snapshot(unit, claim="目前所見", event=None):
    return {"unit": unit, "retelling": claim, "state": "provisional", "state_reason": "仍有細節未交代",
            "knowledge": [{"claim": claim, "basis": "explicit", "rationale": "當頁明說",
                           "evidence": [{"unit": unit, "channel": "visible", "anchor": claim}]}],
            "expectations": [], "assumptions": [], "questions": [], "events": event or []}


def make_pdf(path):
    # Valid two-page PDF with blue first page, red second page, and invisible text.
    a = b"0 0 1 rg 10 10 80 80 re f BT /F1 14 Tf 10 100 Td (FIRST) Tj ET BT 3 Tr /F1 10 Tf 100 30 Td (HIDDEN ANSWER) Tj ET"
    b = b"1 0 0 rg 10 10 80 80 re f BT /F1 14 Tf 10 100 Td (FUTURE) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 120] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(a)).encode() + b" >>\nstream\n" + a + b"\nendstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 120] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        b"<< /Length " + str(len(b)).encode() + b" >>\nstream\n" + b + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    path.write_bytes(data)


class RevealTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "deck.json"
        write(self.source, {"units": [{"visible": "第一頁"}, {"visible": "未來秘密答案"}]})
        self.session = self.root / "session"
        self.current = self.root / "observation.json"

    def call(self, command, *args, fail=False):
        env = dict(os.environ, PYTHONUTF8="1")
        result = subprocess.run([sys.executable, str(SCRIPT), command, "--session", str(self.session), *map(str, args)],
                                capture_output=True, text=True, encoding="utf-8", env=env)
        if fail:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def init(self):
        self.call("init", "--source", self.source, "--mode", "limited")

    def record(self, snap):
        write(self.current, snap)
        return self.call("record", "--snapshot", self.current)

    def test_gate_future_evidence_and_preserved_history(self):
        self.init()
        self.call("record", "--snapshot", self.current, fail=True)
        first = self.call("next")
        self.assertEqual(first["unit"], 1)
        self.assertEqual(Path(first["paths"]["visible"]).read_text(encoding="utf-8"), "第一頁")
        self.assertFalse((self.session / "revealed" / "unit-0002").exists())
        self.call("next", fail=True)
        self.assertEqual(self.call("current")["unit"], 1)
        bad = snapshot(1)
        bad["knowledge"][0]["evidence"][0]["unit"] = 2
        write(self.current, bad)
        self.assertIn("unrevealed", self.call("record", "--snapshot", self.current, fail=True))
        self.assertTrue(self.call("status")["pending"])
        self.record(snapshot(1, "第一頁"))
        old = (self.session / "snapshots" / "unit-0001.json").read_bytes()
        self.call("record", "--snapshot", self.current, fail=True)
        self.assertEqual(self.call("next")["unit"], 2)
        self.record(snapshot(2, "未來秘密答案", [{"type": "revision", "explanation": "新頁提供新的理解依據", "related_units": [1, 2]}]))
        self.assertEqual((self.session / "snapshots" / "unit-0001.json").read_bytes(), old)
        self.assertTrue(self.call("status")["complete"])
        self.call("next", fail=True)
        self.call("init", "--source", self.source, "--mode", "limited", fail=True)
        self.call("rebuild")
        for name in ("mental-model.md", "assumptions.md", "questions.md", "comprehension-timeline.md"):
            self.assertTrue((self.session / name).is_file())
        timeline = (self.session / "comprehension-timeline.md").read_text(encoding="utf-8")
        self.assertIn("第一頁", timeline)
        self.assertIn("未來秘密答案", timeline)

    def test_unavailable_channel_and_missing_explicit_evidence(self):
        self.init()
        self.call("next")
        bad = snapshot(1)
        bad["knowledge"][0]["evidence"][0]["channel"] = "spoken"
        write(self.current, bad)
        self.assertIn("unavailable", self.call("record", "--snapshot", self.current, fail=True))
        bad["knowledge"][0]["evidence"] = []
        write(self.current, bad)
        self.assertIn("require", self.call("record", "--snapshot", self.current, fail=True))
        bad = snapshot(1, event=[{"type": "repair", "explanation": "修復", "related_units": [1]}])
        write(self.current, bad)
        self.assertIn("earlier", self.call("record", "--snapshot", self.current, fail=True))

    def test_source_change_refused(self):
        self.init()
        write(self.source, {"units": [{"visible": "更換版本"}]})
        self.assertIn("changed", self.call("next", fail=True))
        self.assertFalse((self.session / "revealed" / "unit-0001").exists())

    def test_image_manifest_freezes_assets_and_keeps_channels(self):
        image = self.root / "not-an-audience-clue.png"
        # Asset bytes are copied, not inspected by this helper.
        image.write_bytes(b"fixture")
        write(self.source, {"units": [{"image": image.name, "spoken": "實際說出的話"}]})
        self.init()
        result = self.call("next")
        self.assertEqual(Path(result["paths"]["image"]).name, "visible.png")
        self.assertEqual(Path(result["paths"]["spoken"]).read_text(encoding="utf-8"), "實際說出的話")
        snap = snapshot(1)
        snap["knowledge"][0]["evidence"].append({"unit": 1, "channel": "spoken", "anchor": "實際說出的話"})
        self.record(snap)
        image.write_bytes(b"changed")
        self.assertIn("changed", self.call("status", fail=True))

    def test_pdf_one_page_visual_without_hidden_text(self):
        from PIL import Image
        self.source = self.root / "deck.pdf"
        make_pdf(self.source)
        self.init()
        result = self.call("next")
        self.assertEqual(set(result["paths"]), {"image"})
        self.assertFalse((self.session / "revealed" / "unit-0002").exists())
        with Image.open(result["paths"]["image"]) as picture:
            self.assertEqual(picture.size, (300, 180))
            r, g, b = picture.convert("RGB").getpixel((45, 90))
            self.assertGreater(b, 200)
            self.assertLess(r, 50)
            # Invisible text's area stays white; it wasn't exported as text.
            self.assertEqual(picture.convert("RGB").getpixel((180, 135)), (255, 255, 255))
        self.record(snapshot(1))
        result = self.call("next")
        with Image.open(result["paths"]["image"]) as picture:
            r, g, b = picture.convert("RGB").getpixel((45, 90))
            self.assertGreater(r, 200)
            self.assertLess(b, 50)


if __name__ == "__main__":
    unittest.main()
