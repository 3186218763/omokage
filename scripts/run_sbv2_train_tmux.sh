#!/usr/bin/env bash
# Style-Bert-VITS2 Huayin training in tmux.
#
#   bash scripts/run_sbv2_train_tmux.sh start
#   bash scripts/run_sbv2_train_tmux.sh attach
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SBV2_ROOT="${SBV2_ROOT:-/home/mtr/tt/Style-Bert-VITS2}"
DATASET_DIR="${DATASET_DIR:-$PROJECT_ROOT/data/sbv2/huayin}"
SESSION="${TMUX_SESSION:-huayin-sbv2-train}"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="${LOG_FILE:-$LOG_DIR/train_huayin_sbv2_v2.log}"
PYTHON="${PYTHON:-/home/mtr/miniconda3/envs/sbv2/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON_FALLBACK:-$SBV2_ROOT/venv/bin/python}"
fi
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

usage() {
  echo "usage: $0 {start|stop|attach|status}" >&2
  exit 2
}

start() {
  mkdir -p "$LOG_DIR"
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session already running: $SESSION"
    tmux ls | grep "$SESSION" || true
    return 0
  fi
  if [[ ! -f "$DATASET_DIR/esd.list" ]]; then
    echo "export dataset first: python scripts/export_sbv2_dataset.py" >&2
    exit 1
  fi
  tmux new-session -d -s "$SESSION" "cd '$PROJECT_ROOT' && export HF_ENDPOINT='${HF_ENDPOINT:-https://hf-mirror.com}' HUGGINGFACE_HUB_ENDPOINT='${HUGGINGFACE_HUB_ENDPOINT:-https://hf-mirror.com}' PYTHONUNBUFFERED=1 && $PYTHON scripts/train_sbv2.py --sbv2-root '$SBV2_ROOT' --dataset-dir '$DATASET_DIR' --python '$PYTHON' --epochs '${EPOCHS:-100}' --batch-size '${BATCH_SIZE:-2}' --gpus '${GPUS:-2}' --cuda-visible-devices '${CUDA_VISIBLE_DEVICES:-0,1}' --save-every-steps '${SAVE_EVERY_STEPS:-1000}' --learning-rate '${LEARNING_RATE:-0.0002}' --lr-decay '${LR_DECAY:-0.995}' --warmup-epochs '${WARMUP_EPOCHS:-2}' --freeze-bert --bf16 2>&1 | tee -a '$LOG_FILE'"
  echo "started $SESSION; log: $LOG_FILE"
}

stop() {
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  echo "stopped $SESSION"
}

attach() {
  tmux attach -t "$SESSION"
}

status() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "running: $SESSION"
  else
    echo "not running: $SESSION"
  fi
  tail -n 20 "$LOG_FILE" 2>/dev/null || true
}

cmd="${1:-start}"
case "$cmd" in
  start) start ;;
  stop) stop ;;
  attach) attach ;;
  status) status ;;
  *) usage ;;
esac
