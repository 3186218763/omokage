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
    background: Path | None
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

    @property
    def background_url(self) -> str | None:
        if self.background is None:
            return None
        relative = self.background.resolve().relative_to(self.root.resolve())
        return "/live2d/" + relative.as_posix()


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


def resolve_background(root: Path, configured: str = "") -> Path | None:
    """背景纯装饰、可选：配置了但缺失时只回 None，不影响 ready。"""
    if configured.strip():
        raw = Path(configured.strip())
        path = raw if raw.is_absolute() else root / raw
        if not _inside(root, path) or not path.is_file():
            return None
        return path
    backgrounds = root / "backgrounds"
    if not backgrounds.is_dir():
        return None
    day = backgrounds / "clubroom-day.jpg"
    if day.is_file():
        return day
    images = sorted(
        p for p in backgrounds.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    return images[0] if images else None


def assess(
    root: Path | None = None,
    configured_model_dir: str = "",
    configured_background: str = "",
) -> Live2DAssets:
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
        background=resolve_background(live2d_root, configured_background),
        missing=tuple(missing),
    )


def main() -> int:
    status = assess()
    if status.ready:
        print(f"live2d ready: {status.model_json}")
        print(f"background: {status.background if status.background else '（无，舞台用渐变兜底）'}")
        return 0
    print("Live2D 资产未就绪。请放入：", file=sys.stderr)
    for item in status.missing:
        print(f"  - {item}", file=sys.stderr)
    print("说明见 resources/live2d/README.md", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
