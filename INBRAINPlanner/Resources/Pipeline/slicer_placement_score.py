# 3D Slicer 电极片放置规划：开颅窗口 + 刺激/记录双色目标 + 打分 + 集合覆盖 + 排序
# 用法：Slicer 里载入 brain_segmentation、tumor_segmentation（LabelMap），
#      纤维束模型（名字带 tract_CST / tract_AF，已在 T1c 空间），
#      （可选）点列表 Entry（手动指定入路点，只取第一个点），
#      然后 Python 控制台：exec(open("这个文件的路径", encoding="utf-8").read())
import numpy as np, vtk, slicer, csv, os
import vtk.util.numpy_support as nps
from scipy import ndimage
from scipy.spatial import cKDTree

# ================= 参数 =================
# 器件
NX, NY = 3, 7          # 大触点阵列（列 × 行）；商用条带改 1, 4
PITCH = 4.0            # 大触点间距 mm；商用条带 10
SMALL = True           # 大触点之间有没有只记录的小触点（INBRAIN 按官网图 True，商用条带 False）
SMALL_N = 48           # dense layout: number of small contacts
SMALL_LAYOUT = "cells" # 小触点放哪：cells = 每 4 个大触点中间（(NX-1)×(NY-1) 个）；rows = 每列相邻大触点之间（NX×(NY-1) 个）；stagger = 每列两侧错开各一排（NX×2×2NY 个，官网照片）；dense = 均匀密排 SMALL_N 个
# 刺激范围按电流算（Ranck 1975 / Tehovnik 1996：激活半径 r = √(I/k)；k = 1292 µA/mm²，Stoney 1968 皮层锥体细胞）
STIM_MODEL = True     # False = 用固定的 EDGE_TOL / ±3 mm（v0.3 旧做法）
STIM_I = 8.0          # 刺激电流 mA（Penfield 法 1 mA 起、最高 20 mA，参考资料）
K_RANCK = 1292.0      # µA/mm²
CONTACT_D = 1.0       # 阵列大触点直径 mm（参考资料：约 1 mm）
STRIP_CD = 2.3        # 条带触点暴露直径 mm（Ad-Tech 4 mm 触点暴露 2.3 mm）
BIPOLAR_SPREAD = 0.5  # 双极：电流集中在两个触点之间（Nathan 1993 定性结论），激活半径按单极的这个比例算
# 语言段（AF）用 Penfield 双极（相邻两触点组成一对，连同两触点中点都能测）；运动段（CST）用 Taniguchi 单极
REQ_HEALTHY = True    # True = 没有触点落在健康参照区（离 FLAIR > 30 mm）时，加一片只记录的参照片（Díaz-Fernández 2025）
GRAD_BINS = (0.5, 3.0, 7.0, 12.0, 18.0)   # 记录梯度：按到边界的距离 DD 分 5 档（病灶内 / 边界 / +5 / +10 / +15 mm）
GRAD_MIN = 4           # 一段至少有这么多档有记录触点，才能沿梯度区分肿瘤浸润和正常皮层
W_GRAD = 0.5           # 选片时“补全记录梯度”的权重（相对完整判定 1、只确认边界 0.5）
PRUNE = True          # drop placements whose segments are all covered by the other placements
NTMS_PATH = ""        # preoperative nTMS positive points (.fcsv / .mrk.json / CSV x,y,z,label; labels with 'lang' count as language); empty = not used
NTMS_R = 10.0         # segments within this distance of a positive point (mm)
NTMS_W_MOTOR = 1.0    # motor points: segment risk × (1 + w)
NTMS_W_LANG = 0.5     # language points: weaker evidence, lower weight
FMRI_PATH = ""        # 术前 fMRI 激活图（z 值，和 T1c 同一空间）；空 = 不用
FMRI_Z = 3.1          # z 阈值：低于它不算激活；到 2 倍阈值算满分
FMRI_W = 1.0          # 段风险 × (1 + FMRI_W × 激活)；激活满分但附近没有纤维束的段也要定位，风险 = FMRI_W × 激活
STIM_REACH = 5.0       # 大触点刺激能查到的半径 mm
REC_REACH_L = 5.0      # 大触点记录半径 mm
REC_REACH_S = 3.0      # 小触点记录半径 mm
ANGLES = range(0, 180, 30)
ANGLE_MODE = "grid"     # grid = 按 ANGLES 均匀试方向；tangent = 只试沿边界切线、垂直切线及 ±TANGENT_JITTER 的方向
TANGENT_JITTER = 15.0   # tangent 模式下切线方向两侧再试的偏角（°）；0 = 只试切线和法线两个方向
MAX_FIT = 3.0          # 贴合误差硬约束 mm
# 开颅位置
ENTRY_MODE = "auto"    # auto：可开颅区域里综合评分最高；nearest：离核心最近（旧做法）；手动：放 Entry 点列表
MIDLINE_EX = 12.0      # 离中线多近不开（上矢状窦、大脑镰）mm
MIDLINE_CAUTION = 20.0 # 离中线多近扣分 mm
BASE_NZ = -0.35        # 皮层法向 z 分量低于这个 = 颅底面（额底、颞底、小脑下面），不开
LOW_Z = 0.35           # 高度在全脑最低 35% 的外侧皮层扣分（颞部低位，靠近颧弓/耳）
ENTRY_GRID = 4.0       # 入口候选间隔 mm
VEIN_SAFE = 3.0        # surface veins (SWI): corridor closer than this to a large vein is penalised (mm)
W_VEIN = 0.4           # entry penalty weight for veins (0 = ignore SWI)
VEIN_PCT = 0.5         # SWI low-signal threshold: percentile of healthy brain intensity
VEIN_DEPTH = 3.0       # only low signal within this depth below the cortical envelope counts as a surface vein (mm)
VEIN_MIN_VOX = 300     # smallest connected low-signal blob kept as a vein (voxels, about mm³)
W_VEIN_ARR = 0.2       # array-level vein hinge penalty: contacts closer than VEIN_SAFE to a surface vein cost sum(VEIN_SAFE - d)/VEIN_SAFE per contact (Pogoncheff 2026); 0 = off
VEIN_HARD = False      # True: placements with any contact inside VEIN_SAFE are rejected
MAX_STRAIN = 0.20      # contact spacing across the array may stretch/compress at most this fraction when it follows the cortex (spring-like fit, Blenkmann 2017)
BND_SRC = "core"       # resection boundary to verify: "core" = enhancing core + necrosis (default), "flair" = FLAIR outer edge (supramaximal)
NCE_THR = 5.0          # residual non-enhancing tumour threshold (mL) for the better survival group
SEG_LEN = 10.0         # boundary is split into segments about this long (mm); each needs a yes/no from mapping (1 cm = clinical negative-mapping spacing)
SUPRA = 8.0            # extended resection to verify beyond the boundary (mm): a contact on the edge + one this far outside decides a segment
BND_DEPTH = 40.0       # how deep below the cortex a tumour still projects onto it (mm)
EDGE_TOL = 3.0         # a contact this close to the boundary counts as "on the edge" (mm)
ZONE_CLOSE = 15.0      # contact zones from MRI (Díaz-Fernández 2025, Neuro-Oncology): over lesion / close peritumoral < 15 mm /
ZONE_FAR = 30.0        #   far peritumoral 15–30 mm / healthy > 30 mm from the FLAIR border; healthy contacts are the within-patient reference
ZONE_DEPTH = 10.0      # depth below a contact that still counts as "over the lesion" for zoning (mm)
STRIP_N = 4            # conventional subdural strip: number of contacts (1×N)
STRIP_PITCH = 10.0     # conventional strip/grid contact spacing (mm), e.g. DIXI 6×1 / 4×2 with 10 mm spacing
RISK_D = 15.0          # a segment needs mapping when a tract entry lies within this distance (mm); farther segments follow imaging alone
MAX_ARRAYS = 0         # 0 = place until the coverage goals are met; N > 0 = use exactly N placements and maximise coverage
W_E = dict(cov=1.0, path=0.7, cross=1.0, eloq=0.5, low=0.3, mid=0.2)   # 入口评分权重
# 开颅窗口
WINDOW_R = 35.0        # 窗口半径 mm（约 7 cm 骨瓣）
WIN_SHAPE = "ellipse"  # bone window shape: circle (WINDOW_R) / ellipse / rect (rounded rectangle)
WIN_LEN, WIN_WID = 80.0, 60.0   # ellipse / rect: full length along the long axis and full width (mm)
WIN_ANGLE = 0.0        # long-axis direction in the window plane: 0 = anterior-posterior, 90 = superior-inferior (deg)
WIN_CORNER = 10.0      # rect: corner radius (mm)
SLIDE = 15.0           # 允许伸到骨窗边缘下面多远 mm
EXPOSE_MIN = 10.0      # 骨窗至少露出肿瘤皮层投影外多宽 mm（小骨窗定义 ≤ 1 cm，Carrabba 2022）
EXPOSE_MAX = 30.0      # 定制骨窗一般只露肿瘤外 2–3 cm（Sanai 2008/2009，Southwell 2016）
# 目标区
TRACT_NEAR = 10.0      # 皮层点离纤维束多近算“纤维束入口”
STIM_EDGE = 15.0       # 纤维束入口离病灶（切除边缘）多近才需要刺激 mm
RING = 8.0             # 刺激点周围多宽一圈算记录目标（监测后放电）mm
TRACT_W = {"CST": 1.0, "AF": 0.5}   # 0007 在右侧，AF 不一定是语言优势侧，先给一半权重
# 打分和计划
W_STIM, W_REC, W_FIT = 2.0, 1.0, 0.2
GOAL_STIM, GOAL_REC = 0.9, 0.8
# 时间模型（都是假设值，问老师）
T_PLACE = 2.0          # 放/挪一次电极片（含确认位置、拍照）min
T_LANG = 1.0           # 一个语言位点：至少 3 次不连续刺激 + 命名任务 min
T_MOTOR = 0.5          # 一个运动位点 min
OV_PROBE = 0.3         # 手持探针每个位点额外开销（挪探针、贴编号标签）min
T_WAKE = 15.0         # wake-up until cooperative min
T_BASE = 5.0          # baseline language test min
T_MON = 2.5           # awake monitoring per eloquent boundary segment during resection min
OV_ARRAY = 0.05        # 阵列触点之间电子切换的额外开销 min
MOTOR_AWAKE = False    # 运动定位放不放在清醒期（False = 麻醉下 MEP）
AWAKE_WINDOW = 120.0   # 清醒期可用时长 min：文献清醒期平均约 98 min、测试 73±26 min，建议不超过约 120 min（疲劳）
# 情景：先记录后刺激（阵列全部触点在语言任务下同时记录高 gamma，只刺激有反应的触点）
T_PASSIVE = 3.0        # 每次清醒期放置做一轮任务记录 min
P_TRUE = 0.3           # 候选语言位点里真正有语言功能的比例（假设）
SENS, SPEC = 0.95, 0.59  # 被动高 gamma 定位对比电刺激的敏感度/特异度（Swift 2018，感受性语言，15 例对照）
PASSIVE_ASLEEP = True  # 被动任务记录放到麻醉期（全麻下听觉任务高 γ），醒来只刺激 CCEP 和被动记录都阳性的触点
# 情景：麻醉下 CCEP 筛（单脉冲刺激前部触点，后部触点记录，查弓状束连接）
F_CCEP = 0.4           # 语言候选触点里 CCEP 阳性、醒来还要刺激确认的比例（假设）
STRIP_CCEP_EXTRA = 1  # conventional: extra placements per asleep CCEP site (stimulating and recording strips are separate)
PASSIVE_N = 1         # asleep passive recording only on the first N placements
T_CCEP = 2.0           # 每次麻醉期放置做 CCEP 的时间 min
CCEP_SENS = 0.85       # CCEP 对真语言位点的敏感度（假设）
ASLEEP_FIRST = True    # 阵列在麻醉期就放好第一片，醒来不用再放这一片
# 标准流程
PROBE_GRID = 10.0      # 手持探针逐点刺激的网格间距 mm（临床约 1 cm）
STRIP_PLACE_STD = 2    # 标准流程里条带（只记录后放电）放几次，麻醉期完成
ENVELOPE_MM = 6.0
CAND_GRID = 6.0        # 候选中心间隔 mm
BRAIN, TUMOR = "brain_segmentation", "tumor_segmentation"
OUT = None             # CSV 路径，None 则存到 tumor 文件旁边
SHOW = True            # 场景里画目标点云和计划
REC_FLAIR = 5.0        # 记录目标：离 FLAIR 浸润带多近的皮层 mm
CORE_MARGIN = 3.0      # cortex closer than this to the tumour core (enhancing + necrosis) is resected anyway: not a stimulation/recording target (mm)
REC_LESION = 30.0      # 记录目标：离病灶多远以内 mm
DEVICE = None          # 自定义器件：dict(large=[[u,v],...], small=[[u,v],...])，单位 mm，相对片子中心；None 用 NX×NY 网格
# 插件或其他脚本可以在 exec 前放一个 OVERRIDES 字典覆盖上面任何参数
globals().update(globals().get("OVERRIDES") or {})
R_MONO = float(np.sqrt(STIM_I*1000.0/K_RANCK) + CONTACT_D/2) if STIM_MODEL else None    # 单极激活半径 mm
R_BI = BIPOLAR_SPREAD*R_MONO if STIM_MODEL else None
R_STRIP = float(np.sqrt(STIM_I*1000.0/K_RANCK) + STRIP_CD/2) if STIM_MODEL else None  # 条带同流程：手持探针在条带触点处刺激
if STIM_MODEL: STIM_REACH = R_MONO
ANGLES = list(ANGLES)
_P = globals().get("PROGRESS") or (lambda *a: None)   # 进度回调 _P(0–1, 说明)

def node_like(s, cls="vtkMRMLLabelMapVolumeNode"):
    for n in slicer.util.getNodesByClass(cls):
        if s in n.GetName(): return n
    raise RuntimeError(f"找不到节点 {s}")
brain, tumor = node_like(BRAIN), node_like(TUMOR)
sp_mm = np.array(tumor.GetSpacing())[::-1]

_P(0.02, "皮层包络面|Cortical envelope")
# ================= 1 皮层包络面 =================
bm = slicer.util.arrayFromVolume(brain) > 0
r = int(round(ENVELOPE_MM / min(brain.GetSpacing())))
zz, yy, xx = np.ogrid[-r:r+1, -r:r+1, -r:r+1]
env = ndimage.binary_fill_holes(ndimage.binary_closing(np.pad(bm, r), xx*xx + yy*yy + zz*zz <= r*r))[r:-r, r:-r, r:-r]
envNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "brain_envelope_tmp")
envNode.CopyOrientation(brain); slicer.util.updateVolumeFromArray(envNode, env.astype(np.uint8))
seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "brain_surface_tmp")
slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(envNode, seg)
seg.CreateClosedSurfaceRepresentation()
surf0 = vtk.vtkPolyData(); seg.GetClosedSurfaceRepresentation(seg.GetSegmentation().GetNthSegmentID(0), surf0)
slicer.mrmlScene.RemoveNode(seg); slicer.mrmlScene.RemoveNode(envNode)
nm = vtk.vtkPolyDataNormals(); nm.SetInputData(surf0); nm.ComputePointNormalsOn(); nm.SplittingOff(); nm.AutoOrientNormalsOn(); nm.Update()
SP = nps.vtk_to_numpy(nm.GetOutput().GetPoints().GetData()).copy()
SN = nps.vtk_to_numpy(nm.GetOutput().GetPointData().GetNormals()).copy()
stree = cKDTree(SP)
bm_center = SP.mean(0)

_P(0.10, "肿瘤距离场|Tumour distance maps")
# ================= 2 肿瘤距离场 =================
lab = slicer.util.arrayFromVolume(tumor)
m = vtk.vtkMatrix4x4(); tumor.GetRASToIJKMatrix(m); RAS2IJK = slicer.util.arrayFromVTKMatrix(m)
m2 = vtk.vtkMatrix4x4(); tumor.GetIJKToRASMatrix(m2); IJK2RAS = slicer.util.arrayFromVTKMatrix(m2)
def sample(vol, pts):
    ijk = (RAS2IJK @ np.c_[pts, np.ones(len(pts))].T)[:3].T.round().astype(int)
    ijk = np.clip(ijk, 0, np.array(vol.shape[::-1]) - 1)
    return vol[ijk[:, 2], ijk[:, 1], ijk[:, 0]]
d_flair = sample(ndimage.distance_transform_edt(lab != 2, sampling=sp_mm), SP)
d_lesion = sample(ndimage.distance_transform_edt(lab == 0, sampling=sp_mm), SP)
core_mask = (lab == 1) | (lab == 3) | (lab == 4)     # BraTS 标签：1 坏死、2 水肿、强化 = 4（2021 及以前）或 3（2023 起）
d_core_vol = ndimage.distance_transform_edt(~core_mask, sampling=sp_mm)
d_core = sample(d_core_vol, SP)

_P(0.15, "刺激/记录目标|Stimulation/recording targets")
# ================= 3 双色目标（先算，开颅位置评分要用） =================
tracts = {}
for nd in slicer.util.getNodesByClass("vtkMRMLModelNode") + slicer.util.getNodesByClass("vtkMRMLFiberBundleNode"):
    nmn = nd.GetName()
    if "tract" not in nmn.lower() and not nd.IsA("vtkMRMLFiberBundleNode"): continue
    pd = nd.GetPolyData()
    if pd is None or pd.GetNumberOfPoints() == 0: continue
    pd2 = vtk.vtkPolyData(); pd2.DeepCopy(pd)
    if nd.GetParentTransformNode():
        t = vtk.vtkGeneralTransform(); nd.GetParentTransformNode().GetTransformToWorld(t)
        f = vtk.vtkTransformPolyDataFilter(); f.SetInputData(pd2); f.SetTransform(t); f.Update(); pd2 = f.GetOutput()
    key = "CST" if "CST" in nmn.upper() else ("AF" if "AF" in nmn.upper() else nmn)
    tracts.setdefault(key, []).append(nps.vtk_to_numpy(pd2.GetPoints().GetData()))
stim_w = np.zeros(len(SP)); stim_src = np.full(len(SP), "", dtype=object); TRACT_MASK = {}
for key, arrs in tracts.items():
    near = cKDTree(np.vstack(arrs)).query(SP)[0] <= TRACT_NEAR
    TRACT_MASK[key] = near
    hit = near & (d_lesion <= STIM_EDGE)
    w = TRACT_W.get(key, 1.0)
    upd = hit & (w > stim_w); stim_w[upd] = w; stim_src[upd] = key
# optional site prior: weight of each stimulation target by the positive probability of its brain region (atlas)
_PRI = globals().get("SITE_PRIOR")
SITE_W = np.ones(len(SP))
if _PRI is not None:
    try: SITE_W = np.asarray(_PRI(SP), float).reshape(-1); assert len(SITE_W) == len(SP)
    except Exception as _e: print("SITE_PRIOR failed:", _e); SITE_W = np.ones(len(SP))
stim_w = stim_w * np.where(stim_w > 0, SITE_W, 1.0)
on_core = d_core < CORE_MARGIN
stim_w[on_core] = 0
is_stim = stim_w > 0
ring = np.zeros(len(SP), bool)
if is_stim.any():
    ring = cKDTree(SP[is_stim]).query(SP)[0] <= RING
is_rec = ((d_flair <= REC_FLAIR) | ring) & ~is_stim & (d_lesion <= REC_LESION) & ~on_core
TP_all = np.vstack([np.vstack(v) for v in tracts.values()]) if tracts else None

_P(0.20, "可开颅区域和入口评分|Feasible craniotomy and entry scoring")
# ================= 4 哪里能开颅：可开颅区域 + 入口评分 =================
# 硬排除：对侧半球；中线旁（上矢状窦、大脑镰）；颅底面（额底、颞底、小脑下面，法向朝下）；
#         后下部（小脑、横窦一带）。软扣分：低位外侧（颞部低位，靠近颧弓/耳）、入口压在功能区上、
#         通道穿过纤维束、通道长。加分：窗口能露出多少刺激/记录目标。
cx_mid = (SP[:, 0].min() + SP[:, 0].max()) / 2
zmin, zmax = SP[:, 2].min(), SP[:, 2].max(); ymin, ymax = SP[:, 1].min(), SP[:, 1].max()
cv = np.argwhere(core_mask)[:, ::-1]; core_ras = (IJK2RAS @ np.c_[cv, np.ones(len(cv))].T)[:3].T
core_c = core_ras.mean(0); side = np.sign(core_c[0] - cx_mid) or 1.0
zr = (SP[:, 2] - zmin) / (zmax - zmin); yr = (SP[:, 1] - ymin) / (ymax - ymin)
ex_contra = side*(SP[:, 0] - cx_mid) < 0
ex_mid = np.abs(SP[:, 0] - cx_mid) < MIDLINE_EX
ex_base = SN[:, 2] < BASE_NZ
ex_post = (zr < 0.30) & (yr < 0.35)
excluded = ex_contra | ex_mid | ex_base | ex_post
low_lat = (zr < LOW_Z) & ~excluded
caution_mid = (np.abs(SP[:, 0] - cx_mid) < MIDLINE_CAUTION) & ~excluded

def region(p, n):
    y = (p[1] - ymin) / (ymax - ymin); z = (p[2] - zmin) / (zmax - zmin)
    lobe = "额" if y > 0.62 else ("颞" if (z < 0.45 and y > 0.3) else ("枕" if y < 0.25 else "顶"))
    face = "顶部凸面" if n[2] > 0.5 else "外侧凸面"
    hgt = "高位" if z > 0.65 else ("中位" if z > 0.4 else "低位")
    return f"{lobe}·{face}·{hgt}"

feas = np.where(~excluded)[0]
keysE = {}
for i in feas: keysE.setdefault(tuple((SP[i] // ENTRY_GRID).astype(int)), i)
E = np.array(list(keysE.values()))
stree_stim = cKDTree(SP[is_stim]) if is_stim.any() else None
reach_tree = stree
tp_tree = cKDTree(TP_all[::3]) if TP_all is not None else None
# 入口评分时方向还没定，用等面积圆的半径近似
R_EQ = WINDOW_R if WIN_SHAPE == "circle" else (np.sqrt(WIN_LEN*WIN_WID/4) if WIN_SHAPE == "ellipse" else np.sqrt(WIN_LEN*WIN_WID/np.pi))
covE = np.zeros(len(E)); pathE = np.zeros(len(E)); crossE = np.zeros(len(E)); eloqE = np.zeros(len(E)); veinE = np.zeros(len(E))
# 表面大静脉（SWI 低信号）：只取皮层包络面下 VEIN_DEPTH 内、病灶外、连通块够大的；静脉窦在去颅骨数据里看不到，仍靠中线规则
VEIN_PTS = np.zeros((0, 3)); vein_tree = None
_swi = next((n for n in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode") if "SWI" in n.GetName()), None)
if _swi is not None and W_VEIN > 0:
    try:
        _a = slicer.util.arrayFromVolume(_swi).astype(float)
        if _a.shape == bm.shape:
            _depth = ndimage.distance_transform_edt(env, sampling=sp_mm)
            _les = ndimage.binary_dilation(lab > 0, iterations=5)
            _zone = bm & (_depth <= VEIN_DEPTH) & ~_les
            _m = _zone & (_a < np.percentile(_a[bm & ~_les], VEIN_PCT))
            _cc, _n = ndimage.label(_m)
            _sz = ndimage.sum(_m, _cc, range(1, _n + 1)) if _n else np.zeros(0)
            _kji = np.argwhere(np.isin(_cc, np.where(_sz >= VEIN_MIN_VOX)[0] + 1))
            VEIN_PTS = (IJK2RAS @ np.c_[_kji[:, ::-1], np.ones(len(_kji))].T)[:3].T
            if len(VEIN_PTS): vein_tree = cKDTree(VEIN_PTS)
            print(f"SWI 表面大静脉：{len(VEIN_PTS)} 个体素，{int((_sz >= VEIN_MIN_VOX).sum())} 段")
        else: print("SWI 和分割网格不一致，不做静脉避让")
    except Exception as _e: print("SWI 静脉提取失败：", _e)
ctree = cKDTree(core_ras[::5])
for k, i in enumerate(E):
    if k % 200 == 0: _P(0.20 + 0.15*k/max(len(E), 1), "可开颅区域和入口评分|Feasible craniotomy and entry scoring")
    p = SP[i]; nb = reach_tree.query_ball_point(p, R_EQ + SLIDE)
    covE[k] = stim_w[nb].sum() + 0.3*is_rec[nb].sum()
    dcore, j = ctree.query(p); tgt = core_ras[::5][j]; pathE[k] = dcore
    seg_pts = p + np.linspace(0, 1, max(int(dcore // 2), 2))[:, None]*(tgt - p)
    crossE[k] = float(np.mean(tp_tree.query(seg_pts)[0] < 5.0)) if tp_tree is not None else 0.0
    eloqE[k] = float(stree_stim.query(p)[0] < 10.0) if stree_stim is not None else 0.0
    if vein_tree is not None:
        veinE[k] = float(vein_tree.query(p)[0] < 10.0 or (vein_tree.query(seg_pts)[0] < VEIN_SAFE).any())
nz = lambda v: (v - v.min()) / (v.max() - v.min() + 1e-9)
scoreE = W_E["cov"]*nz(covE) - W_E["path"]*nz(pathE) - W_E["cross"]*crossE - W_E["eloq"]*eloqE \
         - W_E["low"]*low_lat[E] - W_E["mid"]*caution_mid[E] - W_VEIN*veinE
orderE = np.argsort(-scoreE)
print(f"可开颅区域：皮层点 {int((~excluded).sum())}/{len(SP)}（排除：对侧 {int(ex_contra.sum())}，中线旁 {int(ex_mid.sum())}，颅底面 {int(ex_base.sum())}，后下部 {int(ex_post.sum())}）")
print(f"核心表面 {CORE_MARGIN:g} mm 内的皮层点不当目标：{int(on_core.sum())} 个")
print("入口候选前 5（分数 | 大致位置 | 窗口内目标 | 到核心 mm | 通道穿纤维束比例 | 压功能区 | 压在核心上 | 近大静脉）：")
for k in orderE[:5]:
    i = E[k]; print(f"  {scoreE[k]:.2f} | {region(SP[i], SN[i])} | {covE[k]:.0f} | {pathE[k]:.0f} | {crossE[k]:.0%} | {'是' if eloqE[k] else '否'} | {'是' if on_core[i] else '否'} | {'是' if veinE[k] else '否'}")
ENTRY_MAP = dict(points=SP[E], score=scoreE, excluded=SP[excluded])

ent = next((n for n in slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode") if n.GetName() == globals().get("ENTRY_NAME", "Entry")), None)
if ent is not None and ent.GetNumberOfControlPoints():
    ei = stree.query(np.array(ent.GetNthControlPointPositionWorld(0)))[1]; how = "手动"
elif ENTRY_MODE == "centre":
    fe = np.where(~excluded)[0]; ei = int(fe[np.argmin(np.linalg.norm(SP[fe] - core_c, axis=1))]) if len(fe) else int(np.argmin(d_core))
    how = "以肿瘤投影为中心（离核心中心最近的可开颅皮层点）"
elif ENTRY_MODE == "nearest":
    ei = int(np.argmin(d_core)); how = "离核心最近的皮层点（不看能不能开）"
else:
    ei = int(E[orderE[0]]); how = "可开颅区域里综合评分最高"
entry = SP[ei]
print(f"入口点：{how}，{region(entry, SN[ei])}，{'被排除区域！' if excluded[ei] else '可开颅'}；到核心 {d_core[ei]:.0f} mm")
d_entry = np.linalg.norm(SP - entry, axis=1)
# 骨窗形状：在垂直于“脑中心 → 入口”的平面里定义；win_sdf = 到骨窗边缘的有符号距离（mm，里面为负）
WIN_N = entry - bm_center; WIN_N = WIN_N / np.linalg.norm(WIN_N)
_ap = np.array([0, 1.0, 0]) - WIN_N[1]*WIN_N
if np.linalg.norm(_ap) < 1e-3: _ap = np.array([1.0, 0, 0]) - WIN_N[0]*WIN_N
_ap /= np.linalg.norm(_ap); _si = np.cross(WIN_N, _ap)
if _si[2] < 0: _si = -_si
_t = np.radians(WIN_ANGLE); WIN_U = np.cos(_t)*_ap + np.sin(_t)*_si; WIN_V = np.cross(WIN_N, WIN_U)
WIN_RMAX = WINDOW_R if WIN_SHAPE == "circle" else max(WIN_LEN, WIN_WID)/2
def win_sdf(P):
    d = np.asarray(P, float).reshape(-1, 3) - entry; u, v = d @ WIN_U, d @ WIN_V
    far = (d @ WIN_N) < -(WIN_RMAX + SLIDE)          # 比骨窗尺寸还深的点（对侧、远侧皮层）不算在骨窗里
    return np.where(far, 999.0, _win_sdf2d(u, v))
def _win_sdf2d(u, v):
    if WIN_SHAPE == "ellipse":
        a, b = WIN_LEN/2, WIN_WID/2; return (np.sqrt((u/a)**2 + (v/b)**2) - 1)*min(a, b)
    if WIN_SHAPE == "rect":
        a, b, c = WIN_LEN/2, WIN_WID/2, min(WIN_CORNER, WIN_LEN/2, WIN_WID/2)
        qx, qy = np.abs(u) - (a - c), np.abs(v) - (b - c)
        return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - c
    return np.hypot(u, v) - WINDOW_R
# 只算从骨窗往里看最外面那层皮层：按骨窗平面 3 mm 一格，每格只留离骨窗最近的 10 mm 以内
_d = SP - entry; _al = _d @ WIN_N; _g = np.floor(np.c_[_d @ WIN_U, _d @ WIN_V]/3.0).astype(int)
_key = (_g[:, 0] - _g[:, 0].min())*100000 + (_g[:, 1] - _g[:, 1].min())
_uk, _inv = np.unique(_key, return_inverse=True); _top = np.full(len(_uk), -1e9); np.maximum.at(_top, _inv, _al)
VISIBLE = _al >= _top[_inv] - 10.0
SDF = np.where(VISIBLE, win_sdf(SP), 999.0)
in_win, in_reach = SDF <= 0, SDF <= SLIDE
WIN_AREA = {"ellipse": np.pi*WIN_LEN*WIN_WID/4, "rect": WIN_LEN*WIN_WID - (4 - np.pi)*min(WIN_CORNER, WIN_LEN/2, WIN_WID/2)**2}.get(WIN_SHAPE, np.pi*WINDOW_R**2)/100.0
# 边界检查：骨窗边缘到中线的距离，边缘是否进了颅底面、后下部、低位外侧
_edge = np.where(np.abs(SDF) < 1.0)[0]
WIN_CHECK = dict(area_cm2=float(WIN_AREA), mid_mm=float(np.abs(SP[_edge, 0] - cx_mid).min()) if len(_edge) else float("nan"),
                 base=bool(ex_base[_edge].any()) if len(_edge) else False, post=bool(ex_post[_edge].any()) if len(_edge) else False,
                 low=bool(low_lat[_edge].any()) if len(_edge) else False, contra=bool(ex_contra[_edge].any()) if len(_edge) else False)
_shape = {"ellipse": f"椭圆 {WIN_LEN:g} × {WIN_WID:g} mm，长轴 {WIN_ANGLE:g}°", "rect": f"圆角矩形 {WIN_LEN:g} × {WIN_WID:g} mm，长轴 {WIN_ANGLE:g}°"}.get(WIN_SHAPE, f"圆形，半径 {WINDOW_R:g} mm")
print(f"骨窗：{_shape}，面积 {WIN_AREA:.0f} cm²，边缘离中线最近 {WIN_CHECK['mid_mm']:.0f} mm；可伸出 {SLIDE} mm")

S_idx, R_idx = np.where(is_stim & in_reach)[0], np.where(is_rec & in_reach)[0]
S_out, R_out = int((is_stim & ~in_reach).sum()), int((is_rec & ~in_reach).sum())
print(f"参考刺激区：骨窗可达 {len(S_idx)} 点，超出可达范围 {S_out} 点  {dict(zip(*np.unique(stim_src[S_idx], return_counts=True))) if len(S_idx) else {}}")
print(f"参考记录区：骨窗可达 {len(R_idx)} 点，超出可达范围 {R_out} 点")
Ts = cKDTree(SP[S_idx]) if len(S_idx) else None
Tr = cKDTree(SP[R_idx]) if len(R_idx) else None
wS = stim_w[S_idx]; totS, totR = max(wS.sum(), 1e-9), max(len(R_idx), 1)

_P(0.38, "放置候选|Placement candidates")
# ================= 5 放一片 =================
def place(center, angle):
    _, ci = stree.query(center); c, n = SP[ci], SN[ci]
    ref = np.array([0, 0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0, 0])
    e1 = np.cross(n, ref); e1 /= np.linalg.norm(e1); e2 = np.cross(n, e1)
    a = np.radians(angle); u = np.cos(a)*e1 + np.sin(a)*e2; v = np.cross(n, u)
    if DEVICE:
        Lo = np.asarray(DEVICE.get("large", []), float).reshape(-1, 2); So = np.asarray(DEVICE.get("small", []), float).reshape(-1, 2)
        big = c + Lo[:, :1]*u + Lo[:, 1:]*v
        small = c + So[:, :1]*u + So[:, 1:]*v if len(So) else np.zeros((0, 3))
        flat = np.vstack([big, small]); _, idx = stree.query(flat); q = SP[idx]
        return q[:len(big)], q[len(big):], np.linalg.norm(q - flat, axis=1).max()
    gi, gj = np.meshgrid(np.arange(NX) - (NX-1)/2, np.arange(NY) - (NY-1)/2, indexing="ij")
    big = c + (gi.ravel()[:, None]*u + gj.ravel()[:, None]*v) * PITCH
    if SMALL and SMALL_LAYOUT == "rows" and NY > 1:
        si, sj = np.meshgrid(np.arange(NX) - (NX-1)/2, np.arange(NY-1) - (NY-2)/2, indexing="ij")
        small = c + (si.ravel()[:, None]*u + sj.ravel()[:, None]*v) * PITCH
    elif SMALL and SMALL_LAYOUT == "stagger" and NY > 1:
        # staggered (as in the website photo and line drawing): a row of small contacts on each side of every column of large ones,
        # PITCH/3 away; one every half pitch along the column, offset a quarter pitch from the large ones. 3 x 4 gives 3 x 2 x 8 = 48
        jj = (np.arange(2*NY) - (2*NY - 1)/2)*PITCH/2
        rows_ = [(i_ - (NX-1)/2)*PITCH + sgn*PITCH/3 for i_ in range(NX) for sgn in (-1, 1)]
        S2 = np.array([(r_, j_) for r_ in rows_ for j_ in jj])
        small = c + S2[:, :1]*u + S2[:, 1:]*v
    elif SMALL and SMALL_LAYOUT == "dense" and NX*NY > 1:
        # dense: small contacts spread evenly between the large ones (not within 0.6 mm of a large one), count close to SMALL_N (first-in-human device: 12 large + 48 small)
        best_ = None
        for m in range(2, 9):
            gu, gv = np.meshgrid(np.arange(-(NX-1)/2*m, (NX-1)/2*m + 1e-9), np.arange(-(NY-1)/2*m, (NY-1)/2*m + 1e-9), indexing="ij")
            P2 = np.c_[gu.ravel(), gv.ravel()]*PITCH/m
            B2 = np.c_[gi.ravel(), gj.ravel()]*PITCH
            keep = np.min(np.linalg.norm(P2[:, None, :] - B2[None, :, :], axis=2), axis=1) > 0.6
            P2 = P2[keep]
            if best_ is None or abs(len(P2) - SMALL_N) < abs(len(best_) - SMALL_N): best_ = P2
        if len(best_) > SMALL_N: best_ = best_[np.round(np.linspace(0, len(best_) - 1, SMALL_N)).astype(int)]
        small = c + best_[:, :1]*u + best_[:, 1:]*v
    elif SMALL and NX > 1 and NY > 1:
        si, sj = np.meshgrid(np.arange(NX-1) - (NX-2)/2, np.arange(NY-1) - (NY-2)/2, indexing="ij")
        small = c + (si.ravel()[:, None]*u + sj.ravel()[:, None]*v) * PITCH
    else:
        small = np.zeros((0, 3))
    flat = np.vstack([big, small]); _, idx = stree.query(flat); q = SP[idx]
    return q[:len(big)], q[len(big):], np.linalg.norm(q - flat, axis=1).max()

# long contact pairs in the flat layout; strain = how much each pair is stretched/compressed on the cortex
if DEVICE and len(DEVICE.get("large", [])) > 1:
    _LO = np.asarray(DEVICE["large"], float).reshape(-1, 2)
else:
    _gi, _gj = np.meshgrid(np.arange(NX) - (NX-1)/2, np.arange(NY) - (NY-1)/2, indexing="ij")
    _LO = np.c_[_gi.ravel(), _gj.ravel()] * PITCH
_ADJ = np.zeros((0, 2), int)
if len(_LO) > 1:
    _D2 = np.linalg.norm(_LO[:, None] - _LO[None], axis=2); _dmin = _D2[_D2 > 0].min()
    _ADJ = np.argwhere(np.triu((_D2 > 0) & (_D2 <= 1.05*_dmin)))         # 相邻大触点对：双极刺激用
    # pairs at least half the array span apart: one-vertex snapping error (~1 mm) would dominate 4 mm neighbour pairs
    _PAIRS = np.argwhere(np.triu(_D2 >= 0.5*_D2.max()))
    _PD = _D2[_PAIRS[:, 0], _PAIRS[:, 1]]
else:
    _PAIRS = np.zeros((0, 2), int); _PD = np.zeros(0)
def strain(L):
    """largest relative change of long contact-to-contact distances after projection (0.1 = 10 % stretch or squeeze)"""
    if not len(_PAIRS): return 0.0
    d = np.linalg.norm(L[_PAIRS[:, 0]] - L[_PAIRS[:, 1]], axis=1)
    return float(np.abs(d/_PD - 1).max())
def vein_hinge(P):
    """hinge penalty: sum over contacts of max(0, VEIN_SAFE - d)/VEIN_SAFE, and number of contacts inside the margin"""
    if vein_tree is None or len(P) == 0: return 0.0, 0
    d = vein_tree.query(P)[0]; h = np.clip(VEIN_SAFE - d, 0, None)/VEIN_SAFE
    return float(h.sum()), int((h > 0).sum())

def hits(tree, base, pts, rad):
    if tree is None or len(pts) == 0: return set()
    return set(base[i] for h in tree.query_ball_point(pts, rad) for i in h)

# ================= 6 候选与打分 =================
pool = SP[in_win]; keys = {}
for q in pool: keys.setdefault(tuple((q // CAND_GRID).astype(int)), q)
centers = list(keys.values())
# 沿边界切线摆放：候选中心附近边界线的主方向（投影到该点切平面）作为长轴方向，再加垂直方向和左右偏角
_vb = d_core_vol if BND_SRC == "core" else ndimage.distance_transform_edt(lab == 0, sampling=sp_mm)
_DDe = np.full(len(SP), np.inf)
for _t in np.arange(0.0, BND_DEPTH + 0.1, 2.0): _DDe = np.minimum(_DDe, sample(_vb, SP - SN*_t))
_bnd_e = np.where((_DDe > 0) & (_DDe <= 2.0))[0]
_btree = cKDTree(SP[_bnd_e]) if len(_bnd_e) else None
def angles_for(c):
    if ANGLE_MODE not in ("tangent", "both") or _btree is None: return list(ANGLES)
    _, ci_ = stree.query(c); c0, n = SP[ci_], SN[ci_]
    ref = np.array([0, 0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0, 0])
    e1 = np.cross(n, ref); e1 /= np.linalg.norm(e1); e2 = np.cross(n, e1)
    nb = _btree.query_ball_point(c0, 12.0)
    if len(nb) < 3: return list(ANGLES)
    X = SP[_bnd_e[nb]] - SP[_bnd_e[nb]].mean(0)
    t = np.linalg.svd(X, full_matrices=False)[2][0]
    a0 = np.degrees(np.arctan2(t @ e2, t @ e1)) % 180
    js = [0.0, 90.0] + ([TANGENT_JITTER, -TANGENT_JITTER, 90 + TANGENT_JITTER, 90 - TANGENT_JITTER] if TANGENT_JITTER > 0 else [])
    tan = set(int(round((a0 + j) % 180)) for j in js)
    return sorted(tan | set(ANGLES)) if ANGLE_MODE == "both" else sorted(tan)   # both = grid angles plus the tangent/normal angles of this spot
_n_ang = [len(angles_for(c)) for c in centers]
print("候选中心数:", len(centers), " 方向数:", f"{np.mean(_n_ang):.1f}（{ANGLE_MODE}）")
widx = {g: k for k, g in enumerate(S_idx)}
rows = []
for ci, c in enumerate(centers):
    _P(0.40 + 0.42*ci/max(len(centers), 1), f"试放打分 {ci+1}/{len(centers)}|Scoring placements {ci+1}/{len(centers)}")
    for ang in angles_for(c):
        L, Sm, fit = place(c, ang)
        allc = np.vstack([L, Sm])
        inside = win_sdf(allc).max() <= SLIDE
        off_core = np.mean(d_core[stree.query(L)[1]] < CORE_MARGIN) <= 0.10   # at most 10% of large contacts over the tumour core
        cs = hits(Ts, S_idx, L, STIM_REACH)
        cr = hits(Tr, R_idx, L, REC_REACH_L) | hits(Tr, R_idx, Sm, REC_REACH_S)
        sw = sum(stim_w[i] for i in cs)
        vh, vn = vein_hinge(allc); stn = strain(L)
        vpen = 2.0*W_VEIN_ARR*vh/max(len(allc), 1)      # all contacts on a vein = 2 × weight
        score = W_STIM*sw/totS + W_REC*len(cr)/totR - W_FIT*min(fit/MAX_FIT, 1) - vpen
        srcs = set(stim_src[i] for i in cs)
        rows.append(dict(cand=ci+1, angle=ang, L=L, S=Sm, cs=cs, cr=cr, stim=sw/totS, rec=len(cr)/totR,
                         fit=fit, score=score, vein_n=vn, vpen=vpen, strain=stn,
                         ok=(fit <= MAX_FIT) and inside and off_core and stn <= MAX_STRAIN and not (VEIN_HARD and vn > 0), srcs=srcs,
                         why=[k for k, bad in (("fit", fit > MAX_FIT), ("outside", not inside), ("core", not off_core),
                                               ("strain", stn > MAX_STRAIN), ("vein", VEIN_HARD and vn > 0)) if bad]))
rows.sort(key=lambda r: (not r["ok"], -r["score"]))
print(f"\n单次放置排名（{NX}×{NY} 大触点，间距 {PITCH} mm，小触点 {'有' if SMALL else '无'}）")
print(f"{'排名':>3} {'候选':>4} {'角度':>4} {'刺激覆盖':>7} {'记录覆盖':>7} {'贴合mm':>6} {'分数':>6} 通过")
for k, r in enumerate(rows[:8], 1):
    print(f"{k:>4} {r['cand']:>5} {r['angle']:>5} {r['stim']:>9.2f} {r['rec']:>9.2f} {r['fit']:>7.2f} {r['score']:>7.2f} {'✓' if r['ok'] else '✗'}")

_P(0.83, "集合覆盖|Set cover")
# ================= 7 集合覆盖：每条束的刺激目标各 90% + 记录 80% =================
# 每条束分开算目标（语言、运动各自要达标），避免点数多的 CST 把点数少的 AF 淹掉
ok = [r for r in rows if r["ok"]]
reachS = set().union(*[r["cs"] for r in ok]) if ok else set()
reachR = set().union(*[r["cr"] for r in ok]) if ok else set()
KEYS = sorted(set(stim_src[i] for i in reachS) - {""})
cntK = {k: max(sum(1 for i in reachS if stim_src[i] == k), 1) for k in KEYS}
cntKw = {k: max(sum(stim_w[i] for i in reachS if stim_src[i] == k), 1e-9) for k in KEYS}   # weighted (equals counts × tract weight without a site prior)
def nkw(st, k): return sum(stim_w[i] for i in st if stim_src[i] == k)
totRr = max(len(reachR), 1)
def nk(st, k): return sum(1 for i in st if stim_src[i] == k)
def short(got): return [k for k in KEYS if nk(got, k) < GOAL_STIM*cntK[k] - 1e-9]
# ================= 7 边界逐段判定（替换原来的覆盖率集合覆盖） =================
# 目标：切除边界（强化核心外缘，可选 FLAIR 外缘）每 SEG_LEN 一段；靠近功能区的段要给出结论：
# 边界上一个触点 + 边界外 SUPRA mm 一个触点 → 这段能不能多切 SUPRA mm。阵列长轴贴着边界放，一片同时判定几段
# 边界画在皮层上：肿瘤在皮层上的“投影轮廓”。每个皮层点沿法向往里看 BND_DEPTH mm，离肿瘤最近的距离 = 横向距离；
# 浅表肿瘤就是它露在表面的边缘，深部肿瘤（如 0007 核心在皮层下约 12 mm）就是它正上方的那圈皮层
_vol = d_core_vol if BND_SRC == "core" else ndimage.distance_transform_edt(lab == 0, sampling=sp_mm)
DD = np.full(len(SP), np.inf)
for _t in np.arange(0.0, BND_DEPTH + 0.1, 2.0):
    DD = np.minimum(DD, sample(_vol, SP - SN*_t))
_bnd = np.where((DD > 0) & (DD <= 2.0))[0]
if globals().get("BND_RIM", True) and (DD == 0).any():
    # keep only the outer rim of the tumour's cortical projection (surface points outside it, within 2 mm)
    from scipy.spatial import cKDTree
    _dd, _ = cKDTree(SP[DD == 0]).query(SP[_bnd], distance_upper_bound=2.5)
    _bnd = _bnd[np.isfinite(_dd)]
def _fps(idx, step):
    if not len(idx): return np.zeros(0, int)
    P = SP[idx]; d = np.full(len(idx), np.inf); k = 0; out = []
    while True:
        out.append(idx[k]); d = np.minimum(d, np.linalg.norm(P - P[k], axis=1)); k = int(d.argmax())
        if d[k] < step: break
    return np.array(out)
SEG = _fps(_bnd, SEG_LEN); SEGC = SP[SEG]; NSEG = len(SEG)
seg_risk = np.zeros(NSEG); seg_src = np.full(NSEG, "", dtype=object)
for key, msk in TRACT_MASK.items():
    tp = np.where(msk)[0]
    if not len(tp): continue
    w_ = TRACT_W.get(key, 1.0) * SITE_W[tp]
    for s_, h in enumerate(cKDTree(SP[tp]).query_ball_point(SEGC, RISK_D)):
        if h and w_[h].max() > seg_risk[s_]: seg_risk[s_] = float(w_[h].max()); seg_src[s_] = key
FMRI_ACT = np.zeros(NSEG)
if FMRI_PATH and os.path.exists(FMRI_PATH) and NSEG:
    try:
        _fn = slicer.util.loadVolume(FMRI_PATH, {"show": False}); _fa = slicer.util.arrayFromVolume(_fn).astype(float)
        _m = vtk.vtkMatrix4x4(); _fn.GetRASToIJKMatrix(_m); _M = slicer.util.arrayFromVTKMatrix(_m)
        for _t in np.arange(0.0, 10.1, 2.0):                                  # 段中心往里 0–10 mm 取最大 z
            _P3 = SEGC - SN[SEG]*_t; _ijk = np.rint((_M @ np.c_[_P3, np.ones(len(_P3))].T)[:3].T).astype(int)
            _ok = np.all((_ijk >= 0) & (_ijk < np.array(_fa.shape[::-1])), axis=1)
            _z = np.zeros(NSEG); _z[_ok] = _fa[_ijk[_ok, 2], _ijk[_ok, 1], _ijk[_ok, 0]]
            FMRI_ACT = np.maximum(FMRI_ACT, np.clip((_z - FMRI_Z)/max(FMRI_Z, 1e-6), 0, 1))
        slicer.mrmlScene.RemoveNode(_fn)
        _newreq = (seg_risk == 0) & (FMRI_ACT >= 1)
        seg_risk = seg_risk*(1 + FMRI_W*FMRI_ACT); seg_risk[_newreq] = FMRI_W*FMRI_ACT[_newreq]; seg_src[_newreq] = "fMRI"
        print(f"fMRI：{int((FMRI_ACT > 0).sum())} 段有激活，其中 {int(_newreq.sum())} 段原来离纤维束远、现在也要定位")
    except Exception as _e: print("fMRI 读取失败：", _e)
# ---- optional preoperative nTMS positive points: motor points are reliable, language points weaker, separate weights ----
NTMS_N = 0
if NTMS_PATH and os.path.exists(NTMS_PATH) and NSEG:
    try:
        _pts = []
        if NTMS_PATH.lower().endswith((".fcsv", ".json")):
            _mn = slicer.util.loadMarkups(NTMS_PATH)
            for _i in range(_mn.GetNumberOfControlPoints()):
                _p = [0.0, 0.0, 0.0]; _mn.GetNthControlPointPosition(_i, _p); _pts.append((_p, _mn.GetNthControlPointLabel(_i) + " " + _mn.GetName()))
            slicer.mrmlScene.RemoveNode(_mn)
        else:   # CSV：x, y, z, 标签（RAS，与 T1c 同一空间）
            import csv as _csv
            for _row in _csv.reader(open(NTMS_PATH, encoding="utf-8")):
                try: _pts.append(([float(_row[0]), float(_row[1]), float(_row[2])], " ".join(_row[3:])))
                except (ValueError, IndexError): pass
        _isL = lambda s: any(k in s.lower() for k in ("lang", "语言", "speech", "naming"))
        for _key, _w, _sel in (("nTMS-M", NTMS_W_MOTOR, lambda s: not _isL(s)), ("nTMS-L", NTMS_W_LANG, _isL)):
            _NP = np.array([p for p, s in _pts if _sel(s)], float).reshape(-1, 3)
            if not len(_NP) or _w <= 0: continue
            _d = cKDTree(_NP).query(SEGC)[0]; _hit = _d <= NTMS_R
            _new = _hit & (seg_risk == 0)
            seg_risk[_hit & ~_new] *= (1 + _w); seg_risk[_new] = _w
            for _s in np.where(_new)[0]: seg_src[_s] = _key
            NTMS_N += len(_NP)
            print(f"nTMS {_key}：{len(_NP)} 个点，{int(_hit.sum())} 段在 {NTMS_R:g} mm 内，其中 {int(_new.sum())} 段原来不要定位、现在也要定位")
    except Exception as _e: print("nTMS 读取失败：", _e)
SEG_REQ = seg_risk > 0                                   # 靠近功能区、要定位才能决定的段
_sdf_seg = SDF[SEG] if NSEG else np.zeros(0)
SEG_ARR = SEG_REQ & (_sdf_seg <= SLIDE)                  # 阵列够得着（含滑到骨窗边缘下）
SEG_PROBE = SEG_REQ & (_sdf_seg <= 0)                    # 手持探针够得着（只限骨窗里露出的皮层）
from scipy.spatial.distance import cdist
_LANG_SEG = np.array([s_ in ("AF", "fMRI", "nTMS-L") for s_ in seg_src], bool)
def seg_grad(P):
    """一片放置能为哪些段提供完整的记录梯度：段附近（横向 ≤ 0.6 段长 + 18 mm）的记录触点覆盖 ≥ GRAD_MIN 档距离"""
    if not NSEG or P is None or len(P) == 0: return set()
    dP = DD[stree.query(P)[1]]; D = cdist(SEGC, P)
    b = np.digitize(dP, GRAD_BINS); near = D <= 0.6*SEG_LEN + GRAD_BINS[-1]
    hit = np.zeros((NSEG, len(GRAD_BINS) + 1), bool)
    for k in range(len(GRAD_BINS)): hit[:, k] = (near & (b == k)[None]).any(1)
    return set(np.where((hit[:, :len(GRAD_BINS)].sum(1) >= GRAD_MIN) & SEG_REQ)[0])
def seg_decide(L, adj, r_mono, r_bi):
    """一片放置能判定哪些段。刺激能测到的点 = 触点（单极，半径 r_mono）或相邻触点对（双极，触点和中点，半径 r_bi）。
    边界上一个能测的点（DD ≤ 半径）+ 边界外 SUPRA mm 一个（|DD − SUPRA| ≤ 半径）→ 完整判定"""
    if not NSEG: return set(), set()
    full = np.zeros(NSEG, bool); edge = np.zeros(NSEG, bool)
    if r_mono is None: modes = [(L, EDGE_TOL, 3.0, np.ones(NSEG, bool))]
    else:
        Tb = np.vstack([L, (L[adj[:, 0]] + L[adj[:, 1]])/2]) if len(adj) else L
        modes = [(L, r_mono, r_mono, ~_LANG_SEG)] + ([(Tb, r_bi, r_bi, _LANG_SEG)] if r_bi is not None else [(L, r_mono, r_mono, _LANG_SEG)])
    for T_, te, to, m in modes:
        dT = DD[stree.query(T_)[1]]; D = cdist(SEGC, T_)
        e = ((D <= 0.6*SEG_LEN) & (dT <= te)[None]).any(1)
        o = ((D <= SUPRA + 0.6*SEG_LEN) & (np.abs(dT - SUPRA) <= to)[None]).any(1)
        edge |= e & m; full |= e & o & m
    return set(np.where(full & SEG_REQ)[0]), set(np.where(edge & SEG_REQ)[0])
for r in rows:
    r["seg_full"], r["seg_edge"] = seg_decide(r["L"], _ADJ, R_MONO, R_BI)
    r["seg_grad"] = seg_grad(np.vstack([r["L"], r["S"]]) if len(r["S"]) else r["L"])
ok = [r for r in rows if r["ok"]]
gotF, gotE, gotG, plan = set(), set(), set(), []
BUDGET = int(MAX_ARRAYS or 0)
def bgain(r):
    g = sum(seg_risk[s_] for s_ in r["seg_full"] - gotF) + 0.5*sum(seg_risk[s_] for s_ in r["seg_edge"] - gotE - gotF) \
        + W_GRAD*sum(seg_risk[s_] for s_ in r.get("seg_grad", set()) - gotG)
    return g - r["vpen"] if g > 0 else 0.0
while ok and (BUDGET <= 0 or len(plan) < BUDGET):
    best = max(ok, key=bgain)
    if bgain(best) <= 1e-9: break
    r = best; r["seg_new_full"] = r["seg_full"] - gotF; r["seg_new_edge"] = (r["seg_edge"] - gotE - gotF) - r["seg_new_full"]
    gotF |= r["seg_full"]; gotE |= r["seg_edge"]; gotG |= r.get("seg_grad", set()); plan.append(dict(r=dict(r)))
# Redundant-placement pruning (joint re-check after greedy selection): a placement is dropped if the others still give the same
# fully decided, edge-confirmed and gradient segments; earlier (higher-gain) placements are kept first
PRUNED = 0
if PRUNE and len(plan) > 1:
    for _k in range(len(plan) - 1, -1, -1):
        _o = [p["r"] for j, p in enumerate(plan) if j != _k]
        _F = set().union(*[x["seg_full"] for x in _o]); _E = set().union(*[x["seg_edge"] for x in _o]) | _F
        _G = set().union(*[x.get("seg_grad", set()) for x in _o])
        if gotF <= _F and gotE <= _E and (gotG & gotF) <= _G:
            plan.pop(_k); PRUNED += 1
    if PRUNED:
        _f, _e = set(), set()
        for p in plan:
            r = p["r"]; r["seg_new_full"] = r["seg_full"] - _f; r["seg_new_edge"] = (r["seg_edge"] - _e - _f) - r["seg_new_full"]
            _f |= r["seg_full"]; _e |= r["seg_edge"]
        print(f"Pruned {PRUNED} redundant placements; decisions unchanged")
# 触点分区（按 FLAIR 投影轮廓，同 Díaz-Fernández 2025 的四区）：0 病灶上 / 1 近瘤周 / 2 远瘤周 / 3 健康参照
_volF = ndimage.distance_transform_edt(lab == 0, sampling=sp_mm)
DF = np.full(len(SP), np.inf)
for _t in np.arange(0.0, ZONE_DEPTH + 0.1, 2.0):        # 只看皮层和浅层白质：触点“在病灶上”指正下方浅层就有 FLAIR 异常
    DF = np.minimum(DF, sample(_volF, SP - SN*_t))
ZONE = np.where(DF <= 0.5, 0, np.where(DF <= ZONE_CLOSE, 1, np.where(DF <= ZONE_FAR, 2, 3)))
ZONE_COUNTS = [0, 0, 0, 0]; RADIAL = []
HEALTHY_ADDED = False; HEALTHY_INFO = None
if REQ_HEALTHY and plan and not any((ZONE[stree.query(p["r"]["L"])[1]] == 3).any() for p in plan):
    # 找骨窗可达范围里离 FLAIR 边界最远的一片：优先有 ≥ 3 个大触点在健康区（> ZONE_FAR）；没有就取中位距离最大的，报告实际距离
    _cand = [(int((ZONE[stree.query(r["L"])[1]] == 3).sum()), float(np.median(DF[stree.query(r["L"])[1]])), r) for r in ok]
    if _cand:
        _n, _d, _r = max(_cand, key=lambda x: (x[0] >= 3, x[1]))
        _r = dict(_r); _r.update(seg_new_full=set(), seg_new_edge=set(), ref=True, srcs=set()); plan.append(dict(r=_r)); HEALTHY_ADDED = True
        HEALTHY_INFO = dict(n_healthy=_n, median_mm=_d)
        print(f"健康参照：加一片只记录，{_n} 个大触点离 FLAIR 边界 > {ZONE_FAR:g} mm，触点中位距离 {_d:.0f} mm")
for p in plan:
    r = p["r"]; zi = ZONE[stree.query(r["L"])[1]]
    r["zones"] = [int((zi == z).sum()) for z in range(4)]
    ZONE_COUNTS = [a_ + b_ for a_, b_ in zip(ZONE_COUNTS, r["zones"])]
    # 径向采样：判定这段的阵列在“边界 → 外 ZONE_CLOSE mm”这条线上有几个触点（瘤周浸润梯度的空间分辨率）
    # 每个触点归到最近的边界段，只数“边界上到外 ZONE_CLOSE mm”之间的触点
    if NSEG and r.get("seg_new_full"):
        dL = DD[stree.query(r["L"])[1]]; nearest = cKDTree(SEGC).query(r["L"])[1]
        for s_ in r["seg_new_full"]:
            RADIAL.append(int(((nearest == s_) & (dL >= 0) & (dL <= ZONE_CLOSE)).sum()))
RADIAL_INB = float(np.mean(RADIAL)) if RADIAL else 0.0
RADIAL_STRIP = float(np.floor(ZONE_CLOSE/STRIP_PITCH) + 1)
# ---- 传统流程，同一套边界规划：1×STRIP_N 商用条带（间距 STRIP_PITCH）代替阵列，同样可滑到骨窗边缘下、麻醉期记录 ----
_DEV0 = DEVICE
DEVICE = dict(large=[[0.0, (k - (STRIP_N - 1)/2)*STRIP_PITCH] for k in range(STRIP_N)], small=[])
srows = []
for ci, c in enumerate(centers):
    _P(0.80 + 0.03*ci/max(len(centers), 1), f"条带同流程 {ci+1}/{len(centers)}|Strip workflow {ci+1}/{len(centers)}")
    for ang in angles_for(c):
        L, Sm, fit = place(c, ang)
        if fit > MAX_FIT or win_sdf(L).max() > SLIDE or np.mean(d_core[stree.query(L)[1]] < CORE_MARGIN) > 0.10: continue
        vh, vn = vein_hinge(L); r = dict(cand=ci+1, angle=ang, L=L, S=np.zeros((0, 3)), fit=fit, vein_n=vn, vpen=2.0*W_VEIN_ARR*vh/max(len(L), 1))
        r["seg_full"], r["seg_edge"] = seg_decide(L, np.zeros((0, 2), int), R_STRIP, None); r["seg_grad"] = seg_grad(L)
        if r["seg_edge"]: srows.append(r)
DEVICE = _DEV0
_gF, _gE, _gG = gotF, gotE, gotG
gotF, gotE, gotG, SPLAN = set(), set(), set(), []
while srows and len(SPLAN) < 60:
    best = max(srows, key=bgain)
    if bgain(best) <= 1e-9: break
    r = dict(best); r["seg_new_full"] = r["seg_full"] - gotF; r["seg_new_edge"] = (r["seg_edge"] - gotE - gotF) - r["seg_new_full"]
    gotF |= r["seg_full"]; gotE |= r["seg_edge"]; gotG |= r["seg_grad"]; SPLAN.append(r)
if PRUNE and len(SPLAN) > 1:   # same pruning for the strip plan
    for _k in range(len(SPLAN) - 1, -1, -1):
        _o = [x for j, x in enumerate(SPLAN) if j != _k]
        _F = set().union(*[x["seg_full"] for x in _o]); _E = set().union(*[x["seg_edge"] for x in _o]) | _F; _G = set().union(*[x["seg_grad"] for x in _o])
        if gotF <= _F and gotE <= _E and (gotG & gotF) <= _G: SPLAN.pop(_k)
    _f, _e = set(), set()
    for r in SPLAN:
        r["seg_new_full"] = r["seg_full"] - _f; r["seg_new_edge"] = (r["seg_edge"] - _e - _f) - r["seg_new_full"]; _f |= r["seg_full"]; _e |= r["seg_edge"]
STRIP_FULL, STRIP_EDGE, STRIP_SEP = len(gotF), len(gotE | gotF), len(gotF & gotG)
STRIP_SEP_SET = gotF & gotG
gotF, gotE, gotG = _gF, _gE, _gG
strip_lang_k, strip_motor_k = [], []
for r in SPLAN:
    nl = nm_ = 0
    for s_, n_ in [(x, 2) for x in r["seg_new_full"]] + [(x, 1) for x in r["seg_new_edge"]]:
        if seg_src[s_] in ("AF", "fMRI", "nTMS-L"): nl += n_     # fMRI 激活段按语言任务算
        else: nm_ += n_
    strip_lang_k.append(nl); strip_motor_k.append(nm_)
print(f"条带同流程（1×{STRIP_N}，{STRIP_PITCH:g} mm）：放 {len(SPLAN)} 次，完整判定 {STRIP_FULL} 段")

SEG_DONE = np.zeros(NSEG, int)                           # 0 未判定，1 只有边界点（能确认核心边界），2 完整判定（能决定多切 SUPRA mm）
for s_ in gotE: SEG_DONE[s_] = 1
for s_ in gotF: SEG_DONE[s_] = 2
# 可分离 = 功能可判定（刺激两点）+ 有完整记录梯度（能区分浸润组织和正常皮层）
SEG_SEP = np.zeros(NSEG, bool)
for s_ in gotF & gotG: SEG_SEP[s_] = True
# Residual non-enhancing (FLAIR) tumour: each FLAIR voxel belongs to its nearest boundary segment; near-function segments that are not
# separable keep their FLAIR tissue (only the core is removed), low-risk segments can be resected; compare with the 5.4 mL threshold
NCE_INFO = None
try:
    _nk = np.argwhere(lab == 2)
    if len(_nk) and NSEG:
        _vml = float(np.prod(sp_mm))/1000.0
        _ras = (IJK2RAS @ np.c_[_nk[:, ::-1], np.ones(len(_nk))].T)[:3].T
        _own = cKDTree(SEGC).query(_ras)[1]
        _cnt = np.bincount(_own, minlength=NSEG)*_vml
        _keep_inb = SEG_REQ & ~SEG_SEP
        _keep_std = SEG_REQ.copy(); _keep_std[list(STRIP_SEP_SET)] = False
        NCE_INFO = dict(total=round(float(_cnt.sum()), 1), res_inb=round(float(_cnt[_keep_inb].sum()), 1),
                        res_std=round(float(_cnt[_keep_std].sum()), 1), res_core_only=round(float(_cnt.sum()), 1), thr=NCE_THR)
except Exception as _e:
    print("NCE residual:", _e)
gotS = set().union(*[p["r"]["cs"] for p in plan]) if plan else set()
gotR = set().union(*[p["r"]["cr"] for p in plan]) if plan else set()
# 定骨窗用的肿瘤投影：沿骨窗法向（术者视线）把强化核心平行投到最外层皮层上，DW = 横向距离 mm
DW = np.full(len(SP), np.inf)
for _t in np.arange(0.0, 80.1, 2.0):
    DW = np.minimum(DW, sample(d_core_vol, SP - WIN_N*_t))
_proj = (DW <= 0) & VISIBLE
WIN_CHECK["proj_in"] = float(-SDF[_proj].max()) if _proj.any() else float("nan")       # 肿瘤投影离骨窗边缘最近多少 mm（负 = 投影伸出骨窗）
WIN_CHECK["expose"] = float(DW[(SDF <= 0) & VISIBLE].max()) if ((SDF <= 0) & VISIBLE).any() else float("nan")   # 骨窗露出肿瘤投影外最远多少 mm
# ---- 没判定完的段：为什么、下一步怎么办 ----
# 原因：hidden 从骨窗看不到（沟底、侧面）/ unreach 骨窗加可伸入范围都够不着 / edge 只确认了边界、缺外侧 SUPRA mm 的点 / budget 片数用完 /
#       vein 能放但压静脉扣分比收益大 / blocked 盖得到它的位置都不合格（贴合、形变、压核心、伸出太多）/ nofit 没有哪片能同时贴到它的边界和外侧
_axes = (("前", "anterior", np.array([0, 1.0, 0])), ("后", "posterior", np.array([0, -1.0, 0])),
         ("上", "superior", np.array([0, 0, 1.0])), ("下", "inferior", np.array([0, 0, -1.0])))
def _dir(v):
    v = v - (v @ WIN_N)*WIN_N; zh, en, _ = max(_axes, key=lambda a: v @ a[2]); return zh, en
_WHY_ZH = dict(fit="贴合不良", outside="超出骨窗过多", core="覆盖肿瘤核心", strain="形变过大", vein="覆盖静脉")
_WHY_EN = dict(fit="poor fit", outside="too far under the bone", core="over the core", strain="too much strain", vein="on a vein")
SEG_WHY = []
for s_ in np.where(SEG_REQ & (SEG_DONE < 2))[0]:
    c_ = SEGC[s_]; dz, de = _dir(c_ - entry); src_ = seg_src[s_]
    if not SEG_ARR[s_]:
        _raw = float(win_sdf(c_[None])[0])
        if _sdf_seg[s_] >= 900 or _raw >= 900:          # 从骨窗看不到：在脑沟深处、侧面或另一面
            k_, zh_, en_ = "hidden", "位于该骨窗视野外（脑沟深部或脑的侧面/底面），阵列和探针均无法到达；按影像切除，或以术中超声 / 皮层下刺激确认", \
                           "not visible from this window (deep in a sulcus or on another face of the brain); neither arrays nor the probe reach it: follow imaging, or confirm with ultrasound / subcortical stimulation"
        else:
            mv = int(np.ceil(_raw - SLIDE))
            k_, zh_, en_ = "unreach", f"将骨窗向{dz}移动或扩大约 {mv} mm；骨窗不变时按影像切除", f"move or enlarge the window about {mv} mm {de}; otherwise follow imaging only"
    elif SEG_DONE[s_] == 1:
        _out = np.where((np.linalg.norm(SP - c_, axis=1) <= SUPRA + 0.6*SEG_LEN) & (np.abs(DD - SUPRA) <= 3.0))[0]
        if len(_out) and (SDF[_out] <= 0).any(): k_, zh_, en_ = "edge", f"边界已确认；外侧 {SUPRA:g} mm 处位于骨窗内，以手持探针补测一点即可完成判定", f"edge confirmed; the point {SUPRA:g} mm outside is exposed, one hand-held probe test decides it"
        elif len(_out) and (SDF[_out] <= SLIDE).any(): k_, zh_, en_ = "edge", f"边界已确认；外侧 {SUPRA:g} mm 处位于骨窗边缘下，需增加一次垂直于边界的放置或更换方向", f"edge confirmed; the point {SUPRA:g} mm outside is under the bone edge, add an array placed outward or change the angle"
        else: k_, zh_, en_ = "edge", f"边界已确认；外侧 {SUPRA:g} mm 处无法到达，该段按核心边界切除，不扩大", f"edge confirmed; the point {SUPRA:g} mm outside is out of reach, resect to the core edge only"
    else:
        cov = [r for r in rows if s_ in r["seg_full"]]; okc = [r for r in cov if r["ok"]]
        if okc:
            r_ = max(okc, key=lambda r: len(r["seg_full"] - gotF))
            if BUDGET > 0 and len(plan) >= BUDGET: k_ = "budget"; zh_, en_ = f"放置次数已满；可增加 1 次放置（候选 {r_['cand']}，{r_['angle']}°）", f"placement budget used; add one (candidate {r_['cand']}, {r_['angle']}°)"
            else: k_ = "vein"; zh_, en_ = f"可行位置压在静脉上，扣分超过收益；可增加 1 次放置（候选 {r_['cand']}，{r_['angle']}°）或用探针", f"the possible placement sits on veins and was not worth it; add one (candidate {r_['cand']}, {r_['angle']}°) or use the probe"
        elif cov:
            from collections import Counter
            top = Counter(w for r in cov for w in r["why"]).most_common(1)[0][0]
            k_ = "blocked"; tail_zh = "改用手持探针" if SEG_PROBE[s_] else f"位于骨窗边缘下，探针无法到达；将骨窗向{dz}移动"
            tail_en = "use the hand-held probe" if SEG_PROBE[s_] else f"under the bone edge and out of probe reach, move the window {de}"
            zh_, en_ = f"无合格放置（{_WHY_ZH[top]}）；{tail_zh}", f"no valid array position ({_WHY_EN[top]}); {tail_en}"
        else:
            k_ = "nofit"; zh_ = "无放置能同时覆盖边界和外侧测试点；" + ("用手持探针" if SEG_PROBE[s_] else f"将骨窗向{dz}移动")
            en_ = "no array reaches both the edge and the outer point; " + ("use the hand-held probe" if SEG_PROBE[s_] else f"move the window {de}")
    SEG_WHY.append(dict(seg=int(s_), src=str(src_), kind=k_, zh=zh_, en=en_, done=int(SEG_DONE[s_]), pos=c_.tolist()))
for s_ in np.where(SEG_REQ & (SEG_DONE == 2) & ~SEG_SEP)[0]:       # 功能可判，但缺记录梯度
    SEG_WHY.append(dict(seg=int(s_), src=str(seg_src[s_]), kind="grad", zh="功能可判定，但缺少跨边界的记录梯度；增加一次垂直于边界的放置，覆盖边界内外 15 mm",
                        en="function decidable but no recording gradient across the boundary; add a placement perpendicular to the boundary covering 15 mm inside and outside",
                        done=2, pos=SEGC[s_].tolist()))
from collections import Counter as _C
WHY_COUNTS = dict(_C(w["kind"] for w in SEG_WHY))
BND = dict(n_seg=NSEG, n_req=int(SEG_REQ.sum()), n_arr=int(SEG_ARR.sum()), n_probe=int(SEG_PROBE.sum()),
           full=int((SEG_DONE == 2).sum()), edge=int((SEG_DONE >= 1).sum()), seg_len=SEG_LEN, supra=SUPRA, src=BND_SRC,
           under_bone=int((SEG_ARR & ~SEG_PROBE).sum()), unreach=int((SEG_REQ & ~SEG_ARR).sum()),
           req_src={k: int((SEG_REQ & (seg_src == k)).sum()) for k in TRACT_MASK},
           zones=ZONE_COUNTS, radial_inb=RADIAL_INB, radial_strip=RADIAL_STRIP,
           strip_n=STRIP_N, strip_placements=len(SPLAN), strip_full=STRIP_FULL, strip_edge=STRIP_EDGE, why=WHY_COUNTS,
           sep=int(SEG_SEP.sum()), strip_sep=STRIP_SEP)
# boundary localisation: half the recording pitch; for separable segments the difference is the safety margin that need not be kept
BND.update(nce=NCE_INFO)
BND.update(loc_inb=PITCH/2, loc_std=STRIP_PITCH/2, margin_cm2=round(BND['sep']*SEG_LEN*max(STRIP_PITCH - PITCH, 0)/2/100, 1))
print(f"\n切除边界（{BND_SRC}）共 {NSEG} 段（每段约 {SEG_LEN:g} mm），靠近功能区要定位 {BND['n_req']} 段；"
      f"阵列完整判定 {BND['full']} 段、至少确认边界 {BND['edge']} 段；手持探针够得着 {BND['n_probe']} 段，骨窗边缘下 {BND['under_bone']} 段")

# 排顺序：含 AF 刺激点（清醒期，语言）→ 含 CST 刺激点（可麻醉下 MEP）→ 只记录
def phase(r):
    if r.get("ref"): return 3, "只记录·健康参照"
    if "AF" in r["srcs"]: return 0, "清醒期·语言刺激"
    if r["srcs"]: return 1, "运动刺激（可麻醉下）"
    return 2, "只记录"
plan.sort(key=lambda p: phase(p["r"])[0])
print(f"\n窗口内可达：刺激目标 {len(reachS)} 点 {cntK}，记录目标 {len(reachR)} 点；目标 每条束刺激 {GOAL_STIM:.0%} + 记录 {GOAL_REC:.0%}")
cs_, cr_ = set(), set()
for k, p in enumerate(plan, 1):
    r = p["r"]; cs_ |= r["cs"]; cr_ |= r["cr"]
    covs = " ".join(f"{kk} {nk(cs_, kk)/cntK[kk]:.0%}" for kk in KEYS)
    print(f"  第 {k} 次 [{phase(r)[1]}]：候选 {r['cand']}，角度 {r['angle']}°，累计 刺激 {covs} / 记录 {len(cr_)/totRr:.0%}")
print(f"→ 需要放 {len(plan)} 次（参考区超出骨窗可达范围：刺激 {S_out} / 记录 {R_out} 点）")
PLACEMENTS_NEEDED = len(plan)
VEIN_VIOL = sum(p["r"]["vein_n"] for p in plan); MAX_STRAIN_PLAN = max([p["r"]["strain"] for p in plan] + [0.0])
print(f"静脉安全距离 {VEIN_SAFE} mm 内的触点：{VEIN_VIOL}；最大触点间距形变 {MAX_STRAIN_PLAN:.0%}")
PLAN = plan
# 计划表里每片的覆盖率和结果区用同一个分母：骨窗内有放置够得着的目标
_totSr = max(sum(stim_w[i] for i in reachS), 1e-9)
for _p in plan: _p["r"]["stim"] = sum(stim_w[i] for i in _p["r"]["cs"])/_totSr; _p["r"]["rec"] = len(_p["r"]["cr"])/totRr

_P(0.88, "时间估计|Time estimate")
# ================= 7b 时间估计 =================
# 先算“数量”（与时间参数无关），再按情景算时间；数量另存 JSON，敏感性分析脚本直接用
# 阵列：按计划顺序，每片在新目标上挑最少的大触点（贪心），每个挑中的触点算一个刺激位点
# 每片要刺激的位点 = 新判定段 × 2（边界上 + 边界外 SUPRA mm）+ 只确认边界的段 × 1；靠 AF 的段算语言位点
lang_k, motor_k = [], []
for p in plan:
    r = p["r"]; nl = nm_ = 0
    for s_, n_ in [(x, 2) for x in r.get("seg_new_full", ())] + [(x, 1) for x in r.get("seg_new_edge", ())]:
        if seg_src[s_] in ("AF", "fMRI", "nTMS-L"): nl += n_     # fMRI 激活段按语言任务算
        else: nm_ += n_
    lang_k.append(nl); motor_k.append(nm_)
n_lang, n_motor = sum(lang_k), sum(motor_k)

# 标准流程（现实版）：手持探针只能碰到骨窗里露出的皮层，按 PROBE_GRID（1 cm）网格逐点刺激，
# 网格点 5 mm 内有刺激目标的都要测（临床按约 1 cm 间距系统刺激、贴标签）
# 传统流程（同一标准）：手持探针只能碰到骨窗里露出的皮层；每个够得着的待判定段同样测 2 个点（边界上 + 外 SUPRA mm），
# 骨窗边缘下的段探针够不着，只能按影像保守处理（不扩大切除）
in_win_S = [i for i in reachS if in_win[i]]
pg_lang = int(2*(SEG_PROBE & (seg_src == "AF")).sum()); pg_motor = int(2*(SEG_PROBE & (seg_src != "AF")).sum())
pg_cov = float(SEG_PROBE.sum() / max(SEG_REQ.sum(), 1)); pg_cov_grid = pg_cov; pg_extra = 0
# 参考：探针“任意位置、最优覆盖”（理想化，偏乐观）
po_lang = po_motor = 0
if reachS:
    cand_pts = np.array(sorted(reachS)); ptree = cKDTree(SP[cand_pts])
    cover = [set(cand_pts[j] for j in ptree.query_ball_point(SP[g], STIM_REACH)) for g in cand_pts]
    gotp = set()
    while short(gotp):
        sk = short(gotp)
        k = max(range(len(cand_pts)), key=lambda j: sum(nk(cover[j] - gotp, kk)/cntK[kk] for kk in sk))
        new = cover[k] - gotp
        if not new or not any(stim_src[i] in sk for i in new): break
        gotp |= new
        if any(stim_src[i] == "AF" for i in new): po_lang += 1
        else: po_motor += 1

COUNTS = dict(device=f"{NX}x{NY}", placements=len(plan), lang_k=lang_k, motor_k=motor_k,
              probe_grid_lang=pg_lang, probe_grid_motor=pg_motor, probe_grid_cov=pg_cov, probe_grid_cov_1cm=pg_cov_grid, probe_extra=pg_extra,
              probe_opt_lang=po_lang, probe_opt_motor=po_motor,
              strip_lang_k=strip_lang_k, strip_motor_k=strip_motor_k, strip_placements=len(SPLAN), n_mon=int(SEG_ARR.sum()))

import sys
for _d in [os.environ.get("SCRIPTS", ""), os.path.dirname(globals().get("__file__", "") or "")]:
    if _d and os.path.exists(os.path.join(_d, "time_model.py")) and _d not in sys.path: sys.path.insert(0, _d)
import importlib, time_model; importlib.reload(time_model)
from time_model import scenario_times

PARAMS = dict(T_PLACE=T_PLACE, T_LANG=T_LANG, T_MOTOR=T_MOTOR, OV_PROBE=OV_PROBE, OV_ARRAY=OV_ARRAY,
              MOTOR_AWAKE=MOTOR_AWAKE, T_PASSIVE=T_PASSIVE, P_TRUE=P_TRUE, SENS=SENS, SPEC=SPEC,
              F_CCEP=F_CCEP, T_CCEP=T_CCEP, CCEP_SENS=CCEP_SENS, ASLEEP_FIRST=ASLEEP_FIRST,
              STRIP_PLACE_STD=STRIP_PLACE_STD, PASSIVE_ASLEEP=PASSIVE_ASLEEP, AD_STRIP=globals().get("AD_STRIP", True), AWAKE_WINDOW=AWAKE_WINDOW, T_WAKE=T_WAKE, PASSIVE_N=PASSIVE_N, STRIP_CCEP_EXTRA=STRIP_CCEP_EXTRA, T_BASE=T_BASE, T_MON=T_MON, LIT_SITES=13.1)
SC = scenario_times(COUNTS, PARAMS)
TIME = dict(placements=len(plan), awake_placements=int((np.array(lang_k) > 0).sum()), lang_sites=n_lang, motor_sites=n_motor,
            scen=SC, counts=COUNTS)
names = dict(MAIN="INBRAIN主方案(CCEP筛+醒后先记录)", A="逐点刺激", B="先记录后刺激", C="麻醉下CCEP筛+醒后刺激阳性点", STD="传统流程·1×4条带同流程+手持探针", STD_probe="常规做法·探针逐点不筛选", STD_opt="商用条带方案·探针理想最优", STD_lit="商用条带方案·文献典型病例(13位点)")
print(f"\n时间估计（{NX}×{NY}，假设参数）：放置 {len(plan)} 次，语言位点 {n_lang} / 运动 {n_motor}；探针网格 语言 {pg_lang} / 运动 {pg_motor}（覆盖 {pg_cov:.0%}）")
for k, v in SC.items():
    print(f"  {names[k]}：清醒期 {v['awake']:.1f} min（{v['awake']/AWAKE_WINDOW:.0%}），麻醉期额外 {v['asleep']:.1f}，全部 {v['total']:.1f} min，估计漏掉 {v['missed']:.1f}")
import json
_json_dir = os.path.dirname(OUT) if OUT else os.path.dirname(tumor.GetStorageNode().GetFileName())
json.dump(dict(counts=COUNTS, params=PARAMS), open(os.path.join(_json_dir, f"counts_{NX}x{NY}.json"), "w"), ensure_ascii=False, indent=1)

_P(0.93, "画进场景|Drawing scene")
# ================= 8 画进场景 =================
def cloud(name, pts, color, radius, opacity=1.0):
    old = slicer.util.getFirstNodeByName(name)
    if old: slicer.mrmlScene.RemoveNode(old)
    if len(pts) == 0: return None
    P = vtk.vtkPoints()
    for q in pts: P.InsertNextPoint(*q)
    pd = vtk.vtkPolyData(); pd.SetPoints(P)
    sph = vtk.vtkSphereSource(); sph.SetRadius(radius); sph.SetThetaResolution(8); sph.SetPhiResolution(8)
    g = vtk.vtkGlyph3D(); g.SetInputData(pd); g.SetSourceConnection(sph.GetOutputPort()); g.ScalingOff(); g.Update()
    md = slicer.modules.models.logic().AddModel(g.GetOutput()); md.SetName(name)
    dn = md.GetDisplayNode(); dn.SetColor(*color); dn.SetOpacity(opacity); dn.SetScalarVisibility(False)
    return md
def patch(name, mask, color, opacity=1.0, lift=0.4):
    """把脑表面上 mask 为真的三角面单独取出来，沿法向抬高一点，画成带颜色的面（代替密集的点）"""
    old = slicer.util.getFirstNodeByName(name)
    if old: slicer.mrmlScene.RemoveNode(old)
    src = nm.GetOutput(); polys = nps.vtk_to_numpy(src.GetPolys().GetData())
    if len(polys) == 0 or not polys.size % 4 == 0: return None
    tri = polys.reshape(-1, 4)[:, 1:]
    keep = tri[mask[tri].sum(1) >= 2]                      # 三个顶点里至少两个在区域内
    if not len(keep): return None
    P = vtk.vtkPoints(); P.SetData(nps.numpy_to_vtk(SP + SN*lift, deep=True))
    C = vtk.vtkCellArray()
    C.SetCells(len(keep), nps.numpy_to_vtkIdTypeArray(np.hstack([np.full((len(keep), 1), 3), keep]).astype(np.int64).ravel(), deep=True))
    pd = vtk.vtkPolyData(); pd.SetPoints(P); pd.SetPolys(C)
    cl = vtk.vtkCleanPolyData(); cl.SetInputData(pd); cl.Update()
    md = slicer.modules.models.logic().AddModel(cl.GetOutput()); md.SetName(name)
    dn = md.GetDisplayNode(); dn.SetColor(*color); dn.SetOpacity(opacity); dn.SetScalarVisibility(False); dn.SetBackfaceCulling(False)
    return md
if SHOW:
    # 刺激/记录目标现在不参与摆放打分（规划只看边界段），只作参考，所以画成半透明的面而不是点
    _m = lambda idx: np.isin(np.arange(len(SP)), idx)
    patch("Targets_stim", _m(S_idx), (1.0, 0.45, 0.1), 0.50)
    patch("Targets_rec", _m(R_idx), (0.35, 0.65, 1.0), 0.35)
    patch("Targets_out", (is_stim | is_rec) & ~in_reach, (0.6, 0.6, 0.6), 0.30)
    ringpts = SP[np.abs(SDF) < 1.0][::2]
    cloud("Window_edge", ringpts, (0.25, 0.25, 0.25), 0.5)
    if len(VEIN_PTS): cloud("Veins_surface", VEIN_PTS[::4], (0.15, 0.18, 0.50), 0.6, 0.85)
    cloud("Entry_point", entry[None], (0.1, 0.1, 0.1), 2.5)
    # 切除边界分段：绿 = 阵列完整判定（能决定多切 SUPRA mm），黄 = 只确认边界，红 = 靠功能区但够不着，灰 = 远离功能区（按影像切）
    if NSEG:
        cloud("Boundary_decided", SEGC[SEG_SEP], (0.10, 0.80, 0.35), 2.0)
        cloud("Boundary_function_only", SEGC[(SEG_DONE == 2) & ~SEG_SEP], (0.0, 0.65, 0.75), 2.0)
        cloud("Boundary_edge_only", SEGC[(SEG_DONE == 1)], (1.0, 0.75, 0.0), 2.0)
        cloud("Boundary_open", SEGC[SEG_REQ & (SEG_DONE == 0)], (0.95, 0.15, 0.15), 2.0)
        cloud("Boundary_low_risk", SEGC[~SEG_REQ], (0.6, 0.6, 0.6), 1.4, 0.8)
        cloud("Boundary_line", SP[_bnd][::2], (0.95, 0.95, 0.95), 0.4, 0.7)
    q = np.quantile(ENTRY_MAP["score"], [0.5, 0.85])
    pts, sc = ENTRY_MAP["points"], ENTRY_MAP["score"]
    cloud("EntryMap_good", pts[sc >= q[1]], (0.1, 0.75, 0.2), 0.9)
    cloud("EntryMap_mid", pts[(sc >= q[0]) & (sc < q[1])], (0.95, 0.85, 0.2), 0.8)
    cloud("EntryMap_poor", pts[sc < q[0]], (1.0, 0.55, 0.1), 0.7)
    cloud("EntryMap_excluded", ENTRY_MAP["excluded"][::8], (0.35, 0.35, 0.35), 0.6, 0.6)
    for nm_ in ["EntryMap_good", "EntryMap_mid", "EntryMap_poor", "EntryMap_excluded"]:
        nd_ = slicer.util.getFirstNodeByName(nm_)
        if nd_: nd_.GetDisplayNode().SetVisibility(False)
    for nd in list(slicer.util.getNodesByClass("vtkMRMLModelNode")):
        if nd.GetName().startswith("Plan_"): slicer.mrmlScene.RemoveNode(nd)
    for k, p in enumerate(plan, 1):
        cloud(f"Plan_{k}_large", p["r"]["L"], (0.20, 0.25, 0.35), 1.3 if NX > 1 else 2.0)
        cloud(f"Plan_{k}_small", p["r"]["S"], (0.55, 0.60, 0.68), 0.7)

_P(0.98, "保存表格|Saving tables")
# ================= 9 CSV =================
if OUT is None:
    fn = tumor.GetStorageNode().GetFileName() if tumor.GetStorageNode() else os.path.expanduser("~/x")
    OUT = os.path.join(os.path.dirname(fn), f"placement_scores_{NX}x{NY}.csv")
with open(OUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["rank", "candidate", "angle", "stim_cov", "rec_cov", "fit_max_mm", "score", "pass", "stim_tracts"])
    for k, r in enumerate(rows, 1):
        w.writerow([k, r["cand"], r["angle"], f"{r['stim']:.4f}", f"{r['rec']:.4f}", f"{r['fit']:.2f}", f"{r['score']:.4f}", r["ok"], "+".join(sorted(r["srcs"]))])
    w.writerow([]); w.writerow(["plan_step", "phase", "candidate", "angle", "stim_tracts"])
    for k, p in enumerate(plan, 1):
        w.writerow([k, phase(p["r"])[1], p["r"]["cand"], p["r"]["angle"], "+".join(sorted(p["r"]["srcs"]))])
    w.writerow([]); w.writerow(["scenario", "awake_min", "asleep_extra_min", "total_min", "missed"])
    for k, v in SC.items(): w.writerow([names[k], f"{v['awake']:.1f}", f"{v['asleep']:.1f}", f"{v['total']:.1f}", f"{v['missed']:.1f}"])
    w.writerow([]); w.writerow(["targets_in_window_stim", len(S_idx), "rec", len(R_idx), "out_stim", S_out, "out_rec", R_out])
print("已存:", OUT)
