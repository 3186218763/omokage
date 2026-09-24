"""Repeatable local System One evaluation; no dialogue text or credentials in logs.

python -m scripts.eval_character_control --output docs/evaluation/kev-local.json
python -m scripts.eval_character_control --browser-log playback.json --output report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from config import load_config
from dialogue.jev_client import JevClient


# Balanced holdout scenarios. Labels are engineering expectations, not human votes.
SCENARIOS = {
    "日常": [
        ("晚上好呀", "晚上好呀，今天过得怎么样？", ["元气", "日常"]),
        ("你喜欢吃什么", "我想吃点甜的，布丁就很不错。", ["日常", "俏皮"]),
        ("今天有点热", "那记得喝水呀，别一直晒着。", ["日常", "温柔"]),
        ("我刚吃完饭", "吃了什么呀，让我也听听。", ["日常", "元气"]),
        ("陪我聊两句", "好呀，我在这里听着呢。", ["温柔", "日常"]),
        ("我要出门了", "路上小心，回来再聊呀。", ["温柔", "日常"]),
        ("今天终于放假", "太好啦，可以好好休息一下了！", ["元气"]),
        ("我在整理书桌", "一点点整理就好，收拾完会舒服很多。", ["日常", "温柔"]),
        ("该睡觉了", "那就晚安啦，今天也辛苦了。", ["温柔"]),
        ("刚下了一场雨", "雨停后的空气，闻起来应该很舒服吧。", ["日常", "温柔"]),
        ("我泡了茶", "听着就很惬意，慢慢喝呀。", ["日常", "温柔"]),
        ("今天见到了朋友", "真好呀，你们聊了些什么？", ["元气", "日常"]),
        ("我想学做饭", "可以先从简单的开始，我给你加油！", ["元气", "温柔"]),
        ("等车有点无聊", "那我们聊一小会儿，别错过车啦。", ["日常", "俏皮"]),
        ("今天走了好多路", "先坐下来歇歇，脚也辛苦啦。", ["温柔"]),
        ("买到了想看的书", "那今天的小快乐已经到手啦！", ["元气", "日常"]),
        ("准备去买菜", "记得列个单子，不然容易忘东西。", ["日常"]),
        ("我起得很早", "早上好呀，今天也慢慢来！", ["元气", "温柔"]),
        ("窗外有小鸟", "真的呀，安静听一会儿也挺好。", ["日常", "温柔", "惊讶"]),
        ("我回来了", "欢迎回来，先歇一会儿吧。", ["元气", "温柔"]),
    ],
    "沉重": [
        ("最近好累", "先歇一会儿吧，不用一直撑着。", ["温柔"]),
        ("今天工作做错了", "做错一次也不代表你不行，我们慢慢想办法。", ["温柔"]),
        ("我考试没考好", "难过也没关系，今天先照顾好自己。", ["温柔"]),
        ("有点想哭", "想哭就哭一会儿，我在这里听着。", ["温柔"]),
        ("朋友不理我了", "被冷落确实不好受，你愿意说说发生了什么吗？", ["温柔"]),
        ("我觉得自己很没用", "你不用这样判定自己，累了的时候先停一停。", ["温柔"]),
        ("家人生病了", "你一定很担心，也记得照顾一下自己。", ["温柔"]),
        ("今天被批评了", "听着挺委屈的，先把这口气慢慢缓过来。", ["温柔"]),
        ("最近睡不好", "睡不好真的很累，先让今晚轻松一点吧。", ["温柔"]),
        ("我失去了很重要的东西", "这份难受不用急着放下，我愿意听你说。", ["温柔"]),
        ("我很想念以前", "那些记忆对你很重要吧，可以慢慢讲给我听。", ["温柔"]),
        ("今天什么也没做成", "能把今天过完也很不容易，不用急着责怪自己。", ["温柔"]),
        ("我有点孤单", "那我们就安静待一会儿，你不用找话题。", ["温柔"]),
        ("感觉没人理解我", "一定憋了很多话吧，我会认真听。", ["温柔"]),
        ("又被拒绝了", "被拒绝会难受，但这不等于你没有价值。", ["温柔"]),
        ("我担心明天", "先把今晚过好，明天的事我们一点点面对。", ["温柔"]),
        ("我不敢面对失败", "害怕也很正常，不用一下子做到很勇敢。", ["温柔"]),
        ("真希望她还在", "这份想念很珍贵，我只是纪念向的 AI，会认真听你说。", ["温柔"]),
        ("我搞砸了很重要的事", "哎呀，先别急着责怪自己，我们慢慢看还能做什么。", ["温柔"]),
        ("最近总是提不起精神", "不用勉强自己表现得开心，先照顾好身体。", ["温柔"]),
    ],
    "玩笑": [
        ("你是不是又笨了", "才没有呢，这次只是让你先答而已！", ["倔强", "俏皮"]),
        ("你好矮呀", "我才不小呢，你再说一遍试试？", ["倔强", "俏皮"]),
        ("我把零食吃完了", "啊？居然一口也不给我留！", ["惊讶", "倔强", "俏皮"]),
        ("你又偷偷摸鱼", "被你发现啦，不过就一小会儿哦。", ["俏皮"]),
        ("今天你最可爱", "哼，这个还用你说嘛。", ["俏皮", "元气"]),
        ("你肯定打不过我", "还没开始呢，你别得意太早！", ["倔强", "俏皮"]),
        ("猜猜我带了什么", "不会是给我的好吃的吧？", ["俏皮", "惊讶", "元气"]),
        ("我比你聪明", "那这道题就交给聪明的你啦。", ["俏皮"]),
        ("你又输了", "这次不算，我还没认真呢！", ["倔强", "俏皮"]),
        ("快夸夸我", "做得不错嘛，今天给你一朵小红花。", ["俏皮", "元气"]),
        ("我偷偷给你点了赞", "偷偷的也被我知道了，谢谢你呀。", ["俏皮", "温柔"]),
        ("我能一口吃十个布丁", "真的假的，你是布丁收纳盒吗？", ["惊讶", "俏皮"]),
        ("你脸红了吗", "哪有，你不要乱看啦。", ["倔强", "俏皮"]),
        ("你唱歌跑调啦", "那是特别编曲，你懂不懂呀！", ["俏皮", "倔强"]),
        ("我今天运气超好", "分我一点嘛，就一点点！", ["俏皮", "元气"]),
        ("我发现你的秘密了", "什么秘密，你先说说看。", ["俏皮", "惊讶"]),
        ("要不要比赛", "来呀，我可不会轻易认输！", ["元气", "倔强"]),
        ("我才没想你", "哦，真的嘛，那是谁先来聊天的？", ["俏皮"]),
        ("你是不是在装傻", "这个嘛，猜对了也没有奖励哦。", ["俏皮"]),
        ("你的零食归我了", "不行，这个绝对不能让！", ["倔强", "俏皮"]),
    ],
}


def percentile(values: list[float], p: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def summarize_browser(rows: list[dict]) -> dict:
    turns: dict[str, list[dict]] = {}
    for row in rows:
        turns.setdefault(row['turn_id'], []).append(row)
    first_audio, motion_delays = [], []
    for events in turns.values():
        send = next((e['ms'] for e in events if e['event'] == 'send'), None)
        playing = [e for e in events if e['event'] == 'playing']
        if send is not None and playing:
            first_audio.append(playing[0]['ms'] - send)
        for motion in (e for e in events if e['event'] == 'motion_start'):
            start = next((e for e in playing if e.get('index') == motion.get('index')), None)
            if start is not None:
                motion_delays.append(motion['ms'] - start['ms'])
    return dict(turns=len(turns), first_playing_p95_ms=percentile(first_audio, .95),
                motion_delay_p95_ms=percentile(motion_delays, .95),
                note='Browser playing approximates audible start; this is not a loopback audio measurement.')


async def evaluate() -> dict:
    cfg = load_config().jev
    client = JevClient(enabled=True, base_url=cfg.base_url, api_key=cfg.api_key, model=cfg.model,
                       timeout_seconds=cfg.timeout_seconds, min_confidence=cfg.min_confidence,
                       fail_cooldown_seconds=cfg.fail_cooldown_seconds)
    results = []
    try:
        warm_start = time.monotonic()
        warm = await client.ask_messages([{'role': 'user', 'content': '你好'}], '你好呀。')
        warm_ms = (time.monotonic() - warm_start) * 1000
        for scene, samples in SCENARIOS.items():
            for index, (user, prefix, expected) in enumerate(samples):
                start = time.monotonic()
                decision = await client.ask_messages([{'role': 'user', 'content': user}], prefix)
                results.append(dict(id=f'{scene}-{index + 1:02}', scene=scene,
                    elapsed_ms=round((time.monotonic() - start) * 1000, 2),
                    decision=asdict(decision) if decision else None, reason=client.last_reason,
                    expected=expected, acceptable=decision.emotion in expected if decision else None))
    finally:
        await client.aclose()
    accepted = [r for r in results if r['decision']]
    elapsed = [r['elapsed_ms'] for r in results]
    return dict(model=cfg.model, min_confidence=cfg.min_confidence, timeout_seconds=cfg.timeout_seconds,
        warmup_ms=warm_ms, warmup_accepted=warm is not None,
        summary=dict(total=len(results), accepted=len(accepted),
                     expected_match=sum(r['acceptable'] is True for r in results),
                     p50_ms=statistics.median(elapsed), p95_ms=percentile(elapsed, .95)),
        note='Engineering expectations only; not human blind review. No LLM or TTS in this measurement.', results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--browser-log', type=Path)
    args = parser.parse_args()
    report = summarize_browser(json.loads(args.browser_log.read_text())) if args.browser_log else asyncio.run(evaluate())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report.get('summary', report), ensure_ascii=False))


if __name__ == '__main__':
    main()
