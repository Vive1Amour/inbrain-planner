# 界面语言和中英文对照表 / interface language and translation table
import qt, slicer

# ---------------- 界面语言：跟随 Slicer / 中文 / English ----------------
LANG_KEY = "INBRAINPlanner/Language"          # 0 跟随 Slicer，1 中文，2 English


def lang_choice():
    try: return int(qt.QSettings().value(LANG_KEY, 2))      # English edition: English unless changed
    except Exception: return 0


def lang():
    c = lang_choice()
    if c == 1: return "zh"
    if c == 2: return "en"
    try: sl = str(slicer.app.userSettings().value("language") or "")
    except Exception: sl = ""
    return "zh" if sl.lower().startswith("zh") else "en"


def T(s):
    """中文界面原样返回；英文界面查 EN 表，查不到就原样"""
    return s if lang() == "zh" else EN.get(s, s)


def L(zh, en):
    return zh if lang() == "zh" else en


def DISCLAIMER():
    return L("仅供术前规划参考，不能替代术中电生理监测与临床判断。", "For pre-operative planning support only; does not replace intra-operative monitoring or clinical judgement.")


EN = {
    "边界段风险已按脑区阳性概率加权（中央前回、额下回岛盖部、颞上/中回后部、缘上回最高）。": "Boundary segment risk weighted by regional positive probability (precentral, pars opercularis, posterior superior/middle temporal and supramarginal highest).",
    # 分区
    "① 数据（下载的病例文件夹）": "① Data (downloaded case folder)", "② 器件参数": "② Device parameters",
    "先评分再定骨窗（按选定放置调整骨窗位置和大小）": "Score first, then fit the bone window (shrink and move it to the chosen placements)",
    "上面的骨窗尺寸当作最大可开范围：先在里面选放置，再找能放下这些阵列和肿瘤投影的最小骨窗，重跑一遍；判定段不减少、放置次数不增加才采用": "The window size above is the largest allowed opening: placements are chosen inside it, then the smallest window that still holds those arrays and the tumour footprint is found and the plan is rerun; it is kept only if no boundary segment is lost and no placement is added",
    "方位字母和外框": "Axis letters and box", "缺记录梯度": "no recording gradient", "这两类区域只用来给开颅入口打分、在 3D 里作参考；阵列放在哪由切除边界段决定": "These areas only score the craniotomy entry and serve as a 3D reference; array placement is decided by the resection boundary segments", "INBRAIN 流程": "INBRAIN workflow", "传统流程（1×4 条带）": "Conventional (1×4 strip)", "输出位置": "Output location", "结果文件夹：": "Result folder: ", "结果放在这里的“病例文件夹名_Slicer”子文件夹里；默认是病例文件夹所在的目录": "Results go into a “<case folder>_Slicer” subfolder here; by default the folder that contains the case folder", "打开结果文件夹": "Open result folder", "导出到": "Export to", "汇报图、网页版 3D、报告、导航坐标都存到这个文件夹；选一次会记住": "Figure, web 3D, report and navigation files are saved here; remembered once chosen", "打开导出文件夹": "Open export folder",
    "刺激范围按电流算": "Stimulation reach from current",
    "激活半径 r = √(I/k) + 触点半径；语言段按 Penfield 双极，运动段按 Taniguchi 单极。不勾 = 固定 3 mm 判定容差": "Activation radius r = √(I/k) + contact radius ; language segments use Penfield bipolar, motor segments Taniguchi monopolar. Unticked = fixed 3 mm decision tolerance",
    "要有健康参照触点": "Require healthy reference contacts",
    "离 FLAIR 边界 > 30 mm 的触点当病人内对照，比较病灶、瘤周和健康皮层的 ECoG（Díaz-Fernández 2025）": "Contacts more than 30 mm from the FLAIR border serve as a within-patient reference for comparing ECoG over lesion, peritumoral and healthy cortex (Díaz-Fernández 2025)",
    "术前 fMRI（可选）": "Pre-operative fMRI (optional)",
    "可选：术前任务 fMRI 的 z 值图（NIfTI，与 T1c 同一空间），用于给边界段风险加权": "Optional: task fMRI z map (NIfTI, same space as T1c), used to weight boundary segment risk",
    "传统流程加一条后放电监测条带": "Add an after-discharge monitoring strip to the conventional workflow",
    "探针刺激时需在旁放置一条 ECoG 条带监测后放电（参考资料）：增加一条条带的器件费；麻醉期放置一次，清醒期每更换刺激区域重新放置一次。INBRAIN 阵列由刺激触点周围的记录触点监测": "Probe stimulation needs a separate ECoG strip next to it to watch for after-discharges (reference material p5): one more strip, placed once asleep and moved for every new awake region. The INBRAIN array monitors itself",
    "刺激电流 mA": "Stimulation current mA", "Penfield 法 1 mA 起、最高 20 mA": "Penfield: from 1 mA up to 20 mA",
    "兴奋常数 k µA/mm²": "Excitability k µA/mm²", "激活半径 r = √(I/k)；1292 = 皮层锥体细胞": "Activation radius r = √(I/k); 1292 = cortical pyramidal cells ",
    "大触点直径 mm": "Large contact diameter mm", "参考资料：INBRAIN 约 1 mm": "Reference material: INBRAIN about 1 mm",
    "双极半径系数": "Bipolar radius factor", "双极刺激电流集中在两触点之间，半径按单极的这个比例": "Bipolar current stays between the two contacts; radius is this fraction of the monopolar one",
    "条带触点暴露直径 mm": "Strip exposed contact diameter mm", "Ad-Tech 4 mm 触点暴露 2.3 mm": "Ad-Tech 4 mm contacts expose 2.3 mm",
    "fMRI z 阈值": "fMRI z threshold", "术前 fMRI（可选）": "Pre-operative fMRI (optional)", "fMRI 权重": "fMRI weight", "段风险 × (1 + 权重 × 激活)": "Segment risk × (1 + weight × activation)",
    "一个大触点刺激能查到的范围（勾“刺激范围按电流算”时不用）": "Range one large contact can test by stimulation (not used when reach is computed from current)",
    "只记录·健康参照": "Record only · healthy reference",
    "导出边界段书签": "Export segment bookmarks", "段": "Segment", "现状": "Status", "下一步": "Next step", "点一行，3D 视图转到这一段": "Click a row to turn the 3D view to this segment", "S/I/A/P/R/L 字母贴在场景包围盒的面上，只有和外框一起看才不错位": "The S/I/A/P/R/L letters sit on the faces of the scene bounding box; they only line up when the box is shown too",
    "③ 参考目标区（刺激区 / 记录区）": "③ Reference target areas (stimulation / recording)",
    "④ 开颅位置和骨窗": "④ Craniotomy site and bone window", "⑤ 优化目标和打分权重": "⑤ Optimisation goals and score weights",
    "⑥ 术中时间参数": "⑥ Intra-operative time parameters", "结果": "Results", "运行日志": "Log",
    # 数据
    "病例文件夹": "Case folder", "病例编号": "Case ID", "工作目录": "Work folder", "肿瘤侧别": "Tumour side", "梯度翻转": "Gradient flip",
    "自动判断": "Auto-detect", "R 右侧": "R (right)", "L 左侧": "L (left)", "自动检测": "Auto-detect",
    "例如 …/UCSF-PDGM-0007_nifti，里面要有 DTI_eddy_noreg、bvec、T1c、分割文件": "e.g. …/UCSF-PDGM-0007_nifti; must contain DTI_eddy_noreg, bvec, T1c and segmentation files",
    "必须是纯英文路径（Slicer 命令行模块要求）": "Must be an ASCII-only path (required by Slicer CLI modules)",
    "梯度表翻转；自动检测约多 10 分钟": "Gradient-table flip; auto-detect adds about 10 min",
    "预处理（张量 → 配准 → 纤维束）": "Preprocess", "预处理": "Preprocess",
    "张量 → 配准 → 纤维束（后台 Slicer 运行，不弹窗口）": "Tensor → registration → tracts (runs in a background Slicer, no window)", "载入场景": "Load scene",
    "CST 种子 FA": "CST seed FA", "CST 停止 FA": "CST stopping FA", "AF 种子 FA": "AF seed FA", "AF 停止 FA": "AF stopping FA",
    "穿过水肿带时需降低": "Lower it to pass through oedema",
    # 器件
    "预设": "Preset", "自定义（导入 JSON）": "Custom (import JSON)", "大触点之间有只记录的小触点": "Record-only small contacts between large contacts",
    "导入器件 JSON": "Import device JSON", "导出器件 JSON": "Export device JSON",
    "INBRAIN 3×7 + 小触点": "INBRAIN 3×7 + micro-contacts",
    "传统条带 1×4（间距 10 mm）": "Conventional strip 1×4 (10 mm spacing)", "传统条带 1×8": "Conventional strip 1×8", "传统栅格 4×5": "Conventional grid 4×5",
    "大触点列数": "Large-contact columns", "大触点行数": "Large-contact rows", "触点间距 mm": "Contact pitch mm",
    "刺激半径 mm": "Stimulation radius mm", "大触点记录 mm": "Large-contact rec. mm", "小触点记录 mm": "Small-contact rec. mm",
    "贴合误差 mm": "Max fit error mm", "旋转步长 °": "Rotation step °",
    "阵列横向大触点个数": "Number of large contacts across", "阵列纵向大触点个数": "Number of large contacts along",
    "相邻大触点中心距离": "Centre-to-centre distance of large contacts", "一个大触点刺激能查到的范围": "Area one large contact can test by stimulation",
    "触点投影到皮层前后的最大位移；超过该值视为贴合不良": "Max distance between flat and projected contact; above it the array does not conform",
    "每个候选位置试几个方向（0–180°）": "Orientations tried at each candidate (0–180°)",
    # 目标
    "纤维束入口 mm": "Tract entry mm", "刺激距病灶 mm": "Stim-to-lesion mm",
    "CST 权重": "CST weight", "AF 权重": "AF weight", "离 FLAIR mm": "To FLAIR mm",
    "记录圈宽 mm": "Recording ring mm", "记录距病灶 mm": "Rec-to-lesion mm",
    "刺激区：离纤维束这么近算入口": "Stimulation area: this close to a tract counts as an entry", "刺激区：只看切除边缘附近": "Stimulation area: only near the resection margin",
    "0 = CST 附近的边界段不需要定位": "0 = boundary segments near CST need no mapping",
    "右侧病例 AF 不一定是语言优势侧；左侧建议 1": "Right-sided AF may be non-dominant; use 1 for left-sided cases",
    "记录区：FLAIR 带上方这么近": "Recording area: this close above the FLAIR zone", "记录区：刺激区外的环形带（用于监测后放电）": "Recording area: ring around the stimulation area (after-discharges)",
    # 开颅
    "入口点": "Entry point", "自动：可开颅区域里评分最高": "Auto: best score in feasible region",
    "离肿瘤核心最近的皮层点": "Cortex point closest to tumour core", "手动：用我放的 Entry 点": "Manual: use my Entry point",
    "在 3D 里放 Entry 点": "Place Entry point in 3D", "骨窗半径 mm": "Window radius mm", "骨窗下伸入 mm": "Window slide mm", "肿瘤投影外至少 mm": "Min margin around tumour mm", "肿瘤投影外最多 mm": "Max margin around tumour mm",
    "收紧骨窗时，肿瘤皮层投影外至少留这么宽（小骨窗定义 ≤ 1 cm）": "Smallest margin kept around the tumour's cortical projection when fitting (small craniotomy ≤ 1 cm)",
    "定制骨窗一般只露出肿瘤外 2–3 cm，超过时提示": "Tailored windows usually expose 2–3 cm around the tumour; flagged when exceeded",
    "中线禁区 mm": "Midline exclusion mm", "中线扣分 mm": "Midline caution mm", "颅底阈值": "Skull-base thr.",
    "低位扣分": "Low-lateral penalty", "约 7 cm 骨瓣": "About a 7 cm bone flap",
    "电极片能滑到骨窗边缘下面多远": "How far the array can slide under the window edge", "上矢状窦、大脑镰": "Superior sagittal sinus, falx",
    "皮层法向 z 低于它 = 颅底面，不开": "Cortex normal z below this = skull base, excluded",
    "全脑高度最低这一比例的外侧皮层扣分": "Lateral cortex in this lowest height fraction is penalised",
    # 优化
    "刺激覆盖目标 %": "Stim. goal %", "记录覆盖目标 %": "Recording coverage goal %",
    "权重·刺激": "Weight: stim.", "权重·记录": "Weight: rec.",
    "权重·贴合": "Weight: fit", "被动高 γ 定位对比电刺激": "Passive high-gamma mapping vs stimulation ",
    "被动定位放在麻醉期（全麻下听觉任务高 γ）": "Passive mapping under anaesthesia (auditory-task high gamma)",
    "麻醉期对每次放置做 CCEP 和被动任务记录；清醒期只对含可疑触点的放置进行刺激确认": "Each array gets CCEP + passive task recording asleep; awake, only arrays with suspicious contacts are revisited for confirmatory stimulation", "触点分区": "Zones (lesion/close/far/healthy)", "边界分段 mm": "Boundary segment mm", "扩大切除 mm": "Extended margin mm",
    "切除边界按这个长度分段，每段需给出是否可扩大切除的结论（1 cm = 临床阴性定位间距）": "The resection boundary is split into segments this long; each needs a resect / keep decision (1 cm = clinical negative-mapping spacing)",
    "每段除边界上的测试点外，在边界外该距离处再设一个测试点；两处均为阴性时，可将该段切除范围扩大此距离": "Besides the contact on the edge, one contact this far outside: if both are negative, this much more can be resected",
    "边界改用 FLAIR 外缘（扩大切除）": "Use the FLAIR outer edge as the boundary (supramaximal)", "判定段": "Segments decided",
    "传统流程（1×4 条带同流程：麻醉期记录筛选 + 清醒期手持探针逐点刺激）": "Conventional (1×4 strips, same workflow: asleep recording screen + awake hand-held probe per site)",
    "常规做法（不筛选，手持探针每段 2 点逐点刺激）": "Usual practice (no screening, hand-held probe, 2 sites per segment)",
    "条带触点数": "Strip contacts", "条带间距 mm": "Strip pitch mm", "只用于“常规做法”和文献病例两行": "Only for the usual-practice and literature rows", "传统流程用的 1×N 商用条带": "1×N commercial strip used by the conventional workflow",
    "切除边界（绿 已判定 / 黄 只确认边界 / 红 未判定）": "Resection boundary (green decided / yellow edge only / red open)", "条带方案覆盖 %": "Conventional coverage %",
    "传统流程按这个刺激覆盖率比较：1 cm 探针网格不够时在空隙补测位点；0 = 只按 1 cm 网格": "The conventional workflow is compared at this stimulation coverage: probe sites are added where the 1 cm grid leaves gaps; 0 = plain 1 cm grid", "阵列避静脉权重": "Array vein weight", "固定片数": "Fixed placements", "最大形变 %": "Max strain %",
    "阵列触点与 SWI 大静脉的距离小于安全距离时，按差值线性扣分（铰链惩罚）；0 = 不考虑静脉": "Hinge penalty for contacts closer than the safety margin to an SWI vein; 0 = off",
    "0 = 放到没有新的边界段可判定为止；N = 只放 N 次，判定尽量多的段": "0 = place until no new boundary segment can be decided; N = exactly N placements, deciding as many segments as possible",
    "阵列贴到皮层后跨阵列的触点间距最多被拉伸或压缩多少": "How much contact spacing across the array may stretch or shrink when it follows the cortex",
    "形变": "Strain", "近静脉": "Near vein", "候选间隔 mm": "Candidate spacing mm", "越小越精细、越慢": "Smaller = finer and slower",
    # 时间
    "放置一次 min": "Place/move one array min", "语言位点 min": "Language site min", "运动位点 min": "Motor site min",
    "探针额外 min": "Probe overhead min", "阵列切换 min": "Array switch min",
    "任务记录 min": "Task recording min", "真语言比例": "True language %",
    "高 gamma 敏感度": "High-gamma sensitivity", "高 gamma 特异度": "High-gamma specificity", "CCEP 阳性比例": "CCEP positive fraction",
    "每片 CCEP min": "CCEP per array min", "CCEP 敏感度": "CCEP sensitivity", "清醒窗口 min": "Awake window min",
    "条带放置次数": "Strip placements", "探针间距 mm": "Probe grid mm", "移动探针、放置编号标签": "Moving the probe, placing tags",
    "第一片阵列麻醉期放好": "First array placed while asleep", "运动定位放在清醒期（否 = 麻醉下 MEP）": "Motor mapping while awake (no = MEP under anaesthesia)",
    # 运行和结果
    "生成方案": "Generate plan", "保存参数": "Save parameters", "读取参数": "Load parameters", "尚未生成方案": "No plan yet",
    "次序": "Order", "阶段": "Phase", "角度": "Angle", "刺激覆盖": "Stim. coverage", "记录区覆盖": "Rec. area coverage", "贴合 mm": "Fit mm", "纤维束": "Tracts",
    "方案": "Approach", "清醒期 min": "Awake min", "麻醉期额外 min": "Extra asleep min", "全部 min": "Total min", "预计漏检位点": "Expected missed sites",
    "显示全部放置": "Show all placements", "显示/隐藏入口评分": "Show/hide entry scores", "保存场景 .mrb": "Save scene .mrb", "打开结果文件夹": "Open result folder",
    "清醒期·语言刺激": "Awake · language stimulation", "运动刺激（可麻醉下）": "Motor stimulation (can be asleep)", "只记录": "Record only",
    "INBRAIN 流程（麻醉期 CCEP 筛选 + 清醒期先记录后刺激）": "INBRAIN workflow (asleep CCEP screening + awake record-then-stimulate)",
    "传统流程（条带记录 + 手持探针，补到同等覆盖）": "Conventional workflow (strip recording + hand-held probe, matched coverage)",
    "传统流程·文献平均病例（13 个位点）": "Conventional workflow · literature average (13 sites)",
    "导入器件 JSON ": "Import device JSON", "保存参数 ": "Save parameters", "读取参数 ": "Load parameters",
    "界面语言": "Language", "跟随 Slicer": "Follow Slicer",
    "显示样式（颜色、透明度）": "Display style (colour, opacity)", "设为默认样式": "Set as default style", "加载默认样式": "Load default style", "恢复出厂样式": "Factory style",
    "恢复为“设为默认”保存的样式；未保存时使用出厂样式": "Back to the style saved with “Set as default”, or the factory style",
    "把现在的颜色、透明度、显示设置存成默认": "Save current colours, opacity and visibility as default",
    "颅骨距脑 mm": "Skull offset mm", "颅骨厚度 mm": "Skull thickness mm", "CT 骨阈值 HU": "CT bone threshold HU",
    "脑表面到颅骨内板：脑脊液 + 硬膜": "Brain surface to inner table: CSF + dura", "成人颅骨约 5–10 mm": "Adult skull about 5–10 mm",
    "用 CT 文件时，高于它算骨": "With a CT file, voxels above this count as bone",
    "自动（有颅骨影像时使用，否则模拟）": "Auto: use skull if present, otherwise simulate", "用颅骨文件（CT 或颅骨分割）": "Use skull file (CT or skull segmentation)",
    "从 MRI 提取（没去颅骨的影像）": "Extract from MRI (non-skull-stripped)", "模拟颅骨": "Simulate skull", "颅骨来源": "Skull source", "颅骨文件": "Skull file",
    "可选：CT（自动按 HU 阈值取骨）或颅骨分割 NIfTI；要和病例 MRI 在同一坐标系": "Optional: CT (bone by HU threshold) or skull segmentation NIfTI, in the same space as the case MRI",
    "生成方案后自动生成颅骨并开出骨窗": "After optimisation, build skull and cut the bone window", "生成颅骨": "Build skull", "显示/隐藏": "Show/hide", "恢复默认样式": "Reset default style",
    # 成本、脑移位、顺序、导出
    "⑦ 成本参数": "⑦ Cost parameters", "⑧ 脑移位分析": "⑧ Brain-shift analysis",
    "手术室 €/min": "OR cost €/min", "清醒加价 €/min": "Awake cost €/min",
    "阵列单价 €": "Array price €", "条带单价 €": "Strip price €",
    "每例片数": "Arrays per case", "每例条数": "Strips per case",
    "按实际采购价填写": "Enter your purchase price", "同一片阵列可多次重新放置": "One array can be moved repeatedly",
    "下沉 mm": "Shift: sinking mm", "侧向 mm": "Shift: lateral mm",
    "开颅后皮层向内塌陷：骨窗中心最大，到可伸出范围边缘减到 0": "Cortex sinks after opening: largest at window centre, zero at the reach edge",
    "沿皮层切向偏移，试 8 个方向": "Shift along the cortex surface, 8 directions tried",
    "运行脑移位分析": "Run brain-shift analysis", "尚未分析": "Not analysed yet",
    "◀ 上一片": "◀ Previous", "下一片 ▶": "Next ▶", "导出汇报图": "Export figure", "生成报告": "Generate report",
    "方案": "Scheme", "时间成本 €": "Time cost €", "器件 €": "Device €", "合计 €": "Total €",
    "放置顺序编号": "Placement order labels", "放置路径": "Placement path",
    "情况": "Case", "导出网页版 3D": "Export web 3D", "取消": "Cancel",
    "骨窗长 mm": "Window length mm", "骨窗宽 mm": "Window width mm", "长轴方向 °": "Long-axis direction °", "圆角半径 mm": "Corner radius mm",
    "椭圆、圆角矩形：沿长轴的全长": "Ellipse / rounded rectangle: full length along the long axis", "椭圆、圆角矩形：垂直长轴的全宽": "Ellipse / rounded rectangle: full width across the long axis",
    "0 = 前后向，90 = 上下向，45 = 前上到后下": "0 = anterior-posterior, 90 = superior-inferior, 45 = antero-superior to postero-inferior", "圆角矩形的四个角": "Corners of the rounded rectangle",
    "骨窗形状": "Window shape", "骨窗预设": "Window preset", "圆形": "Circle", "椭圆": "Ellipse", "圆角矩形": "Rounded rectangle",
    "自定义（按下面的参数）": "Custom (parameters below)", "颞顶：椭圆 80 × 60，前后向": "Temporoparietal: ellipse 80 × 60, anterior-posterior",
    "额颞（翼点）：椭圆 80 × 60，斜 45°": "Frontotemporal (pterional): ellipse 80 × 60, oblique 45°", "顶部凸面：圆形半径 35": "Parietal convexity: circle radius 35",
    "额部：圆角矩形 70 × 60，前后向": "Frontal: rounded rectangle 70 × 60, anterior-posterior",
    "静脉安全距离 mm": "Vein safety distance mm", "SWI 上的表面大静脉：手术通道离它小于这个距离要扣分": "Large surface veins on SWI: a corridor closer than this is penalised",
    "近大静脉扣分权重": "Vein penalty weight", "入口 10 mm 内有大静脉或通道经过大静脉时扣的分；0 = 不用 SWI": "Penalty when a large vein lies within 10 mm of the entry or the corridor passes it; 0 = ignore SWI",
    "核心表面排除 mm": "Core surface exclusion mm", "距肿瘤核心小于该距离的皮层属于计划切除范围，不作为阵列放置位置": "Cortex this close to the core is resected anyway; arrays are not placed over it",
    "以肿瘤投影为中心（临床常规）": "Centred on the tumour projection (standard practice)",
    "⑨ 脑区图谱（阳性概率和任务建议）": "⑨ Brain atlas (positive-site priors and task suggestions)", "模板/图谱文件夹": "Template / atlas folder",
    "含 tpl-harvardoxford 的 space 文件夹（trajectoryGuide 的模板包）": "The space folder containing tpl-harvardoxford (trajectoryGuide template package)",
    "按脑区阳性概率给边界段加权": "Weight boundary segments by regional positive probability", "配准到标准脑并标注脑区": "Register to template and label regions",
    "还没有配准到标准脑": "Not registered to the template yet", "脑区": "Region", "重点测试建议": "Suggested mapping focus",
    "导出导航坐标": "Export navigation coordinates", "视图工具": "View tools", "十字光标": "Crosshair", "视图联动": "Link views",
    "重新居中": "Re-centre views", "3D 里显示切片": "Slices in 3D", "方位小人": "Orientation marker", "布局": "Layout",
    "只看 3D": "3D only", "3D + 三视图": "3D + three slices", "四宫格": "Four-up", "只看红色切片": "Red slice only",
    "通道视图": "Corridor view", "沿入口到肿瘤核心的手术通道切片，拖动滑条看每个深度离纤维束多远": "Slices along the surgical corridor from the entry to the tumour core; drag the slider to see how far the tracts are at each depth",
    "配准检查": "Check registration", "把 FA 叠在 T1c 上，拖滑条对比脑轮廓、脑室是否对齐": "Overlay FA on T1c; drag the slider to check that brain outline and ventricles line up",
    "配准通过": "Registration OK", "配准不通过": "Registration failed", "手术室成本参考": "OR cost reference", "按肿瘤体积自动设下沉量（侧向 = 下沉 × 0.4）": "Set sinking from tumour volume (lateral = sinking × 0.4)",
    "西班牙公立：阿斯图里亚斯价目表 2023（183.51 €/15 min）": "Spain public: Asturias tariff 2023 (183.51 €/15 min)",
    "默认值：西班牙公立医疗价目表（阿斯图里亚斯 2023），183.51 €/15 min": "Default: Spanish public tariff , 183.51 €/15 min",
    "默认值：清醒手术每例增加约 2,175 美元人员成本（时间驱动成本研究，2025），按清醒期约 130 min 折算": "Default: awake surgery adds about $2,175 staff cost per case (time-driven costing, 2025), spread over about 130 awake min", "刺激覆盖": "Stimulation coverage", "记录区覆盖": "Rec. area coverage",
}
