# P2-13 人设资产卡片化：为「复刻下一位」铺路

## 差距（airi 怎么做）

airi 的人设是一张**可加载的卡**：兼容 SillyTavern CCv3 角色卡格式（`airi/packages/ccc` 解析 description/personality/scenario/system_prompt/first_mes/character_book，`airi/packages/stage-ui/src/stores/modules/airi-card.ts` 组装成 system prompt）。换角色 = 换一张卡，代码不动。

## 我们的现状

人设资产散在三处：`dialogue/persona.py` 的 system prompt 组装、`docs/persona/`（persona-spec / facts-kb.json / fewshot-lines.json）、`model/refs/speaking_style_refs.json`（说话语气参考音库）+ 配置里的声线配方（`configs/huayin_sbv2.yaml`）。这些由 `build_persona_*` 脚本与文档约定粘在一起，**换一个人格需要动代码、文档、配置、脚本四处**。

CONTEXT.md 已有「不推倒重写」的约定，所以本方向不是重写，是**收敛**：先把格式定义出来，现有资产平移进去。

## 方案（若做）

1. **卡片 schema（一个 YAML/JSON 文件 = 一个人物）**，CCv3 兼容子集 + omokage 扩展节：
   - CCv3 字段：name / description / personality / scenario / system_prompt / first_mes / character_book（≈我们的 facts-kb）；
   - omokage 扩展：`few_shot`（≈fewshot-lines）、`speaking_styles`（闭集六类 → 参考音条目）、`voice_recipe`（SBV2 配方引用）、`motion_vocab`（动作词表：皮套资产能播什么）、`language`（中日混用习惯等文本语气指纹项）。
2. **加载器 + 校验**：`dialogue/persona.py` 从卡片组装（卡缺失/非法 → 启动报错，不静默）；`scripts/check_*` 家族加一个卡片 lint（闭集合法、参考音文件存在、词表与皮套资产匹配）。
3. **docs/persona/ 保持研究底稿地位**：卡片是「构建产物或加载源」二选一（建议：卡片为源，研究文档为据——spec 与 eval 不动）。
4. 花音本人**第一个受益者**而非白鼠：先把花音资产平移进卡片格式跑通全链路（eval-set 回归不劣化），才谈第二位。

## 价值与时机

- 「omokage = 虚拟人物重现」如果成立，复刻下一位是迟早的事；届时需要的是「新素材管线 + 新卡片」，而不是改代码。
- CCv3 兼容让社区现成的角色卡生态（成千上万张）成为潜在输入——虽然纪念向的深度（声线克隆、盲测）远超卡片承载，格式兼容只赚不亏。

## 为什么是 P2

- 单人格现状没有痛感，收益在未来第二位；
- 卡片 schema 的字段设计需要一次认真讨论（尤其说话语气/表演闭集如何参数化），不值得在 P0/P1 硬伤未除时占用决策带宽。

## 规模

M（schema 设计讨论 + 加载器 + 花音资产平移 + eval 回归）。
