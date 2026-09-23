#!/usr/bin/env bash
# Create a conda env and install Style-Bert-VITS2 (training + inference).
set -euo pipefail

CONDA_BASE="${CONDA_BASE:-/home/mtr/miniconda3}"
ENV_NAME="${ENV_NAME:-sbv2}"
SBV2_DIR="${SBV2_DIR:-/home/mtr/tt/Style-Bert-VITS2}"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
PIP_INDEX="${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple}"
export HF_ENDPOINT
export HUGGINGFACE_HUB_ENDPOINT="${HUGGINGFACE_HUB_ENDPOINT:-$HF_ENDPOINT}"

source "${CONDA_BASE}/etc/profile.d/conda.sh"

if ! conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "=== create conda env ${ENV_NAME} (python 3.10) ==="
  conda create -n "${ENV_NAME}" python=3.10 -y
fi

conda activate "${ENV_NAME}"
# This machine's pip.conf adds an unreachable NVIDIA index; keep installs isolated.
export PIP_CONFIG_FILE=/dev/null
export PIP_EXTRA_INDEX_URL=""
unset PIP_INDEX_URL || true
python -m pip install -U pip

echo "=== install ffmpeg ==="
conda install -y -c conda-forge ffmpeg pkg-config

echo "=== install torch 2.3.1 cu121 ==="
python -m pip install "torch==2.3.1" "torchaudio==2.3.1" --index-url https://download.pytorch.org/whl/cu121

echo "=== install Style-Bert-VITS2 requirements ==="
cd "${SBV2_DIR}"
# Official requirements.txt backtracks forever against torch 2.3 (pyannote.audio>=3.1)
# and faster-whisper needs system libav. Pin a known-good training stack instead.
python -m pip install -i "${PIP_INDEX}" --trusted-host mirrors.aliyun.com \
  "setuptools<81" \
  "numpy<2" \
  "librosa==0.9.2" \
  "numba<0.60" \
  pyloudnorm soundfile \
  jieba pypinyin cn2an \
  "nltk<=3.8.1" \
  g2p_en cmudict num2words \
  loguru \
  "huggingface_hub<1" \
  "transformers<4.45" \
  accelerate tensorboard \
  "protobuf==4.25" \
  pyopenjtalk-dict pyworld-prebuilt \
  "pyannote.audio==3.3.2" \
  "pyannote.pipeline<4" \
  "pyannote.core<6" \
  "lightning<2.5" \
  "pytorch-lightning<2.5" \
  "torchmetrics<1.5" \
  GPUtil psutil \
  onnx "onnxruntime-gpu" \
  safetensors scipy \
  "gradio>=4.32,<5" \
  umap-learn \
  fastapi uvicorn pyyaml einops matplotlib

# pyannote may pull numpy 2.x; setuptools 83 drops pkg_resources (librosa 0.9.2).
python -m pip install -i "${PIP_INDEX}" --trusted-host mirrors.aliyun.com \
  "numpy<2" "setuptools<81" "huggingface_hub<1"

# pyopenjtalk lazy-downloads open_jtalk_dic from GitHub; that often times out here.
# Reuse a local copy from the GPT-SoVITS env if present.
OPEN_JTALK_DST="${CONDA_PREFIX}/lib/python3.10/site-packages/pyopenjtalk/open_jtalk_dic_utf_8-1.11"
OPEN_JTALK_SRC="${CONDA_BASE}/envs/gptsovits/lib/python3.10/site-packages/pyopenjtalk/open_jtalk_dic_utf_8-1.11"
if [[ ! -d "${OPEN_JTALK_DST}" && -d "${OPEN_JTALK_SRC}" ]]; then
  echo "=== copy open_jtalk dict from gptsovits env ==="
  cp -a "${OPEN_JTALK_SRC}" "${OPEN_JTALK_DST}"
fi

echo "=== download ZH BERT / WavLM / pretrained G,D,DUR (skip demo voices and JP-Extra) ==="
python - <<'PY'
import json
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download

root = Path(".").resolve()


def download(repo: str, filename: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / filename
    if target.is_file() and target.stat().st_size > 1024:
        print(f"skip {target}")
        return
    print(f"download {repo} {filename} -> {dest}")
    hf_hub_download(repo, filename, local_dir=str(dest))


with open("bert/bert_models.json", encoding="utf-8") as fp:
    models = json.load(fp)
zh = models["chinese-roberta-wwm-ext-large"]
for name in zh["files"]:
    download(zh["repo_id"], name, root / "bert" / "chinese-roberta-wwm-ext-large")

download("microsoft/wavlm-base-plus", "pytorch_model.bin", root / "slm" / "wavlm-base-plus")
for name in ("G_0.safetensors", "D_0.safetensors", "DUR_0.safetensors"):
    download("litagin/Style-Bert-VITS2-1.0-base", name, root / "pretrained")

paths_yml = root / "configs" / "paths.yml"
if not paths_yml.exists():
    shutil.copy(root / "configs" / "default_paths.yml", paths_yml)
print("assets ready")
PY

python - <<'PY'
import torch
print(f"PyTorch {torch.__version__}, CUDA={torch.cuda.is_available()}")
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
import numpy, librosa, pyannote.audio, gradio
print("numpy", numpy.__version__, "librosa", librosa.__version__, "gradio", gradio.__version__)
PY

echo
echo "=== Style-Bert-VITS2 安装完成 ==="
echo "导出数据: python /home/mtr/tt/omokage/scripts/export_sbv2_dataset.py"
echo "训练:     python /home/mtr/tt/omokage/scripts/train_sbv2.py --python $(which python)"
echo "API:      python /home/mtr/tt/omokage/scripts/run_sbv2_api.py"
