from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

FORMAT_ID = "pv-micropile-project"
FORMAT_VERSION = 1
MAX_PROJECT_BYTES = 2 * 1024 * 1024


class ProjectDataError(ValueError):
    pass


def app_data_dir() -> Path:
    override = os.environ.get("MICROPILE_APP_DATA_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "PVSupportMicropileCalculator"


def last_session_path() -> Path:
    return app_data_dir() / "last_session.json"


def build_project_state(
    variables: dict[str, str],
    soils: list[list[str]],
    pile_geometry_values: dict[str, dict[str, str]],
) -> dict[str, Any]:
    return {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "variables": {str(key): str(value) for key, value in variables.items()},
        "soils": [[str(value) for value in row] for row in soils],
        "pile_geometry_values": {
            str(pile_type): {str(key): str(value) for key, value in values.items()}
            for pile_type, values in pile_geometry_values.items()
        },
    }


def save_project_state(state: dict[str, Any], path: Path) -> Path:
    checked = validate_project_state(state)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def load_project_state(path: Path) -> dict[str, Any]:
    path = Path(path)
    if path.stat().st_size > MAX_PROJECT_BYTES:
        raise ProjectDataError("项目文件超过2 MB，可能不是有效的微型桩项目文件")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectDataError(f"无法读取项目文件：{exc}") from exc
    return validate_project_state(value)


def validate_project_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("format") != FORMAT_ID:
        raise ProjectDataError("文件类型不正确，未找到微型桩项目标识")
    if value.get("version") != FORMAT_VERSION:
        raise ProjectDataError(f"暂不支持该项目文件版本：{value.get('version')}")
    variables = value.get("variables")
    soils = value.get("soils")
    geometry = value.get("pile_geometry_values", {})
    if not isinstance(variables, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in variables.items()):
        raise ProjectDataError("项目文件中的输入参数格式无效")
    if not isinstance(soils, list) or len(soils) > 100:
        raise ProjectDataError("项目文件中的土层数据无效")
    if any(not isinstance(row, list) or len(row) != 7 or not all(isinstance(v, str) for v in row) for row in soils):
        raise ProjectDataError("每个土层必须包含7项文本参数")
    if not isinstance(geometry, dict) or any(
        not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items())
        for values in geometry.values()
    ):
        raise ProjectDataError("项目文件中的桩型几何参数无效")
    return {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "saved_at": str(value.get("saved_at", "")),
        "variables": variables,
        "soils": soils,
        "pile_geometry_values": geometry,
    }
