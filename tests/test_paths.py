import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import paths
from tests.fake_streamlit import FakeStreamlit, install


class DataDirTests(unittest.TestCase):

    def reload_with(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            if "TRAFFIC_AGENT_DATA_DIR" not in env:
                os.environ.pop("TRAFFIC_AGENT_DATA_DIR", None)

            module = importlib.reload(paths)

        self.addCleanup(importlib.reload, paths)

        return module

    def test_default_is_the_project_folder(self):
        module = self.reload_with({})

        self.assertEqual(module.DATA_DIR, module.ROOT)
        self.assertEqual(module.DB_PATH, module.ROOT / "traffic_agent.db")
        self.assertEqual(module.OUTPUT_DIR, module.ROOT / "outputs")

    def test_env_variable_moves_database_and_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            module = self.reload_with({"TRAFFIC_AGENT_DATA_DIR": folder})
            data = Path(folder).resolve()

            self.assertEqual(module.DATA_DIR, data)
            self.assertEqual(module.DB_PATH, data / "traffic_agent.db")
            self.assertEqual(module.OUTPUT_DIR, data / "outputs")
            self.assertIn(data, module.ALLOWED_EVIDENCE_ROOTS)
            self.assertIn(module.ROOT, module.ALLOWED_EVIDENCE_ROOTS)

    def test_blank_value_means_default(self):
        module = self.reload_with({"TRAFFIC_AGENT_DATA_DIR": "   "})

        self.assertEqual(module.DATA_DIR, module.ROOT)


class EvidenceConfinementTests(unittest.TestCase):
    """A database row must not be able to make the page read other files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base / "project"
        self.data = self.base / "data"
        self.outside = self.base / "outside"

        for folder in (self.project, self.data, self.outside):
            folder.mkdir()

        self.addCleanup(install(FakeStreamlit()))
        self.evidence = importlib.import_module("app.ui.evidence")

        for patch in (
            mock.patch.object(self.evidence, "ROOT", self.project),
            mock.patch.object(paths, "ALLOWED_EVIDENCE_ROOTS",
                              (self.project, self.data)),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def resolve(self, value):
        return self.evidence.resolve_evidence_path(value)

    def test_file_inside_the_project_is_allowed(self):
        image = self.project / "a.jpg"
        image.write_bytes(b"x")

        self.assertEqual(self.resolve(str(image)), image)
        self.assertEqual(self.resolve("a.jpg"), image)     # relative path

    def test_file_inside_the_data_folder_is_allowed(self):
        image = self.data / "outputs" / "b.jpg"
        image.parent.mkdir()
        image.write_bytes(b"x")

        self.assertEqual(self.resolve(str(image)), image)

    def test_file_outside_both_folders_is_refused(self):
        secret = self.outside / "secret.txt"
        secret.write_text("secret")

        self.assertIsNone(self.resolve(str(secret)))

    def test_dot_dot_traversal_is_refused(self):
        secret = self.outside / "secret.txt"
        secret.write_text("secret")

        self.assertIsNone(self.resolve("../outside/secret.txt"))

    def test_symlink_pointing_outside_is_refused(self):
        secret = self.outside / "secret.txt"
        secret.write_text("secret")
        link = self.project / "innocent.jpg"

        try:
            link.symlink_to(secret)
        except OSError:
            self.skipTest("symlinks are not available here")

        self.assertIsNone(self.resolve(str(link)))

    def test_missing_blank_and_non_files_return_none(self):
        self.assertIsNone(self.resolve(None))
        self.assertIsNone(self.resolve(""))
        self.assertIsNone(self.resolve("   "))
        self.assertIsNone(self.resolve("nothing-here.jpg"))
        self.assertIsNone(self.resolve(str(self.project)))   # a folder


if __name__ == "__main__":
    unittest.main()
