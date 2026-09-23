"""检查本地 Live2D 资产是否齐：Cubism Core + 一份 model3。

模型与 Core 不入库。缺资产时退出码 2，Web 仍可纯聊天。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE2D_ROOT = PROJECT_ROOT / "resources" / "live2d"
CORE_RELATIVE = Path("core") / "live2dcubismcore.min.js"


@dataclass(frozen=True)
class Live2DAssets:
    root: Path
    ready: bool
    model_dir: Path | None
    model_json: Path | None
    core_path: Path
    missing: tuple[str, ...]

    @property
    def model_url(self) -> str | None:
        if self.model_json is None:
            return None
        relative = self.model_json.resolve().relative_to(self.root.resolve())
        return "/live2d/" + relative.as_posix()

    @property
    def core_url(self) -> str:
        return "/live2d/core/live2dcubismcore.min.js"


def _model_jsons(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    named = directory / "model3.json"
    if named.is_file():
        return [named]
    return sorted(directory.glob("*.model3.json"))


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def resolve_model_dir(root: Path, configured: str = "") -> Path | None:
    """空配置时优先 baicai，否则 hiyori。配置路径必须落在 root 内。"""
    if configured.strip():
        raw = Path(configured.strip())
        path = raw if raw.is_absolute() else root / raw
        if not _inside(root, path):
            return None
        return path if _model_jsons(path) else None
    for name in ("baicai", "hiyori"):
        candidate = root / "models" / name
        if _model_jsons(candidate):
            return candidate
    return None


def assess(root: Path | None = None, configured_model_dir: str = "") -> Live2DAssets:
    live2d_root = (root or DEFAULT_LIVE2D_ROOT).resolve()
    core_path = live2d_root / CORE_RELATIVE
    missing: list[str] = []
    if not core_path.is_file():
        missing.append(str(core_path))
    model_dir = resolve_model_dir(live2d_root, configured_model_dir)
    model_json = _model_jsons(model_dir)[0] if model_dir else None
    if model_json is None:
        if configured_model_dir.strip():
            missing.append(
                f"{configured_model_dir} 下的 model3.json 或 *.model3.json"
                "（且目录必须在 Live2D 根目录内）"
            )
        else:
            missing.append(
                str(live2d_root / "models" / "hiyori" / "*.model3.json")
            )
    return Live2DAssets(
        root=live2d_root,
        ready=not missing,
        model_dir=model_dir,
        model_json=model_json,
        core_path=core_path,
        missing=tuple(missing),
    )


def main() -> int:
    status = assess()
    if status.ready:
        print(f"live2d ready: {status.model_json}")
        return 0
    print("Live2D 资产未就绪。请放入：", file=sys.stderr)
    for item in status.missing:
        print(f"  - {item}", file=sys.stderr)
    print("说明见 resources/live2d/README.md", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
