import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from app import audit, challan, pdfmini, review
from app.violation import violation_logger as vl
from tests.db_helpers import db_connect


def jpeg_bytes(width=64, height=48, colour=(0, 0, 255)):
    frame = np.zeros((height, width, 3), np.uint8)
    frame[:] = colour
    ok, buf = cv2.imencode(".jpg", frame)

    return buf.tobytes()


class PdfMiniTests(unittest.TestCase):
    @unittest.skipIf(cv2 is None, "OpenCV is not installed")
    def test_jpeg_size_is_read(self):
        self.assertEqual(pdfmini.jpeg_info(jpeg_bytes(64, 48)), (64, 48, 3))

        with self.assertRaises(pdfmini.PdfError):
            pdfmini.jpeg_info(b"not a jpeg")

    def test_document_has_valid_structure_and_escapes_text(self):
        doc = pdfmini.Document(title="T (1)", author="a")
        page = doc.add_page()
        page.text(10, 10, "Fine (Rs. 500) \\ ok ₹")
        pdf = doc.render()

        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"Fine \\(Rs. 500\\) \\\\ ok ?", pdf)
        # the xref offsets point at the objects
        start = int(pdf.split(b"startxref\n")[1].split(b"\n")[0])
        self.assertTrue(pdf[start:].startswith(b"xref"))
        first = int(pdf[start:].split(b"\n")[3][:10])
        self.assertTrue(pdf[first:].startswith(b"1 0 obj"))


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class ChallanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"

        for target, name, value in (
                (vl, "DB_PATH", self.db), (audit, "DB_PATH", self.db),
                (challan.paths, "DB_PATH", self.db),
                (challan.paths, "OUTPUT_DIR", self.dir / "outputs"),
                (challan.paths, "ALLOWED_EVIDENCE_ROOTS", (self.dir,))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.ev = self.dir / "ev.jpg"
        self.crop = self.dir / "crop.jpg"
        self.ev.write_bytes(jpeg_bytes(320, 200))
        self.crop.write_bytes(jpeg_bytes(60, 80, (0, 255, 0)))
        vl.log_violation("k1", 7, "speeding", self.ev, speed=61, speed_limit=40,
                         crop_path=self.crop, camera_id="NH-4",
                         plate_text="KA01AB1234", source="clip.mp4")

    def text(self, path):
        if not shutil.which("pdftotext"):
            self.skipTest("pdftotext is not installed")

        return subprocess.run(["pdftotext", "-layout", str(path), "-"],
                              capture_output=True, text=True, check=True).stdout

    def test_unapproved_record_gets_no_challan(self):
        with self.assertRaisesRegex(challan.ChallanError, "only approved"):
            challan.create(1)

        with self.assertRaises(challan.ChallanError):
            challan.create(99)

    def test_approved_record_makes_a_readable_pdf_with_the_facts(self):
        review.set_status(1, "approved", "alice", note="clear photo")
        path = challan.create(1, user="alice")
        text = self.text(path)

        self.assertTrue(path.name.startswith("TA-"))
        self.assertTrue(path.read_bytes().startswith(b"%PDF"))
        for expected in ("TRAFFIC VIOLATION NOTICE", "Speeding", "NH-4",
                         "KA01AB1234", "61 km/h in a 40 km/h limit", "Rs. 800",
                         "approved by alice", "clear photo", "not a legal notice"):
            self.assertIn(expected, text)

        self.assertEqual(audit.recent(3)[0]["action"], "challan_created")
        # both pictures were embedded
        self.assertEqual(path.read_bytes().count(b"/DCTDecode"), 2)

    def test_missing_pictures_still_make_a_challan(self):
        review.set_status(1, "approved", "alice")
        self.ev.unlink()
        self.crop.unlink()
        path = challan.create(1)

        self.assertEqual(path.read_bytes().count(b"/DCTDecode"), 0)
        self.assertIn("no longer", self.text(path))

    def test_pictures_outside_the_data_folders_are_never_embedded(self):
        review.set_status(1, "approved", "alice")
        outside = Path(tempfile.mkdtemp()) / "x.jpg"
        outside.write_bytes(jpeg_bytes())
        self.addCleanup(lambda: outside.unlink(missing_ok=True))

        with db_connect(self.db) as conn:
            conn.execute("UPDATE violation_records SET evidence_path = ?",
                         (str(outside),))

        self.assertEqual(challan.create(1).read_bytes().count(b"/DCTDecode"), 1)

    def test_cli(self):
        self.assertEqual(challan.main(["--all-approved"]), 1)   # none approved
        review.set_status(1, "approved", "alice")
        self.assertEqual(challan.main(["--all-approved", "--output",
                                       str(self.dir / "pdfs")]), 0)
        self.assertEqual(len(list((self.dir / "pdfs").glob("*.pdf"))), 1)
        self.assertEqual(challan.main(["--id", "5"]), 1)

    def test_number_is_stable(self):
        record = challan.fetch_record(1)

        self.assertRegex(challan.challan_number(record), r"^TA-\d{8}-000001$")


if __name__ == "__main__":
    unittest.main()
