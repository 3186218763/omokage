# baicai 皮套资产规格（交付给画师 / 建模师）

舞台只加载一份模型（见 [README.md](README.md)）。本规格是「白菜」皮套的交付验收单：
皮套到货后扩动作词表是纯增量，程序化动作（点头/摇头/歪头）在任何 Cubism 4 模型上都能跑，皮套不阻塞开发。

## 1. 模型本体

- Cubism 4（`.moc3` + `model3.json` + 贴图 + `cdi3.json`）。**cdi3.json 必须交付**——参数映射靠它对照。
- 必须实现的标准参数（id 不同也可以，但要随附一份「实际 id ↔ 标准 id」对照表，用于改 `param-map.json` / `soullink.profile.json`）：

  | 用途 | 标准 id | 最低要求 |
  |---|---|---|
  | 口型 | `ParamMouthOpenY` | 必须（口型跟音频电平） |
  | 嘴形 | `ParamMouthForm` | 必须（笑/平静） |
  | 睁闭眼 | `ParamEyeLOpen` / `ParamEyeROpen` | 必须（含眨眼） |
  | 眯眼笑 | `ParamEyeLSmile` / `ParamEyeRSmile` | 应有 |
  | 眉毛 | `ParamBrowLY` / `ParamBrowRY` | 应有 |
  | 头部三轴 | `ParamAngleX` / `ParamAngleY` / `ParamAngleZ` | 必须（表演情绪 + 程序化动作都写这里） |
  | 身体 | `ParamBodyAngleX` / `ParamBodyAngleZ` | 应有 |
  | 呼吸 | `ParamBreath` | 应有 |

- `model3.json` 的 Groups 里声明 `LipSync`（指向 `ParamMouthOpenY`）与 `EyeBlink`（指向双眼 Open）。
- `physics3.json` 可选但有更好（头发/饰品跟随）。

## 2. 动作素材（motion3.json）＝ 未来扩词表的依据

v1 词表（点头/摇头/歪头）是程序化曲线，**不依赖素材**。以下语义动作为二期词表候选，
每条对应一个闭集词，做了哪条、词表就开到哪条：

| 闭集词（暂定） | 动作 | 备注 |
|---|---|---|
| 挥手 | 打招呼式摆手 | 问候场景高频 |
| 思考 | 手扶下巴/歪头停顿 | 被问到难题时 |
| 拍手 | 双手鼓掌 | 夸用户/起哄 |
| 鞠躬 | 轻鞠躬 | 告别/感谢 |

素材要求：

- 每条 1–2.5 秒，**非循环**，结束姿态回到中性位（程序化底色会在其上继续叠加）。
- 只动身体/手臂/头部大关节；脸部表情参数（眉/眼/嘴）尽量不写死，留给表演情绪层。
- `model3.json` 的 `FileReferences.Motions` 里建组，文件名带语义：`motions/wave.motion3.json` 等。
- 每条配 `FadeIn`/`FadeOut` 0.3–0.5 秒，避免硬切。

## 3. 授权红线

- 原创或已获授权的模型；**不得**使用从录播、粉丝盘、官方物料中提取或逆向的模型。
- 不放入任何官方音频素材。

## 4. 到货验收

```bash
python scripts/check_live2d_assets.py
```

缺 Core / model3 退出码 2。随后对照 `cdi3.json` 核查上表参数，id 不一致时改
`param-map.json` 与 `soullink.profile.json` 的 `target`。动作素材按第 2 节命名入组后，
在 `dialogue/motion.py` 的闭集里扩词并接上播放映射。
