# Live2D 资产（不入库）

舞台只加载这一份模型。没有「导入任意模型」的界面。

白菜皮套的交付规格见 [`BAICAI-SPEC.md`](BAICAI-SPEC.md)。

## 需要人放进来的文件

1. Cubism Core，同意 Live2D 专有协议后从官网 SDK 取出：

   `resources/live2d/core/live2dcubismcore.min.js`

2. 一份 Cubism 3/4 模型目录，内含 `model3.json`（或 `*.model3.json`）、`moc3`、贴图、`cdi3.json`。

   - 工程占位：`resources/live2d/models/hiyori/`（官方 Hiyori。不改角色设计，不放入官方音频）
   - 白菜皮套：`resources/live2d/models/baicai/`（原创或已授权。不要放入从录播或粉丝盘抽出的官方模型）

3. 舞台背景图（可选），放 `resources/live2d/backgrounds/`：

   当前用的「文化系の部室」四时段变体来自 [みんちりえ](https://min-chi.material.jp)
   （免费素材、商用 OK；素材本身不得再配布，故不入库）。重命名对照：

   | 文件 | 原名 |
   | --- | --- |
   | `clubroom-day.jpg` | 文化系の部室（日中） |
   | `clubroom-evening.jpg` | 文化系の部室（夕方） |
   | `clubroom-night-lights-on.jpg` | 文化系の部室（夜・照明ON） |
   | `clubroom-night-lights-off.jpg` | 文化系の部室（夜・照明OFF） |

两个目录都在时，默认用 `baicai`。也可以在 `configs/config.yaml` 里写相对 Live2D 根目录的路径：

```yaml
live2d:
  model_dir: models/hiyori
  background: backgrounds/clubroom-evening.jpg
```

`model_dir` 必须落在 `resources/live2d/` 里面。`background` 同理；留空时默认取
`backgrounds/clubroom-day.jpg`（没有则按文件名排序取第一张图），没有背景则舞台用 CSS 渐变兜底。

## 检查

```bash
python scripts/check_live2d_assets.py
```

缺 Core 或缺 model3 时退出码 2。Web 仍可聊天，舞台显示「菜」。

## 参数

`param-map.json` 声明嘴、眼、眉、头角要写的参数 id。运行时只写模型里真实存在的 id。嘴部优先 `ParamMouthOpenY`。

`soullink.profile.json` 是按标准 Cubism 参数写的表演配置。换皮套后如果参数 id 不同，对照该模型的 `cdi3.json` 改这份文件里的 `target`。
