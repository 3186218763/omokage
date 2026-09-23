#!/usr/bin/env python3
"""Headless Style-Bert-VITS2 fine-tune for the Huayin dataset.

Expects an exported SBV2 layout:

    data/sbv2/huayin/
      raw/*.wav
      esd.list

Then, from the Style-Bert-VITS2 repo (after ``python initialize.py --skip_default_models``):

    python /home/mtr/tt/omokage/scripts/train_sbv2.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SBV2_ROOT = Path("/home/mtr/tt/Style-Bert-VITS2")
DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "sbv2" / "huayin"
DEFAULT_MODEL_NAME = "huayin"
DEFAULT_PYTHON = Path("/home/mtr/miniconda3/envs/sbv2/bin/python")


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbv2-root", type=Path, default=DEFAULT_SBV2_ROOT)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument(
        "--python",
        default=str(DEFAULT_PYTHON if DEFAULT_PYTHON.is_file() else sys.executable),
    )
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--save-every-steps", type=int, default=1000)
    parser.add_argument("--num-processes", type=int, default=8)
    parser.add_argument("--val-per-lang", type=int, default=12)
    parser.add_argument("--log-interval", type=int, default=50)
    parser.add_argument("--learning-rate", type=float, default=0.0002)
    parser.add_argument("--lr-decay", type=float, default=0.995)
    parser.add_argument("--warmup-epochs", type=int, default=2)
    parser.add_argument("--gpus", type=int, default=1)
    parser.add_argument(
        "--cuda-visible-devices",
        default="",
        help="Passed as CUDA_VISIBLE_DEVICES. Empty keeps the process default.",
    )
    parser.add_argument(
        "--freeze-bert",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Freeze ZH/JP/EN BERT. Default on: 1.25h cannot safely update the text encoder.",
    )
    parser.add_argument(
        "--bf16",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Train in bfloat16. Also enables Style-Bert-VITS2 grad clipping.",
    )
    parser.add_argument("--yomi-error", default="skip", choices=["raise", "skip", "use"])
    parser.add_argument("--skip-preprocess", action="store_true")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--skip-style-bank", action="store_true")
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--trim", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def run(
    command: list[str],
    *,
    cwd: Path,
    dry_run: bool,
    env: dict[str, str] | None = None,
) -> None:
    pretty = " ".join(command)
    log(f"$ {pretty}")
    if dry_run:
        log("[DRY-RUN] skipped")
        return
    merged = os.environ.copy()
    merged.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    merged.setdefault("HUGGINGFACE_HUB_ENDPOINT", merged["HF_ENDPOINT"])
    merged.setdefault("PYTHONUNBUFFERED", "1")
    if env:
        merged.update(env)
    subprocess.run(command, check=True, cwd=str(cwd), env=merged)


def require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def require_dir(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def sync_dataset(dataset_dir: Path, dest: Path, *, dry_run: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        if dest.is_dir() and not dest.is_symlink():
            # Keep an existing checkout only if it already contains our esd.list.
            existing = dest / "esd.list"
            if existing.is_file():
                log(f"dataset already present: {dest}")
                return
            if dry_run:
                log(f"[DRY-RUN] would replace {dest}")
                return
            shutil.rmtree(dest)
        else:
            if dry_run:
                log(f"[DRY-RUN] would unlink {dest}")
            else:
                dest.unlink()
    log(f"link dataset {dataset_dir} -> {dest}")
    if dry_run:
        return
    try:
        dest.symlink_to(dataset_dir, target_is_directory=True)
    except OSError:
        shutil.copytree(dataset_dir, dest)


def preprocess_command(args: argparse.Namespace) -> list[str]:
    command = [
        args.python,
        "preprocess_all.py",
        "-m",
        args.model_name,
        "-b",
        str(args.batch_size),
        "-e",
        str(args.epochs),
        "-s",
        str(args.save_every_steps),
        "--num_processes",
        str(args.num_processes),
        "--val_per_lang",
        str(args.val_per_lang),
        "--log_interval",
        str(args.log_interval),
        "--yomi_error",
        args.yomi_error,
    ]
    if not args.no_normalize:
        command.append("--normalize")
    if args.trim:
        command.append("--trim")
    if args.freeze_bert:
        command.extend(["--freeze_ZH_bert", "--freeze_JP_bert", "--freeze_EN_bert"])
    return command


def train_command(args: argparse.Namespace, dest: Path) -> list[str]:
    launch = [args.python]
    if args.gpus > 1:
        launch.extend(
            [
                "-m",
                "torch.distributed.run",
                "--nproc_per_node",
                str(args.gpus),
            ]
        )
    launch.extend(
        [
            "train_ms.py",
            "--config",
            str(dest / "config.json"),
            "--model",
            str(dest),
        ]
    )
    return launch


def train_env(args: argparse.Namespace) -> dict[str, str]:
    env: dict[str, str] = {}
    if args.cuda_visible_devices:
        env["CUDA_VISIBLE_DEVICES"] = args.cuda_visible_devices
    return env


def apply_recipe(config_path: Path, args: argparse.Namespace, *, dry_run: bool) -> None:
    """preprocess_all hardcodes bf16 off and leaves the stock LR schedule.

    Patch the written config so the second run is the recipe we actually want.
    """
    log(
        "recipe "
        f"epochs={args.epochs} batch={args.batch_size} gpus={args.gpus} "
        f"bf16={args.bf16} freeze_bert={args.freeze_bert} "
        f"lr={args.learning_rate} decay={args.lr_decay} warmup={args.warmup_epochs}"
    )
    if dry_run:
        log(f"[DRY-RUN] would patch {config_path}")
        return
    if not config_path.is_file():
        raise FileNotFoundError(f"training config not found: {config_path}")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    train = payload.setdefault("train", {})
    train["epochs"] = args.epochs
    train["batch_size"] = args.batch_size
    train["bf16_run"] = bool(args.bf16)
    train["learning_rate"] = args.learning_rate
    train["lr_decay"] = args.lr_decay
    train["warmup_epochs"] = args.warmup_epochs
    train["eval_interval"] = args.save_every_steps
    train["log_interval"] = args.log_interval
    train["freeze_ZH_bert"] = bool(args.freeze_bert)
    train["freeze_JP_bert"] = bool(args.freeze_bert)
    train["freeze_EN_bert"] = bool(args.freeze_bert)
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log(f"patched {config_path}")


def style_bank_command(args: argparse.Namespace) -> list[str]:
    script = PROJECT_ROOT / "scripts" / "build_sbv2_style_bank.py"
    return [
        args.python,
        str(script),
        "--sbv2-root",
        str(args.sbv2_root),
        "--model-name",
        args.model_name,
    ]


def main() -> int:
    args = parse_args()
    sbv2_root = require_dir(args.sbv2_root, "Style-Bert-VITS2 root")
    dataset_dir = require_dir(args.dataset_dir, "exported SBV2 dataset")
    require_file(dataset_dir / "esd.list", "esd.list")
    require_dir(dataset_dir / "raw", "raw wav directory")
    dest = sbv2_root / "Data" / args.model_name

    if not args.skip_sync:
        sync_dataset(dataset_dir, dest, dry_run=args.dry_run)

    if not args.skip_preprocess:
        # pyopenjtalk's dictionary worker has timed out once on this machine.
        last_error: subprocess.CalledProcessError | None = None
        for attempt in range(1, 3):
            try:
                run(preprocess_command(args), cwd=sbv2_root, dry_run=args.dry_run)
                last_error = None
                break
            except subprocess.CalledProcessError as exc:
                last_error = exc
                log(f"preprocess attempt {attempt} failed (exit {exc.returncode})")
        if last_error is not None:
            raise last_error

    if not args.skip_train or not args.skip_style_bank:
        apply_recipe(dest / "config.json", args, dry_run=args.dry_run)

    if not args.skip_train:
        run(
            train_command(args, dest),
            cwd=sbv2_root,
            dry_run=args.dry_run,
            env=train_env(args),
        )

    if not args.skip_style_bank:
        run(style_bank_command(args), cwd=sbv2_root, dry_run=args.dry_run)

    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
