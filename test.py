import time, torch
from lerobot.policies.factory import make_policy
# load your policy the same way lerobot-record does, then:
for _ in range(5):
    t = time.perf_counter()
    with torch.no_grad():
        policy.select_action(obs)  # obs = a cached observation dict
    print(f"{(time.perf_counter()-t)*1000:.1f} ms")
