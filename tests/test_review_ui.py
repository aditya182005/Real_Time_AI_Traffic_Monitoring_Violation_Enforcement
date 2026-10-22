import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from app import audit
from app.violation import violation_logger as vl
from tests.db_helpers import db_connect
from tests.test_ui_pages import PageTestCase, empty_data


class EvidenceReviewTests(PageTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "t.db"

        for target in (vl, audit):
            patcher = mock.patch.object(target, "DB_PATH", self.db)
            patcher.start()
            self.addCleanup(patcher.stop)

        vl.log_violation("k1", 3, "red_light", Path(self.tmp.name) / "e.jpg")

    def data(self):
        with db_connect(self.db) as conn:
            violations = pd.read_sql_query("SELECT * FROM violation_records", conn)

        data = empty_data()
        data["violations"] = violations

        return data

    def status(self):
        with db_connect(self.db) as conn:
            return conn.execute(
                "SELECT review_status, reviewed_by FROM violation_records"
            ).fetchone()

    def test_operator_can_approve(self):
        self.start(clicks={"approve_1"}, values={"review_note_1": "clear"})
        self.ui("evidence").render(self.data())

        self.assertEqual(self.status(), ("approved", "tester"))
        self.assertTrue(self.st.called("rerun"))
        self.assertEqual(audit.recent(3)[0]["action"], "review_approved")

    def test_viewer_cannot_decide(self):
        self.start(clicks={"approve_1"})
        self.st.session_state["user"] = {"name": "v", "role": "viewer"}
        self.ui("evidence").render(self.data())

        self.assertEqual(self.status(), ("pending", None))
        self.assertIn("Operators and admins can approve", self.st.text())

    def test_filter_hides_non_matching(self):
        self.start(values={"evidence_review_filter": "Approved"})
        self.ui("evidence").render(self.data())

        self.assertIn("No violations are approved", self.st.text())


if __name__ == "__main__":
    unittest.main()
