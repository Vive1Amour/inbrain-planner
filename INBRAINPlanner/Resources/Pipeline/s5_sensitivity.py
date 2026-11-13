# 第 5 步：时间参数敏感性分析，找 INBRAIN 什么时候在清醒期用时上占优
# 读 s3 生成的 counts_3x7.json / counts_1x4.json（数量），用 time_model.py 的同一套公式
#   CASE=0007 SIDE=R OUT=…/UCSF-PDGM-0007_Slicer ~/.venvs/ds/bin/python -I s5_sensitivity.py
import os, sys, json, csv
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from time_model import scenario_times
CASE = os.environ.get("CASE", "0007"); SIDE = os.environ.get("SIDE", "R")
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work"))
W = os.path.join(WORK, "w" + CASE) + "/"; O = os.environ["OUT"].rstrip("/") + "/"
J = json.load(open(W + "counts_3x7.json", encoding="utf-8")); C, P0 = J["counts"], J["params"]
side_txt = "右侧" if SIDE == "R" else "左侧"

def diff(P, key):   # INBRAIN 主方案清醒期 − 标准流程（探针 1 cm 网格）清醒期；负数 = INBRAIN 更短
    o = scenario_times(C, P); return o[key]["awake"] - o["STD"]["awake"]

base = scenario_times(C, P0)
print("默认参数：", {k: round(v["awake"], 1) for k, v in base.items()}, "（清醒期 min）")

# 1 单因素敏感性（龙卷风图）
ranges = [("T_PLACE", 0.5, 4.0, "每次放置时间 min"), ("T_LANG", 0.5, 2.0, "每个语言位点 min"),
          ("OV_PROBE", 0.1, 0.6, "探针每点额外 min"), ("P_TRUE", 0.1, 0.5, "候选里真语言位点比例"),
          ("SENS", 0.75, 0.95, "记录敏感度（特异度同变）"), ("F_CCEP", 0.2, 0.7, "CCEP 阳性比例"),
          ("T_PASSIVE", 1.0, 5.0, "每片任务记录 min"), ("ASLEEP_FIRST", 0, 1, "第一片麻醉期放好（否/是）")]
rows = []
for key in ["MAIN"]:
    for p, lo, hi, lab in ranges:
        vals = []
        for v in (lo, hi):
            P = dict(P0); P[p] = bool(v) if p == "ASLEEP_FIRST" else v
            if p == "SENS": P["SPEC"] = v
            vals.append(diff(P, key))
        rows.append([key, lab, lo, hi, round(vals[0], 1), round(vals[1], 1), round(diff(P0, key), 1)])
with open(O + f"{CASE}_敏感性_单因素.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["情景", "参数", "低值", "高值", "低值时差(min)", "高值时差(min)", "默认差(min)"]); w.writerows(rows)

# 2 双因素临界图：CCEP 阳性比例 × 每次放置时间（情景 C），以及 真语言比例 × 每次放置时间（情景 B）
fc = np.linspace(0.1, 0.8, 36); tp = np.linspace(0.5, 4.0, 36); pt = np.linspace(0.05, 0.6, 36)
Zc = np.array([[diff({**P0, "F_CCEP": a, "T_PLACE": b}, "MAIN") for a in fc] for b in tp])
Zb = np.array([[diff({**P0, "P_TRUE": a, "T_PLACE": b}, "MAIN") for a in pt] for b in tp])

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
font_manager.fontManager.addfont(FONT); plt.rcParams["font.family"] = font_manager.FontProperties(fname=FONT).get_name(); plt.rcParams["axes.unicode_minus"] = False
fig, ax = plt.subplots(1, 3, figsize=(20, 6.2), gridspec_kw=dict(width_ratios=[1.3, 1, 1]))
# 龙卷风（情景 C）
rc = [r for r in rows if r[0] == "MAIN"]; rc.sort(key=lambda r: abs(r[5] - r[4]))
d0 = rc[0][6]
for i, r in enumerate(rc):
    ax[0].barh(i, r[4] - d0, left=d0, color="#4C9BE8"); ax[0].barh(i, r[5] - d0, left=d0, color="#E8774C")
    ax[0].text(min(r[4], r[5]) - 1, i, f"{r[2]:g}" if r[4] < r[5] else f"{r[3]:g}", ha="right", va="center", fontsize=9)
    ax[0].text(max(r[4], r[5]) + 1, i, f"{r[3]:g}" if r[4] < r[5] else f"{r[2]:g}", ha="left", va="center", fontsize=9)
ax[0].set_yticks(range(len(rc))); ax[0].set_yticklabels([r[1] for r in rc], fontsize=10)
ax[0].axvline(0, color="#C00", lw=1.2); ax[0].axvline(d0, color="#333", ls=":", lw=1)
ax[0].set_xlabel("INBRAIN 主方案清醒期 减 商用条带方案清醒期（min），< 0 = INBRAIN 更短")
ax[0].set_title("单因素敏感性（蓝 = 低值，橙 = 高值）", fontsize=13)
for a, Z, xs, xl, t in [(ax[1], Zc, fc, "CCEP 阳性比例（醒后还要刺激的语言触点比例）", "INBRAIN 主方案 vs 商用条带方案"),
                        (ax[2], Zb, pt, "候选里真语言位点比例", "INBRAIN 主方案 vs 商用条带方案")]:
    lim = np.abs(Z).max(); im = a.contourf(xs, tp, Z, levels=21, cmap="RdBu_r", vmin=-lim, vmax=lim)
    cs = a.contour(xs, tp, Z, levels=[0], colors="k", linewidths=2); a.clabel(cs, fmt="持平", fontsize=10)
    a.plot(P0["F_CCEP"] if Z is Zc else P0["P_TRUE"], P0["T_PLACE"], "k*", ms=14)
    a.set_xlabel(xl); a.set_ylabel("每次放置时间 min"); a.set_title(t + "\n（蓝 = INBRAIN 清醒期更短，★ = 默认参数）", fontsize=12)
    fig.colorbar(im, ax=a, label="清醒期差 min")
fig.suptitle(f"UCSF-PDGM-{CASE}（{side_txt}）：INBRAIN 在清醒期用时上什么时候占优", fontsize=15)
fig.tight_layout(); fig.savefig(O + f"{CASE}_敏感性分析.png", dpi=160, bbox_inches="tight")

# 3 文字结论：默认放置时间下，CCEP 阳性比例低于多少 INBRAIN 更短
def breakeven(key, p, grid):
    v = [diff({**P0, p: x}, key) for x in grid]
    s = [x for x, d in zip(grid, v) if d < 0]
    return (min(s), max(s)) if s else None
print("主方案 默认参数清醒期差：", round(diff(P0, "MAIN"), 1), "min；CCEP 阳性比例在", breakeven("MAIN", "F_CCEP", np.linspace(0.01, 1, 100)), "之间时 INBRAIN 更短")
print("主方案 真语言比例在", breakeven("MAIN", "P_TRUE", np.linspace(0.01, 1, 100)), "之间时 INBRAIN 更短")
print("saved", f"{CASE}_敏感性分析.png", f"{CASE}_敏感性_单因素.csv")
