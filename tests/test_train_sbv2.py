import json
import sys
from pathlib import Path

from scripts import train_sbv2 as train


def test_preprocess_command_includes_normalize_and_skips_jp_extra(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["train_sbv2.py", "--python", "/opt/sbv2/bin/python", "--model-name", "huayin"],
    )
    args = train.parse_args()
    command = train.preprocess_command(args)
    assert command[:5] == [
        "/opt/sbv2/bin/python",
        "preprocess_all.py",
        "-m",
        "huayin",
        "-b",
    ]
    assert "--normalize" in command
    assert "--use_jp_extra" not in command
    assert "--yomi_error" in command
    assert "--freeze_ZH_bert" in command
    assert "--freeze_JP_bert" in command
    assert "--freeze_EN_bert" in command
    assert args.batch_size == 4
    assert args.epochs == 100
    assert args.bf16 is True
    assert args.freeze_bert is True


def test_train_command_points_at_dataset_config(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["train_sbv2.py", "--python", "python"])
    args = train.parse_args()
    dest = tmp_path / "Data" / "huayin"
    command = train.train_command(args, dest)
    assert command[1] == "train_ms.py"
    assert command[command.index("--config") + 1] == str(dest / "config.json")
    assert command[command.index("--model") + 1] == str(dest)


def test_train_command_uses_torchrun_for_multiple_gpus(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["train_sbv2.py", "--python", "python", "--gpus", "2"]
    )
    args = train.parse_args()
    command = train.train_command(args, Path("/tmp/Data/huayin"))
    assert command[1:4] == ["-m", "torch.distributed.run", "--nproc_per_node"]
    assert command[4] == "2"
    assert "train_ms.py" in command


def test_apply_recipe_writes_bf16_and_schedule(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"train": {"epochs": 50, "bf16_run": false, "lr_decay": 0.99995}}',
        encoding="utf-8",
    )
    namespace = train.argparse.Namespace(
        epochs=100,
        batch_size=2,
        gpus=2,
        bf16=True,
        freeze_bert=True,
        learning_rate=0.0002,
        lr_decay=0.995,
        warmup_epochs=2,
        save_every_steps=1000,
        log_interval=50,
    )
    train.apply_recipe(config_path, namespace, dry_run=False)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["train"]["bf16_run"] is True
    assert payload["train"]["epochs"] == 100
    assert payload["train"]["freeze_ZH_bert"] is True
    assert payload["train"]["lr_decay"] == 0.995
    assert payload["train"]["warmup_epochs"] == 2


def test_sync_dataset_symlinks_exported_layout(tmp_path):
    source = tmp_path / "export"
    (source / "raw").mkdir(parents=True)
    (source / "esd.list").write_text("a.wav|花音|ZH|你好\n", encoding="utf-8")
    dest = tmp_path / "Data" / "huayin"
    train.sync_dataset(source, dest, dry_run=False)
    assert dest.is_symlink() or (dest / "esd.list").is_file()
    assert (dest / "esd.list").read_text(encoding="utf-8").startswith("a.wav")
