# 第 4 步：给 s3 的截图加图例和关键数字，画三方案对比柱状图
# 用 ~/.venvs/ds 的 Python（需要 Pillow、matplotlib），不在 Slicer 里跑
#   CASE=0007 SIDE=R OUT=…/UCSF-PDGM-0007_Slicer ~/.venvs/ds/bin/python -I s4_legend.py
import csv, os, json
from PIL import Image, ImageDraw, ImageFont, ImageChops
CASE = os.environ.get("CASE", "0007"); SIDE = os.environ.get("SIDE", "R")
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work"))
W = os.path.join(WORK, "w" + CASE) + "/"
O = os.environ["OUT"].rstrip("/") + "/"
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
f_t, f_b, f_s = ImageFont.truetype(FONT, 46), ImageFont.truetype(FONT, 32), ImageFont.truetype(FONT, 27)

rows = list(csv.reader(open(W + "time_compare.csv", encoding="utf-8")))
T = {r[0]: r for r in rows[1:]}
k37 = "INBRAIN 主方案（阵列多点刺激+多点记录）"
HDR = rows[0]; col = {h: i for i, h in enumerate(HDR)}
# 窗口内外目标点数：placement_scores_3x7.csv 最后一行
last = [r for r in csv.reader(open(W + "placement_scores_3x7.csv", encoding="utf-8")) if r and r[0] == "targets_in_window_stim"][0]
n_in_s, n_in_r, n_out_s, n_out_r = last[1], last[3], last[5], last[7]
side_txt = "右侧" if SIDE == "R" else "左侧"

def crop(im, bg=(255, 255, 255), pad=30):
    bb = ImageChops.difference(im.convert("RGB"), Image.new("RGB", im.size, bg)).getbbox()
    return im if not bb else im.crop((max(bb[0]-pad, 0), max(bb[1]-pad, 0), min(bb[2]+pad, im.width), min(bb[3]+pad, im.height)))

def compose(src, dst, title, items, notes, bg=(255, 255, 255)):
    if not os.path.exists(W + src): print("缺", src); return
    im = crop(Image.open(W + src).convert("RGB"), bg)
    pw = 760; H = max(im.height, 140 + 54*len(items) + 44*len(notes) + 80)
    can = Image.new("RGB", (im.width + pw, H + 90), (255, 255, 255))
    can.paste(im, (0, 90 + (H - im.height)//2)); d = ImageDraw.Draw(can)
    d.text((30, 22), title, font=f_t, fill=(20, 20, 20))
    x0, y = im.width + 30, 130
    d.text((x0, y - 10), "图例", font=f_b, fill=(20, 20, 20)); y += 50
    for kind, col, label in items:
        if kind == "dot": d.ellipse((x0, y+6, x0+26, y+32), fill=col, outline=(60, 60, 60))
        elif kind == "big": d.ellipse((x0-2, y+2, x0+30, y+34), fill=col, outline=(60, 60, 60))
        elif kind == "line": d.line((x0-4, y+19, x0+34, y+19), fill=col, width=7)
        elif kind == "ring": d.ellipse((x0, y+4, x0+28, y+32), outline=col, width=4)
        elif kind == "box": d.rectangle((x0, y+6, x0+28, y+32), fill=col, outline=(60, 60, 60))
        d.text((x0 + 50, y), label, font=f_s, fill=(30, 30, 30)); y += 54
    y += 20
    if notes:
        d.text((x0, y), "关键数字", font=f_b, fill=(20, 20, 20)); y += 50
        for n in notes: d.text((x0, y), n, font=f_s, fill=(30, 30, 30)); y += 44
    can.save(O + dst); print("saved", dst)

base = [
    ("big", (0, 0, 0), "入口点（可开颅区域里综合评分最高）"),
    ("ring", (40, 40, 40), "开颅窗口边缘"),
    ("dot", (230, 25, 25), "刺激目标：纤维束入口（离病灶 ≤15 mm）"),
    ("dot", (25, 125, 255), "记录目标：浸润带上方皮层 + 刺激点周围"),
    ("dot", (155, 155, 155), "这个开颅够不着的目标"),
    ("box", (215, 25, 25), "肿瘤核心（强化 + 坏死）"),
    ("box", (175, 200, 255), "FLAIR 浸润带（半透明）"),
    ("line", (40, 90, 255), "皮质脊髓束 CST（运动）"),
    ("line", (25, 190, 65), "弓状束/上纵束 AF/SLF（语言，近似）"),
]
compose(f"{CASE}_目标区_红刺激_蓝记录.png", f"{CASE}_目标区_红刺激_蓝记录.png",
        f"UCSF-PDGM-{CASE}（{side_txt}）：开颅窗口内的刺激/记录目标", base,
        [f"窗口内：刺激 {n_in_s} 点，记录 {n_in_r} 点", f"窗口外够不着：刺激 {n_out_s} / 记录 {n_out_r}"])
for tag, k, extra, name in [("3x7", "INBRAIN 主方案（阵列多点刺激+多点记录）", [("big", (255, 205, 0), "大触点（刺激 + 记录），3×7，间距 4 mm"), ("dot", (255, 255, 255), "小触点（只记录），2×6")], "INBRAIN 3×7 阵列")]:
    compose(f"{CASE}_计划_{tag}_双色目标+开颅窗口.png", f"{CASE}_计划_{tag}_双色目标+开颅窗口.png",
            f"UCSF-PDGM-{CASE}：{name}放置计划", base + extra,
            [f"放置 {T[k][col['放置次数']]} 次", f"刺激位点：语言 {T[k][col['语言刺激位点']]} / 运动 {T[k][col['运动刺激位点']]}",
             f"主方案：清醒期 {T[k][col['清醒期用时min']]} min，全部 {T[k][col['全部定位用时min']]} min", "覆盖目标：每条束刺激 90%，记录 80%"])
compose(f"{CASE}_可开颅区域_入口评分.png", f"{CASE}_可开颅区域_入口评分.png",
        f"UCSF-PDGM-{CASE}（{side_txt}）：哪里能开颅（从肿瘤一侧看）", [
            ("big", (0, 0, 0), "选中的入口点"),
            ("dot", (25, 190, 50), "好：评分前 15%"),
            ("dot", (240, 215, 50), "中：评分 50–85%"),
            ("dot", (255, 140, 25), "差：评分后 50%"),
            ("dot", (90, 90, 90), "不开：对侧 / 中线旁 12 mm / 颅底面 / 后下部"),
            ("box", (215, 25, 25), "肿瘤核心"),
            ("line", (40, 90, 255), "CST"), ("line", (25, 190, 65), "AF/SLF（近似）")],
        ["评分 = 窗口能露出的目标 − 通道长度", "      − 通道穿过纤维束 − 入口压在功能区", "      − 低位外侧、靠近中线扣分",
         "颅底面 = 皮层法向朝下（额底、颞底、小脑）"])
compose(f"{CASE}_轴位_配准检查_T1c+FA+纤维束.png", f"{CASE}_轴位_配准检查_T1c+FA.png",
        f"UCSF-PDGM-{CASE}：弥散 FA 叠在 T1c 上（配准检查）", [
            ("box", (128, 128, 128), "背景：T1 增强（T1c）"),
            ("box", (230, 230, 230), "前景 50%：FA"),
            ("box", (230, 230, 60), "坏死（标签 1）"),
            ("box", (220, 70, 70), "强化环（标签 4）"),
            ("box", (90, 140, 230), "水肿/浸润带（标签 2）")],
        ["脑轮廓、脑室、胼胝体对齐 → 配准可用", "图像左侧 = 病人右侧（放射学方向）"], bg=(0, 0, 0))

real_base = [("box", (237, 230, 210), "颅骨（示意：脑表面外 4–11 mm；MRI 已去颅骨）"),
             ("box", (237, 199, 189), "皮层（T1c 去掉脑脊液后的表面，有脑回脑沟）"),
             ("big", (0, 0, 0), "入口点"), ("big", (255, 205, 0), "电极片大触点"), ("dot", (255, 255, 255), "小触点"),
             ("dot", (230, 25, 25), "刺激目标"), ("dot", (25, 125, 255), "记录目标")]
compose(f"{CASE}_真实_开颅位置.png", f"{CASE}_真实_开颅位置.png", f"UCSF-PDGM-{CASE}（{side_txt}）：开颅位置（骨窗半径 35 mm）",
        real_base[:3] + [("box", (230, 200, 60), "右下角小人：看前后、上下方向")],
        ["方位点：A 前额  B 头顶  C 枕部（后脑）", "          D 太阳穴  E 耳朵上方（肿瘤这一侧）", "骨窗中心 = 入口点（可开颅区域里评分最高）", "骨窗在太阳穴后上方、耳朵上方，不在太阳穴"])
for tag, nm in [("3x7", "INBRAIN 3×7")]:
    compose(f"{CASE}_真实_手术视角_{tag}.png", f"{CASE}_真实_手术视角_{tag}.png", f"UCSF-PDGM-{CASE}：手术视角（从骨窗往里看），{nm}",
            real_base if tag == "3x7" else real_base[:3] + [("big", (255, 50, 255), "条带触点")] + real_base[5:], ["电极片可以伸到骨窗边缘下面 15 mm", "方位点：A 前额 B 头顶 C 枕部 D 太阳穴 E 耳上方"])
    compose(f"{CASE}_真实_内部结构_{tag}.png", f"{CASE}_真实_内部结构_{tag}.png", f"UCSF-PDGM-{CASE}：内部结构（皮层半透明），{nm}",
            [("box", (237, 199, 189), "皮层（半透明）"), ("box", (215, 25, 25), "肿瘤核心"), ("box", (175, 200, 255), "FLAIR 浸润带"),
             ("line", (40, 90, 255), "CST（运动）"), ("line", (25, 190, 65), "AF/SLF（语言，近似）"), ("big", (0, 0, 0), "入口点"),
             ("big", (255, 205, 0) if tag == "3x7" else (255, 50, 255), "电极片触点")], [])

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
font_manager.fontManager.addfont(FONT); plt.rcParams["font.family"] = font_manager.FontProperties(fname=FONT).get_name(); plt.rcParams["axes.unicode_minus"] = False
order = [r[0] for r in rows[1:] if r]
short = {"INBRAIN 主方案（阵列多点刺激+多点记录）": "INBRAIN 主方案\n阵列多点刺激+多点记录", "商用条带方案（条带记录+探针1cm刺激）": "商用条带方案\n本病例窗口内", "商用条带方案·文献典型病例（13位点）": "商用条带方案\n文献典型病例"}
labs = [short.get(k, k) for k in order]
cols = ["#E8A400" if k.startswith("INBRAIN") else "#7A7A7A" for k in order]
fig, ax = plt.subplots(1, 3, figsize=(17, 5.4))
for a, cname, t, unit in [(ax[0], "清醒期用时min", "清醒期用时", "min"), (ax[1], "全部定位用时min", "全部定位用时（含麻醉期 CCEP）", "min"), (ax[2], "语言刺激位点", "清醒期要刺激的语言位点", "数量")]:
    vals = [float(T[k][col[cname]]) for k in order]; b = a.bar(labs, vals, color=cols, width=0.6)
    for bb, v in zip(b, vals): a.text(bb.get_x() + bb.get_width()/2, v, f"{v:g}", ha="center", va="bottom", fontsize=11)
    a.set_title(t, fontsize=14); a.set_ylabel(unit); a.spines[["top", "right"]].set_visible(False); a.tick_params(axis="x", labelsize=9.5)
    if cname == "清醒期用时min":
        WINm = json.load(open(W + "counts_3x7.json", encoding="utf-8"))["params"]["AWAKE_WINDOW"]
        a.axhline(WINm, color="#C00", ls="--", lw=1.2); a.text(len(order)-0.5, WINm, f"清醒窗口 {WINm:g} min", color="#C00", ha="right", va="bottom", fontsize=10)
fig.suptitle(f"补充：UCSF-PDGM-{CASE}（{side_txt}）按规划器目标（每条束刺激 90% + 记录 80%），INBRAIN 主方案 vs 商用条带方案", fontsize=13)
fig.text(0.5, -0.12, "商用条带方案·文献典型：Sanai 2008（250 例）平均每人约 13 个皮层刺激位点；本病例窗口内按 1 cm 网格要测的更多\nINBRAIN 主方案：麻醉期 CCEP 筛（阳性 40%，每片 4 min），醒后每片先 3 min 任务记录，只刺激两层都有反应的触点；每次放置 2 min，第一片麻醉期放好", ha="center", fontsize=9.5, color="#555")
fig.tight_layout(); fig.savefig(O + f"{CASE}_对比_放置次数与用时.png", dpi=170, bbox_inches="tight"); print("saved chart")
