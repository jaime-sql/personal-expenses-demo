"""The fixed window subtitle is removed and nothing else in the live schema changes."""
import copy, json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from patch_opening_period import patch_dashboard  # noqa: E402
from remove_stale_window import (  # noqa: E402
    STALE_WINDOW, StaleWindowError, assert_only_subtitle_removed, remove_stale_window,
)

FIXTURE = ROOT / "tests" / "fixtures" / "dashboard_schema.json"


def _title_lines(dashboard):
    for page in dashboard["pages"]:
        for item in page["layout"]:
            if item["widget"].get("name") == "title":
                return item["widget"]["multilineTextboxSpec"]["lines"]
    raise AssertionError("title missing")


class RemoveStaleWindowTests(unittest.TestCase):
    def setUp(self):
        self.live = json.loads(FIXTURE.read_text())

    def test_live_schema_loses_only_the_fixed_window(self):
        original_lines = copy.deepcopy(_title_lines(self.live))
        self.assertEqual(original_lines[2].count(STALE_WINDOW), 1)
        patched = remove_stale_window(self.live)
        assert_only_subtitle_removed(self.live, patched)
        lines = _title_lines(patched)
        self.assertNotIn(STALE_WINDOW, "".join(lines))
        self.assertEqual(
            lines[2],
            original_lines[2].replace(STALE_WINDOW, "", 1),
        )
        self.assertIn("(America/El_Salvador).", lines[2])
        self.assertIn("Filters: Year / Month / Day", lines[2])
        self.assertIn("notificaciones_clientes@credicomer.com.sv", lines[2])
        self.assertEqual(lines[0], original_lines[0])
        self.assertEqual(json.dumps(self.live["datasets"]), json.dumps(patched["datasets"]))

    def test_published_period_dashboard_keeps_the_resolved_label(self):
        published, _ = patch_dashboard(self.live)
        published_lines = copy.deepcopy(_title_lines(published))
        self.assertIn("Period / Day", published_lines[2])
        self.assertIn(STALE_WINDOW, published_lines[2])
        corrected = remove_stale_window(published)
        assert_only_subtitle_removed(published, corrected)
        self.assertEqual(
            _title_lines(corrected)[2],
            published_lines[2].replace(STALE_WINDOW, "", 1),
        )
        self.assertIn("Period / Day", _title_lines(corrected)[2])
        self.assertNotIn(STALE_WINDOW, json.dumps(corrected, ensure_ascii=False))
        label = next(
            item for page in corrected["pages"] for item in page["layout"]
            if item["widget"]["name"] == "period_label"
        )
        original_label = next(
            item for page in published["pages"] for item in page["layout"]
            if item["widget"]["name"] == "period_label"
        )
        self.assertEqual(label, original_label)
        self.assertEqual(corrected["datasets"], published["datasets"])

    def test_missing_subtitle_is_refused(self):
        dashboard = copy.deepcopy(self.live)
        lines = _title_lines(dashboard)
        lines[2] = lines[2].replace(STALE_WINDOW, "")
        with self.assertRaises(StaleWindowError):
            remove_stale_window(dashboard)


if __name__ == "__main__":
    unittest.main()
