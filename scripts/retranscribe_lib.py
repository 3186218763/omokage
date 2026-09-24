"""Retranscribe 脚本共用的 GPU 分片跑批骨架。

fork 起进程、round-robin 分 shard、mp.Queue 回收结果与断点续跑循环。
各脚本只保留自己的选片逻辑与解码参数（transcribe_one / target 选择）。
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path


def load_cuda_model(model_size: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device="cuda", compute_type="float16")


def segment_metrics(materialized: list) -> dict:
    """时长加权 avg_logprob 与峰值 no_speech / compression 指标。"""
    weighted = 0.0
    wsum = 0.0
    no_speech: list[float] = []
    compression: list[float] = []
    for s in materialized:
        w = max(
            float(getattr(s, "end", 0.0) or 0.0) - float(getattr(s, "start", 0.0) or 0.0),
            0.01,
        )
        lp = getattr(s, "avg_logprob", None)
        if lp is not None:
            weighted += float(lp) * w
            wsum += w
        ns = getattr(s, "no_speech_prob", None)
        if ns is not None:
            no_speech.append(float(ns))
        cr = getattr(s, "compression_ratio", None)
        if cr is not None:
            compression.append(float(cr))
    return {
        "avg_logprob": weighted / wsum if wsum else None,
        "max_no_speech_probability": max(no_speech) if no_speech else None,
        "max_compression_ratio": max(compression) if compression else None,
    }


def worker(
    worker_id: int,
    gpu_id: str,
    model_size: str,
    paths: list[str],
    out_q,
    transcribe_one: Callable,
) -> None:
    try:
        os.environ["CUDA_VISIBLE_DEVICES"] = gpu_id
        model = load_cuda_model(model_size)
        for p in paths:
            out_q.put(("result", worker_id, transcribe_one(model, Path(p))))
    except BaseException:
        out_q.put(("error", worker_id, traceback.format_exc()))
    finally:
        out_q.put(("done", worker_id, None))


def shard_round_robin(paths: list, gpus: list[str]) -> list[list[str]]:
    shards: list[list[str]] = [[] for _ in gpus]
    for i, p in enumerate(paths):
        shards[i % len(gpus)].append(str(p))
    return shards


def run_sharded(
    jobs: list,
    gpus: list[str],
    model_size: str,
    transcribe_one: Callable,
    on_result: Callable[[dict], None],
    *,
    progress_every: int = 50,
) -> None:
    """把 jobs 分片跑完；on_result 逐条回调（缓存写入方），出错打 stderr。"""
    shards = shard_round_robin(jobs, gpus)
    out_q: mp.Queue = mp.Queue()
    procs = [
        mp.Process(
            target=worker,
            args=(i, gpu, model_size, shard, out_q, transcribe_one),
            daemon=True,
        )
        for i, (gpu, shard) in enumerate(zip(gpus, shards))
        if shard
    ]
    for p in procs:
        p.start()

    pending = len(jobs)
    done_procs: set[int] = set()
    try:
        while pending > 0 or len(done_procs) < len(procs):
            kind, wid, payload = out_q.get(timeout=600)
            if kind == "result":
                pending -= 1
                on_result(payload)
                if pending % progress_every == 0:
                    print(f"  progress: {len(jobs) - pending}/{len(jobs)}", flush=True)
            elif kind == "error":
                print(f"worker {wid} error:\n{payload}", file=sys.stderr, flush=True)
            elif kind == "done":
                done_procs.add(wid)
    finally:
        for p in procs:
            p.join(timeout=30)
