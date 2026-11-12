"""Where model time goes, from llama-server's own print_timing lines (this launch's log)."""
import re
from pathlib import Path

log = Path(r"C:\Users\prana\Desktop\atlas\.data\logs\llama.log").read_text(encoding="utf-8", errors="replace")
calls = []
keep = None
for line in log.splitlines():
    if m := re.search(r"f_keep = ([\d.]+)", line):
        keep = float(m[1])
    if m := re.search(r"prompt eval time =\s+([\d.]+) ms /\s+(\d+) tokens", line):
        cur = {"p_ms": float(m[1]), "p_tok": int(m[2]), "keep": keep}
    if m := re.search(r"\s eval time =\s+([\d.]+) ms /\s+(\d+) tokens", line):
        cur.update(g_ms=float(m[1]), g_tok=int(m[2]))
        calls.append(cur)
n = len(calls)
P = sum(c["p_ms"] for c in calls) / 1000
G = sum(c["g_ms"] for c in calls) / 1000
print(f"{n} model calls; prompt reading {P:.0f}s ({100 * P / (P + G):.0f}%), generating {G:.0f}s ({100 * G / (P + G):.0f}%)")
print(f"generation speed {sum(c['g_tok'] for c in calls) / G:.0f} tok/s; prompt speed {sum(c['p_tok'] for c in calls) / P:.0f} tok/s")
for lo, hi in ((0, 300), (300, 1500), (1500, 4000), (4000, 99999)):
    b = [c for c in calls if lo <= c["p_tok"] < hi]
    print(f"  calls reading {lo}-{hi} fresh prompt tokens: {len(b):4} ({100 * len(b) / n:.0f}%), {sum(c['p_ms'] for c in b) / 1000:.0f}s")
big = [c for c in calls if c["p_tok"] >= 4000]
print("full re-reads (>=4000 fresh tokens):", len(big), "avg", round(sum(c["p_ms"] for c in big) / max(1, len(big)) / 1000, 1), "s each; f_keep values:",
      sorted({round(c["keep"] or 0, 2) for c in big})[:8])
for lo, hi in ((0, 50), (50, 200), (200, 600), (600, 99999)):
    b = [c for c in calls if lo <= c["g_tok"] < hi]
    print(f"  calls generating {lo}-{hi} tokens: {len(b):4}, {sum(c['g_ms'] for c in b) / 1000:.0f}s")
