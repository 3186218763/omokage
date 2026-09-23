# Huayin 交付权重（Style-Bert-VITS2）

**配方：** [`configs/huayin_sbv2.yaml`](../configs/huayin_sbv2.yaml)

训练完成后，推理资产在 Style-Bert-VITS2 的 `model_assets/huayin/`：

| 文件 | 角色 |
|------|------|
| `config.json` | 超参与 `spk2id` |
| `*.safetensors` | 声学模型 |
| `style_vectors.npy` | 默认风格向量（Neutral） |

本目录保留参考音（对话层说话语气库），**不再**存放 GPT-SoVITS 的 `.ckpt` / `.pth`。

```bash
python scripts/export_sbv2_dataset.py
python scripts/run_sbv2_api.py
python scripts/test_huayin_tts.py "你好，今天也要加油。"
```
