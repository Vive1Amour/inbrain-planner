# 第 6 步：同样的定位任务下比较（文献校准），每种器件只用它最优的一种检测方案
#   商用条带方案：商用条带只记录后放电（麻醉期放好），刺激靠手持探针按约 1 cm 逐点
#   INBRAIN 主方案：同一片阵列上多点刺激、多点记录，不用额外的刺激器——
#                  麻醉期放好阵列做 CCEP（前部触点单脉冲刺激、后部触点记录，查弓状束连接），标出阳性触点；
#                  醒后先做约 3 min 语言任务、全部触点同时记录高 gamma，只刺激两层都有反应的触点
# 任务统一成“把同一块露出的皮层测一遍”：
#   面积 = 文献典型病例 13.1 平方厘米（Sanai 2008：3281 个皮层位点 / 250 人，约 1 cm 一个点），以及本病例窗口内按 1 cm 网格要测的面积
#   位点真阳性比例用文献值 6%（Sanai 2008 里 94% 位点阴性）
#   CASE=0007 SIDE=R OUT=… ~/.venvs/ds/bin/python -I s6_same_task.py
import os, json, csv, math
CASE = os.environ.get("CASE", "0007"); SIDE = os.environ.get("SIDE", "R")
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work"))
W = os.path.join(WORK, "w" + CASE) + "/"; O = os.environ["OUT"].rstrip("/") + "/"
J = json.load(open(W + "counts_3x7.json", encoding="utf-8")); P = J["params"]; C = J["counts"]
P_TRUE_LIT = 0.06; USE = 0.8          # 文献阳性比例；阵列面积利用率（相邻片有重叠、边缘不规则）
NX, NY, PITCH, NSMALL, REACH = 3, 7, 4.0, 12, 5.0
FOOT = ((NX-1)*PITCH + 2*REACH) * ((NY-1)*PITCH + 2*REACH) / 100.0   # 一片能盖的面积，平方厘米
st_p = P["T_LANG"] + P["OV_PROBE"]; st_a = P["T_LANG"] + P["OV_ARRAY"]
rows = []
for lab, A in [("文献典型病例", 13.1), (f"{CASE} 窗口内", float(C["probe_grid_lang"] + C["probe_grid_motor"]))]:
    rows.append([lab, A, "商用条带方案（条带记录 + 探针 1 cm 刺激）", P["STRIP_PLACE_STD"], round(A, 1), round(A*st_p, 1), 0.0, round(A*st_p + P["STRIP_PLACE_STD"]*P["T_PLACE"], 1), 1.0, 0.0])
    n = math.ceil(A / (FOOT*USE)); per = NX*NY; nc = n*per
    Ea = n*(1 - (1 - P["F_CCEP"])**per)                                  # 醒后还要去的放置数（期望）
    p2 = min(P_TRUE_LIT*P["CCEP_SENS"]/P["F_CCEP"], 1.0)               # CCEP 阳性触点里真阳性的比例
    flag2 = p2*P["SENS"] + (1 - p2)*(1 - P["SPEC"]); stim = nc*P["F_CCEP"]*flag2
    awake = max(Ea - (1 if P["ASLEEP_FIRST"] else 0), 0)*(P["T_PLACE"] + P["T_PASSIVE"]) + stim*st_a
    asleep = n*(P["T_PLACE"] + P["T_CCEP"])
    rows.append([lab, A, "INBRAIN 主方案（阵列多点刺激+多点记录）", n, round(stim, 1), round(awake, 1), round(asleep, 1), round(awake + asleep, 1),
                 round((per + NSMALL)/FOOT, 1), round(nc*P_TRUE_LIT*(1 - P["CCEP_SENS"]*P["SENS"]), 2)])
with open(O + f"{CASE}_同任务对比_文献校准.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["任务", "面积cm2", "方案", "放置次数", "清醒期刺激次数", "清醒期用时min", "麻醉期额外min", "全部min", "每cm2点数", "估计漏掉"]); w.writerows(rows)
for r in rows: print(r)

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
font_manager.fontManager.addfont(FONT); plt.rcParams["font.family"] = font_manager.FontProperties(fname=FONT).get_name(); plt.rcParams["axes.unicode_minus"] = False
fig, ax = plt.subplots(1, 2, figsize=(14, 5.8))
for a, lab in zip(ax, ["文献典型病例", f"{CASE} 窗口内"]):
    rr = [r for r in rows if r[0] == lab]
    b = a.bar(["商用条带方案\n条带记录 + 探针1cm刺激", "INBRAIN 主方案\n阵列多点刺激 + 多点记录"], [r[5] for r in rr], color=["#7A7A7A", "#E8A400"], width=0.55)
    for bb, r in zip(b, rr):
        a.text(bb.get_x() + bb.get_width()/2, r[5], f"清醒期 {r[5]:g} min\n清醒期刺激 {r[4]:g} 次\n麻醉期额外 {r[6]:g} min\n每平方厘米 {r[8]:g} 点\n估计漏掉 {r[9]:g}", ha="center", va="bottom", fontsize=10)
    a.set_title(f"{lab}：把 {rr[0][1]:g} 平方厘米露出皮层测一遍", fontsize=13); a.set_ylabel("清醒期用时（分钟）")
    a.spines[["top", "right"]].set_visible(False); a.set_ylim(0, max(r[5] for r in rr)*1.6)
fig.suptitle("商用条带方案 vs INBRAIN 主方案（同样的定位任务，文献校准：每人约 13 个皮层位点、阳性率 6%，Sanai 2008）", fontsize=13)
fig.text(0.5, -0.12, "INBRAIN 主方案：刺激和记录都在同一片阵列上，不用额外刺激器。麻醉期放好阵列做 CCEP（前部触点单脉冲刺激、后部触点记录，查弓状束连接）标出阳性触点；\n醒后先做 3 min 语言任务、全部触点同时记录，只刺激两层都有反应的触点。假设：CCEP 阳性 40%、CCEP 敏感度 0.85，高 gamma 敏感度/特异度 0.9；每片放置 2 min，第一片麻醉期放好。\n商用条带方案：条带只记录后放电、麻醉期放 2 次；手持探针每点 1.3 min（语言位点 1 + 挪探针、贴标签 0.3）。", ha="center", fontsize=9.5, color="#555")
fig.tight_layout(); fig.savefig(O + f"{CASE}_主方案对比.png", dpi=170, bbox_inches="tight"); print("saved main")
