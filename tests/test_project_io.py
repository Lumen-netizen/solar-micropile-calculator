from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from micropile_app.project_io import (  # noqa: E402
    ProjectDataError,
    build_project_state,
    last_session_path,
    load_project_state,
    save_project_state,
)


class ProjectIoTests(unittest.TestCase):
    def sample_state(self):
        return build_project_state(
            {
                "project_name": "示例项目",
                "pile_type": "微型灌注桩",
                "diameter_mm": "250",
                "consider_self_weight": "1",
            },
            [["耕植土", "0.5", "0", "0", "0", "0", "黏性土或粉土：0.7"]],
            {"微型灌注桩": {"diameter_mm": "250", "embedment": "2.5", "height": "0.5"}},
        )

    def test_project_round_trip_preserves_utf8_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "项目.json"
            save_project_state(self.sample_state(), path)
            loaded = load_project_state(path)
        self.assertEqual(loaded["variables"]["project_name"], "示例项目")
        self.assertEqual(loaded["variables"]["consider_self_weight"], "1")
        self.assertEqual(loaded["soils"][0][0], "耕植土")

    def test_last_session_uses_persistent_app_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"MICROPILE_APP_DATA_DIR": directory}):
            self.assertEqual(last_session_path(), Path(directory) / "last_session.json")

    def test_invalid_project_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps({"format": "wrong", "version": 1}), encoding="utf-8")
            with self.assertRaises(ProjectDataError):
                load_project_state(path)


if __name__ == "__main__":
    unittest.main()
