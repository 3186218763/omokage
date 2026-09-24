# P2-13 人设资产卡片化：为「复刻下一位」铺路

**状态（2026-09-23，本地工作树）：花音卡片已接线。** `configs/huayin_card.yaml` 引用原样迁移的 `huayin_prompt.txt`、事实/few-shot 与声线配方；`dialogue.character_card.load_character_card()` 校验并供 `get_system_prompt()` 读取，`scripts/check_character_card.py` 可独立检查。尚未做第二人物切换或 CCv3 兼容。SBV2 仍锁定花音声线，参考音库不能被当作已实现的声学风格切换。

## 差距（airi 怎么做）

airi 的人设是一张**可加载的卡**：兼容 SillyTavern CCv3 角色卡格式（`airi/packages/ccc` 解析 description/personality/scenario/system_prompt/first_mes/character_book，`airi/packages/stage-ui/src/stores/modules/airi-card.ts` 组装成 system prompt）。换角色 = 换一张卡，代码不动。

## 我们的现状

人设资产散在 `dialogue/persona.py`、`docs/persona/`、`model/refs/speaking_style_refs.json` 和声线配方（`configs/huayin_sbv2.yaml`）。换人物需要协调代码、资料与训练/推理资产；单张文本卡不能解决模型权重与授权问题。

CONTEXT.md 已有「不推倒重写」的约定，所以本方向不是重写，是**收敛**：先把格式定义出来，现有资产平移进去。

## 方案（若做）

1. **卡片 schema（一个 YAML/JSON 文件 = 一个人物的文本配置）**，可借鉴 CCv3 字段，但只有通过兼容测试后才宣称 CCv3 兼容：
   - CCv3 字段：name / description / personality / scenario / system_prompt / first_mes / character_book（≈我们的 facts-kb）；
   - omokage 扩展：`few_shot`、文本说话语气闭集、`voice_recipe`（SBV2 配方/权重的引用，不是模型本身）、`motion_vocab`、`language`；参考音条目只作为研究/训练资产，直到推理 API 真的支持对应控制。
2. **加载器 + 校验**：`dialogue/persona.py` 从卡片组装（卡缺失/非法 → 启动报错，不静默）；`scripts/check_*` 家族加一个卡片 lint（闭集合法、参考音文件存在、词表与皮套资产匹配）。
3. **docs/persona/ 保持研究底稿地位**：卡片是「构建产物或加载源」二选一（建议：卡片为源，研究文档为据——spec 与 eval 不动）。
4. 花音本人**第一个受益者**而非白鼠：先把花音资产平移进卡片格式跑通全链路（eval-set 回归不劣化），才谈第二位。

## 价值与时机

- 「omokage = 虚拟人物重现」如果成立，复刻下一位是迟早的事；届时需要的是「新素材管线 + 新卡片」，而不是改代码。
- CCv3 字段可以减少文本资料迁移成本，但兼容解析、扩展字段、授权和安全边界会增加维护成本；是否要承诺格式兼容，应由实际导入需求决定。

## 为什么是 P2

- 单人格现状没有痛感，收益在未来第二位；
- 卡片 schema 的字段设计需要一次认真讨论（尤其说话语气/表演闭集如何参数化），不值得在 P0/P1 硬伤未除时占用决策带宽。

## 规模

M（schema 设计讨论 + 加载器 + 花音资产平移 + eval 回归）。
