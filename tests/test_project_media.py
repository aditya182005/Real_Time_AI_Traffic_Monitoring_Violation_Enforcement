import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.ui import project_media
from tests.test_ui_pages import PageTestCase, empty_data


class ListingTests(unittest.TestCase):
    def test_lists_only_media_in_the_known_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "my_media").mkdir(parents=True)
            (root / "data" / "samples").mkdir()
            (root / "data" / "my_media" / "a.JPG").write_bytes(b"x")
            (root / "data" / "my_media" / "clip.mp4").write_bytes(b"x")
            (root / "data" / "my_media" / "notes.txt").write_text("no")
            (root / "data" / "samples" / "b.png").write_bytes(b"x")
            (root / "stray.jpg").write_bytes(b"x")

            with mock.patch.object(project_media, "ROOT", root):
                self.assertEqual(list(project_media.images()),
                                 ["my_media/a.JPG", "samples/b.png"])
                self.assertEqual(list(project_media.videos()),
                                 ["my_media/clip.mp4"])

                label, path = next(iter(project_media.images().items()))
                self.assertEqual(project_media.ProjectFile(label, path).getvalue(), b"x")
                self.assertEqual(project_media.ProjectFile(label, path).name, "a.JPG")

    def test_bundled_files_are_found(self):
        self.assertIn("samples/ambulance_1.jpg", project_media.images())
        self.assertIn("videos/demo_all_checks.mp4", project_media.videos())


class UploadPageTests(PageTestCase):
    def test_pictures_from_the_project_can_be_analyzed(self):
        from tests.test_ui_pages import FakeVehicleDetector

        self.start(
            clicks={"run_images"},
            values={"project_images": ["samples/ordinary_1.jpg"]})
        upload = self.ui("upload")

        with mock.patch.object(upload, "_load_models",
                               return_value=(FakeVehicleDetector(), None)):
            upload._images_tab()

        results = self.st.session_state["image_results"]
        self.assertEqual([r["name"] for r in results], ["ordinary_1.jpg"])
        self.assertIsNone(results[0]["error"])
        self.assertEqual(results[0]["vehicles"], 1)

    def test_picking_the_demo_video_shows_expected_results(self):
        self.start(values={"project_video": "videos/demo_all_checks.mp4"})
        self.ui("upload")._video_tab()

        text = self.st.text()
        self.assertIn("Expected results for this demo video", text)
        self.assertIn("demo_all_checks.mp4", text)
        self.assertTrue(self.st.called("button"))

    def test_other_videos_have_no_expected_panel(self):
        self.start(values={"project_video": "videos/traffic.mp4"})
        self.ui("upload")._video_tab()

        self.assertNotIn("Expected results", self.st.text())

    def test_apply_demo_settings_sets_the_controls(self):
        self.start()
        upload = self.ui("upload")

        with mock.patch.object(upload.EmergencyDetector, "available",
                               return_value=True):
            upload._apply_demo_settings()

        state = self.st.session_state
        self.assertEqual(state["signal_mode"], "Cycle red and green")
        self.assertEqual((state["red_s"], state["green_s"]), (6, 6))
        self.assertTrue(state["check_speed"] and state["check_wrong_way"]
                        and state["check_collisions"] and state["video_emergency"])
        self.assertEqual(state["limit_kmh"], 40)
        self.assertIn(state["direction"], upload.DIRECTIONS)
        self.assertEqual(upload.DIRECTIONS[state["direction"]], "down")
        # every key must be one the settings panel really uses
        source = Path(upload.__file__).read_text()

        for key in project_media.DEMO_SETTINGS:
            self.assertIn(f'key="{key}"', source, key)


if __name__ == "__main__":
    unittest.main()
