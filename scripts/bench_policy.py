"""Benchmark SmolVLA (or any lerobot policy) inference latency.

Usage:
    python scripts/bench_policy.py
    python scripts/bench_policy.py --policy-path $HF_USER/StarkHacks --device mps --iters 20

Prints per-step ms and effective Hz. If Hz >> target FPS, your policy
is NOT the bottleneck. If Hz ~= record-loop Hz, the policy IS the bottleneck.
"""

from __future__ import annotations

import argparse
import os
import time
from contextlib import nullcontext

import numpy as np
import torch

from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.factory import get_policy_class, make_pre_post_processors


def build_raw_observation(policy, device: torch.device) -> dict:
    """Create a fake observation dict matching the policy's declared input features,
    WITHOUT batch dimension and before tokenization. The preprocessor pipeline
    (add batch dim, tokenize, normalize, to-device) will handle the rest.
    """
    obs: dict = {}
    cfg = policy.config

    for key, feat in cfg.input_features.items():
        shape = tuple(feat.shape)

        if "image" in key:
            # preprocessor expects CHW float32 [0,1]
            c, h, w = shape
            obs[key] = torch.rand(c, h, w, dtype=torch.float32)
        else:
            obs[key] = torch.zeros(shape, dtype=torch.float32)

    obs["task"] = "grab screwdriver and put on paper"
    obs["robot_type"] = "so100_follower"
    return obs


def pick_device(preferred: str | None) -> torch.device:
    if preferred:
        return torch.device(preferred)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy-path",
        default=os.environ.get("POLICY_PATH") or f"{os.environ.get('HF_USER', '')}/StarkHacks",
        help="HF repo id or local path to the policy checkpoint.",
    )
    parser.add_argument("--device", default=None, help="cpu | cuda | mps (auto if unset)")
    parser.add_argument("--iters", type=int, default=10, help="Number of timed iterations.")
    parser.add_argument("--warmup", type=int, default=3, help="Warmup iterations (not timed).")
    args = parser.parse_args()

    device = pick_device(args.device)
    print(f"[bench] policy_path = {args.policy_path}")
    print(f"[bench] device      = {device}")

    print("[bench] loading policy config ...")
    cfg: PreTrainedConfig = PreTrainedConfig.from_pretrained(args.policy_path)
    cfg.pretrained_path = args.policy_path
    cfg.device = str(device)
    print(f"[bench] policy type = {cfg.type}")

    print("[bench] loading policy weights ...")
    policy_cls = get_policy_class(cfg.type)
    policy = policy_cls.from_pretrained(args.policy_path, config=cfg)
    policy.to(device)
    policy.eval()

    print("[bench] policy input_features:")
    for k, f in cfg.input_features.items():
        print(f"    {k}: shape={tuple(f.shape)} type={f.type}")
    print(f"[bench] policy output_features: {list(cfg.output_features.keys())}")

    print("[bench] loading preprocessor pipeline (tokenizer, normalizer) ...")
    preprocessor, _postprocessor = make_pre_post_processors(
        policy_cfg=cfg,
        pretrained_path=args.policy_path,
        preprocessor_overrides={
            "device_processor": {"device": str(device)},
        },
    )

    raw_obs = build_raw_observation(policy, device)
    print("[bench] raw obs (pre-processor) shapes:")
    for k, v in raw_obs.items():
        if isinstance(v, torch.Tensor):
            print(f"    {k}: {tuple(v.shape)} {v.dtype}")
        else:
            print(f"    {k}: {v!r}")

    # Many policies (SmolVLA, ACT, DP, ...) cache an action chunk and pop
    # one per select_action call. To measure true inference cost we reset
    # the action queue before every call so each step does a full forward.
    def fresh_select_action():
        if hasattr(policy, "reset"):
            policy.reset()
        obs = preprocessor(dict(raw_obs))
        return policy.select_action(obs)

    # Warmup
    print(f"\n[bench] warmup ({args.warmup} iters) ...")
    for _ in range(args.warmup):
        with torch.inference_mode():
            _ = fresh_select_action()
    if device.type == "cuda":
        torch.cuda.synchronize()
    elif device.type == "mps":
        torch.mps.synchronize()

    # Timed
    print(f"[bench] timing ({args.iters} iters, forced fresh inference each step) ...\n")
    times_ms = []
    amp_ctx = (
        torch.autocast(device_type="cuda")
        if device.type == "cuda"
        else nullcontext()
    )
    for i in range(args.iters):
        t0 = time.perf_counter()
        with torch.inference_mode(), amp_ctx:
            action = fresh_select_action()
        if device.type == "cuda":
            torch.cuda.synchronize()
        elif device.type == "mps":
            torch.mps.synchronize()
        dt_ms = (time.perf_counter() - t0) * 1000.0
        times_ms.append(dt_ms)
        print(f"  step {i:2d}: {dt_ms:7.1f} ms   action shape={tuple(action.shape)}")

    arr = np.array(times_ms)
    print("\n[bench] summary")
    print(f"    mean   : {arr.mean():7.1f} ms   ({1000.0 / arr.mean():.2f} Hz)")
    print(f"    median : {np.median(arr):7.1f} ms   ({1000.0 / np.median(arr):.2f} Hz)")
    print(f"    p90    : {np.percentile(arr, 90):7.1f} ms")
    print(f"    min    : {arr.min():7.1f} ms")
    print(f"    max    : {arr.max():7.1f} ms")

    target_ms = 1000.0 / 30.0
    print(f"\n    target @ 30 Hz = {target_ms:.1f} ms/step")
    n_action_steps = getattr(policy.config, "n_action_steps", 1)
    effective_ms = arr.mean() / max(n_action_steps, 1)
    effective_hz = 1000.0 / effective_ms if effective_ms > 0 else float("inf")
    print(
        f"    n_action_steps = {n_action_steps}  "
        f"(1 inference produces {n_action_steps} actions)"
    )
    print(
        f"    => Amortized per-action cost = {effective_ms:.1f} ms  ({effective_hz:.1f} Hz)"
    )
    if effective_ms > target_ms:
        print(
            "    => Policy IS the bottleneck at 30 Hz.\n"
            "       Fixes: lower record fps, use GPU, increase n_action_steps, smaller model."
        )
    else:
        print("    => Policy is NOT the bottleneck at 30 Hz once amortized.")


if __name__ == "__main__":
    main()
