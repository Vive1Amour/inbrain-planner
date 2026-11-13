# 第 7 步：整理结果文件夹，越少越好、不丢数据
# 1 所有表格（CSV、JSON）合并成一个 Excel：<病例>_结果汇总.xlsx，每个文件一个工作表，内容原样（逐行）写入，核对行数后删原文件
# 2 图（PNG）放进 图/，场景和模型（mrb、vtk、nrrd）放进 场景/
# 3 和 UCSF-PDGM-<病例>_nifti/ 原始文件逐字节相同的输入副本删掉（原始数据还在）
#   CASE=0007 OUT=…/UCSF-PDGM-0007_Slicer ~/.venvs/ds/bin/python -I s7_pack.py
import os, csv, json, glob, shutil, filecmp
from openpyxl import Workbook
CASE = os.environ.get("CASE", "0007"); O = os.environ["OUT"].rstrip("/")
DATA = os.path.abspath(os.path.join(O, "..", ".."))                      # UCSF-PDGM_Dataset/
N = os.path.join(DATA, f"UCSF-PDGM-{CASE}_nifti", f"UCSF-PDGM-{CASE}")
XL = os.path.join(O, f"{CASE}_结果汇总.xlsx")

sheets = [  # (工作表名, 文件, 说明)
    ("方案对比", "time_compare.csv", "按规划器目标（每条束刺激 90% + 记录 80%）各方案的放置次数、刺激位点、清醒期/麻醉期/全部用时"),
    ("同任务对比", f"{CASE}_同任务对比_文献校准.csv", "同一块露出皮层测一遍：商用条带方案 vs INBRAIN 各用法（文献校准），清醒期用时、刺激次数、图的密度、估计漏掉"),
    ("敏感性_单因素", f"{CASE}_敏感性_单因素.csv", "每个时间参数取低/高值时，INBRAIN 清醒期减商用条带方案清醒期（负数 = INBRAIN 更短）"),
    ("放置打分_3x7", "placement_scores_3x7.csv", "INBRAIN 3×7 每个候选（中心 × 角度）的单片打分；后面依次是放置计划、各情景时间、窗口内外目标点数"),
    ("放置打分_1x4", "placement_scores_1x4.csv", "商用 1×4 同上"),
    ("数量_3x7", "counts_3x7.json", "时间模型用的数量（每片语言/运动位点数、探针网格位点数）和当时的参数"),
    ("数量_1x4", "counts_1x4.json", "商用 1×4 同上"),
]
# 已有 Excel 就在上面增补/替换对应工作表，不重建；这次没找到任何原表就不动 Excel
from openpyxl import load_workbook as _lw
found = [(n, fn, d) for n, fn, d in sheets if os.path.exists(os.path.join(O, fn))]
done = []
if found:
    wb = _lw(XL) if os.path.exists(XL) else Workbook()
    if "说明" in wb.sheetnames: del wb["说明"]
    info = wb.create_sheet("说明", 0)
    if "Sheet" in wb.sheetnames and wb["Sheet"].max_row <= 1: del wb["Sheet"]
    info.append(["工作表", "原文件", "内容"])
    for name, fn, desc in sheets:
        p = os.path.join(O, fn)
        if os.path.exists(p):
            if name in wb.sheetnames: del wb[name]
            ws = wb.create_sheet(name); n_src = 0
            if fn.endswith(".csv"):
                for row in csv.reader(open(p, encoding="utf-8")):
                    ws.append([float(x) if x.replace(".", "", 1).replace("-", "", 1).isdigit() else x for x in row]); n_src += 1
            else:
                J = json.load(open(p, encoding="utf-8"))
                for sec, d in J.items():
                    for k, v in d.items():
                        ws.append([sec, k, ", ".join(map(str, v)) if isinstance(v, list) else v]); n_src += 1
            done.append((p, n_src, name))
        if name in wb.sheetnames: info.append([name, fn, desc])
    info.append([]); info.append(["图/", "", "所有 PNG：目标区、放置计划、可开颅区域、配准检查、各种对比图、敏感性分析"])
    info.append(["场景/", "", "Slicer 场景（3×7、1×4 各一个 .mrb）、纤维束 .vtk（T1c 空间）、FA .nrrd"])
    info.append(["输入", "", f"原始影像在 UCSF-PDGM_Dataset/UCSF-PDGM-{CASE}_nifti/，bval 在 UCSF-PDGM_Dataset/UCSF-PDGM_DTI.bval"])
    wb.save(XL)
else:
    print("没有新的原表，Excel 不动")

# 核对行数再删原文件
from openpyxl import load_workbook
chk = load_workbook(XL, read_only=True)
for p, n_src, name in done:
    n_xl = sum(1 for _ in chk[name].iter_rows())
    if n_xl == n_src: os.remove(p); print(f"并入 {name}（{n_src} 行），删 {os.path.basename(p)}")
    else: print(f"!! {name} 行数不符（{n_src} vs {n_xl}），保留原文件")

# 图、场景分文件夹
for sub, pats in [("图", ["*.png"]), ("场景", ["*.mrb", "*.vtk", "*.nrrd"])]:
    os.makedirs(os.path.join(O, sub), exist_ok=True)
    for pat in pats:
        for f in glob.glob(os.path.join(O, pat)):
            shutil.move(f, os.path.join(O, sub, os.path.basename(f)))

# 删和原始文件逐字节相同的输入副本
pairs = {f"{CASE}_DWI.nii.gz": N + "_DTI_eddy_noreg.nii.gz", f"{CASE}_DWI.bvec": N + "_DTI_eddy.eddy_rotated_bvecs",
         f"{CASE}_DWI.bval": os.path.join(DATA, "UCSF-PDGM_DTI.bval")}
for k in ["T1c_bias", "FLAIR_bias", "tumor_segmentation", "brain_segmentation"]: pairs[f"{CASE}_{k}.nii.gz"] = N + f"_{k}.nii.gz"
for f, src in pairs.items():
    p = os.path.join(O, f)
    if os.path.exists(p) and os.path.exists(src) and filecmp.cmp(p, src, shallow=False):
        os.remove(p); print("删重复输入", f)
print("整理完：", sorted(os.listdir(O)))

# ================= 4 生成可读的 Markdown：<病例>_结果汇总.md（表格 + 图和场景的超链接） =================
def write_md():
    from openpyxl import load_workbook
    wb = load_workbook(XL, read_only=True)
    def blocks(name):
        if name not in wb.sheetnames: return []
        out, cur = [], []
        for r in wb[name].iter_rows(values_only=True):
            if all(v in (None, "") for v in r):
                if cur: out.append(cur); cur = []
            else: cur.append([v for v in r if v is not None])
        if cur: out.append(cur)
        return out
    def fmt(v):
        if isinstance(v, float): return f"{v:g}"
        return str(v).replace("|", "/")
    def table(rows, limit=None):
        if not rows: return "（无）\n"
        head, body = rows[0], rows[1:]
        if limit: body = body[:limit]
        n = len(head)
        s = "| " + " | ".join(fmt(h) for h in head) + " |\n|" + "---|"*n + "\n"
        for r in body: s += "| " + " | ".join(fmt(x) for x in (list(r) + [""]*n)[:n]) + " |\n"
        return s
    figs = sorted(os.listdir(os.path.join(O, "图"))) if os.path.isdir(os.path.join(O, "图")) else []
    scenes = sorted(os.listdir(os.path.join(O, "场景"))) if os.path.isdir(os.path.join(O, "场景")) else []
    link = lambda sub, f: f"[{f}]({sub}/{f.replace(' ', '%20')})"
    fig = lambda key: next((f for f in figs if key in f), None)
    L = [f"# UCSF-PDGM-{CASE} 放置规划结果汇总\n",
         f"完整数据在 [{os.path.basename(XL)}]({os.path.basename(XL)})（Excel，每个原始表一个工作表）。这里放读得快的版本：主要表格、放置计划、图和场景的链接。\n",
         "## 目录\n", "- [1 主方案对比](#1-主方案对比)\n- [2 同任务对比（文献校准）](#2-同任务对比文献校准)\n- [3 按规划器目标的方案对比](#3-按规划器目标的方案对比)\n"
         "- [4 放置计划](#4-放置计划)\n- [5 敏感性分析](#5-敏感性分析)\n- [6 时间模型用的数量和参数](#6-时间模型用的数量和参数)\n- [7 图](#7-图)\n- [8 场景和模型](#8-场景和模型)\n"]
    L.append("## 1 主方案对比\n")
    if fig("主方案对比"): L.append(f"![主方案对比](图/{fig('主方案对比')})\n")
    sb = blocks("同任务对比")
    if sb:
        rows = [sb[0][0]] + [r for r in sb[0][1:] if "商用条带方案" in str(r[2]) or "CCEP 筛 + 先记录" in str(r[2])]
        L.append("商用条带方案（条带只记录后放电 + 手持探针 1 cm 逐点刺激） vs INBRAIN 主方案（麻醉下 CCEP 筛 + 醒后先记录再刺激）：\n\n" + table(rows))
    tb0 = blocks("方案对比")
    if tb0:
        rows = [tb0[0][0]] + [r for r in tb0[0][1:] if any(k in str(r[0]) for k in ["商用", "INBRAIN 3×7 逐点"])]
        L.append("\n商用条带的数据（两种用法）：\n"
                 "- 实际临床用法 = 商用条带方案：商用条带只记录后放电，麻醉期放约 2 次，刺激靠手持探针（上表和下表的“商用条带方案”）。\n"
                 "- 假设用法：把商用 1×4 当成和 INBRAIN 一样“刺激 + 记录”的阵列，按规划器目标（每条束刺激 90% + 记录 80%）要放的次数和用时；同一用法的 INBRAIN 3×7 放在一起对照。\n\n" + table(rows))
    L.append("\n## 2 同任务对比（文献校准）\n\n把同一块露出皮层测一遍，阳性率按文献 6%（Sanai 2008）。\n")
    if fig("同任务对比"): L.append(f"\n![同任务对比](图/{fig('同任务对比')})\n")
    L.append("\n" + (table(sb[0]) if sb else "（无）\n"))
    L.append("\n## 3 按规划器目标的方案对比\n\n每条束刺激 90% + 记录 80%，一次开颅内。\n")
    if fig("对比_放置次数"): L.append(f"\n![方案对比](图/{fig('对比_放置次数')})\n")
    tb = blocks("方案对比"); L.append("\n" + (table(tb[0]) if tb else "（无）\n"))
    L.append("\n## 4 放置计划\n")
    for dev, key in [("INBRAIN 3×7", "3x7"), ("商用 1×4", "1x4")]:
        bl = blocks(f"放置打分_{key}")
        if not bl: continue
        L.append(f"\n### {dev}\n")
        if fig(f"计划_{key}"): L.append(f"\n![{dev} 放置计划](图/{fig(f'计划_{key}')})\n")
        plan = next((b for b in bl if b and str(b[0][0]) == "plan_step"), None)
        scen = next((b for b in bl if b and str(b[0][0]) == "scenario"), None)
        tgt = next((b for b in bl if b and str(b[0][0]) == "targets_in_window_stim"), None)
        if plan: L.append(f"\n放置顺序（共 {len(plan)-1} 次）：\n\n" + table(plan))
        if scen: L.append("\n各情景时间：\n\n" + table(scen))
        if tgt:
            t = tgt[0]; L.append(f"\n窗口内目标：刺激 {fmt(t[1])} 点、记录 {fmt(t[3])} 点；窗口外够不着：刺激 {fmt(t[5])}、记录 {fmt(t[7])}。\n")
        L.append(f"\n单片打分前 10 名（共 {len(bl[0])-1} 个候选姿态，全部见 Excel）：\n\n" + table(bl[0], 10))
    L.append("\n## 5 敏感性分析\n")
    if fig("敏感性分析"): L.append(f"\n![敏感性分析](图/{fig('敏感性分析')})\n")
    sbk = blocks("敏感性_单因素"); L.append("\n每个参数取低/高值时，INBRAIN 清醒期减商用条带方案清醒期（负数 = INBRAIN 更短）：\n\n" + (table(sbk[0]) if sbk else "（无）\n"))
    L.append("\n## 6 时间模型用的数量和参数\n")
    for key in ["3x7", "1x4"]:
        cb = blocks(f"数量_{key}")
        if cb:
            rows = [["部分", "项", "值"]] + cb[0]
            L.append(f"\n### {key}\n\n" + table(rows))
    L.append("\n## 7 图\n\n" + "".join(f"- {link('图', f)}\n" for f in figs))
    L.append("\n## 8 场景和模型\n\n双击 `.mrb` 用 Slicer 打开；`.vtk` 是 T1c 空间的纤维束。原始影像在 `UCSF-PDGM_Dataset/UCSF-PDGM-" + CASE + "_nifti/`。\n\n" + "".join(f"- {link('场景', f)}\n" for f in scenes))
    md = os.path.join(O, f"{CASE}_结果汇总.md")
    open(md, "w", encoding="utf-8").write("".join(L)); print("写好", md)

write_md()
