# INBRAIN Planner：3D Slicer scripted module（界面 + 自测）
# 下载的 UCSF-PDGM 病例文件夹 → 预处理（张量、配准、纤维束）→ 载入 → 调参数 → 规划 → 看结果、导出
# 代码结构：INBRAINPlannerLib/i18n.py 语言，config.py 参数和样式，logic.py 逻辑；规划核心在 Resources/Pipeline/slicer_placement_score.py
import os, re, io, json, shutil, contextlib, glob, sys, importlib
import qt, ctk, vtk, slicer
from slicer.ScriptedLoadableModule import ScriptedLoadableModule, ScriptedLoadableModuleWidget, ScriptedLoadableModuleLogic, ScriptedLoadableModuleTest

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path: sys.path.insert(0, HERE)
import INBRAINPlannerLib.i18n, INBRAINPlannerLib.config, INBRAINPlannerLib.logic
for _m in (INBRAINPlannerLib.i18n, INBRAINPlannerLib.config, INBRAINPlannerLib.logic):
    importlib.reload(_m)          # Reload / 切换语言时子模块也重新加载
from INBRAINPlannerLib.i18n import *
from INBRAINPlannerLib.config import *
from INBRAINPlannerLib.logic import INBRAINPlannerLogic
from INBRAINPlannerLib.deps import ensure_dependencies     # 缺 SlicerDMRI / SlicerElastix 时自动下载安装
REG_MIN_TRACTS = 20     # 自动配准判定：CST 和 AF 都至少这么多条才算正常


class INBRAINPlanner(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "INBRAIN Planner"
        parent.categories = ["INBRAIN"]
        qt.QTimer.singleShot(3000, ensure_dependencies)     # 缺依赖扩展时后台下载安装（需联网，装完重启）
        parent.contributors = ["Zelong Gan"]
        parent.helpText = L("术前规划开颅位置和电极阵列放置：输入 MRI、肿瘤分割、弥散数据和器件参数，"
                            "输出最少放置次数的计划和清醒期用时估计。所有阈值和器件参数都可调。",
                            "Preoperative planning of craniotomy site and electrode-array placement: input MRI, tumour segmentation, "
                            "diffusion data and device parameters; output a plan with the fewest placements and an awake-time estimate. "
                            "All thresholds and device parameters are adjustable.")
        parent.acknowledgementText = L("基于 3D Slicer、SlicerDMRI、SlicerElastix。仅供术前规划参考，不能替代术中电生理监测与临床判断。",
                                       "Built on 3D Slicer, SlicerDMRI and SlicerElastix. For pre-operative planning support only; does not replace intra-operative neurophysiological monitoring or clinical judgement.")


class INBRAINPlannerWidget(ScriptedLoadableModuleWidget):

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        ensure_dependencies()                               # 打开模块时再检查一次（每个会话只提示一次）
        self.logic = INBRAINPlannerLogic(); self.w = {}; self.device_json = None; self.G = None
        self.proc = None; self.queue = []
        L = self.layout
        try:
            L.setContentsMargins(10, 8, 10, 10); L.setSpacing(8)
        except Exception: pass
        top = qt.QFrame(); top.setObjectName("topBar")
        hb = qt.QHBoxLayout(top); hb.setContentsMargins(2, 0, 2, 5); hb.setSpacing(8)
        lab = qt.QLabel(T("界面语言")); lab.setObjectName("muted"); hb.addWidget(lab)
        self.langBox = qt.QComboBox(); self.langBox.addItems([T("跟随 Slicer"), "中文", "English"])
        self.langBox.setCurrentIndex(lang_choice()); self.langBox.connect("currentIndexChanged(int)", self.onLang)
        try: self.langBox.setMaximumWidth(160)
        except Exception: pass
        hb.addStretch(1); hb.addWidget(self.langBox)
        L.addWidget(top)

        # ---- 快速开始：一键规划、一键导出 ----
        box, f = self.section(INBRAINPlannerLib.i18n.L("快速开始", "Quick start"), True); self.quickBox = box
        self.quickDir = ctk.ctkPathLineEdit(); self.quickDir.filters = ctk.ctkPathLineEdit.Dirs
        self.quickDir.setToolTip(INBRAINPlannerLib.i18n.L("选病例文件夹，例如 …/UCSF-PDGM-0007_nifti", "Choose the case folder, e.g. …/UCSF-PDGM-0007_nifti"))
        f.addRow(INBRAINPlannerLib.i18n.L("病例文件夹", "Case folder"), self.quickDir)
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        self.btnAuto = qt.QPushButton(INBRAINPlannerLib.i18n.L("一键规划", "Plan in one click")); self.btnAuto.setObjectName("primary")
        self.btnAuto.setToolTip(INBRAINPlannerLib.i18n.L("自动完成：预处理（没做过才做，约 10–20 分钟）→ 载入 → 生成方案", "Runs preprocessing if needed (about 10–20 min) → load → plan"))
        self.btnAuto.connect("clicked()", self.onAuto); hb.addWidget(self.btnAuto, 2)
        self.btnExportAll = qt.QPushButton(INBRAINPlannerLib.i18n.L("一键导出", "Export all"))
        self.btnExportAll.setToolTip(INBRAINPlannerLib.i18n.L("报告（PDF/HTML/MD，含导航坐标）+ 网页版 3D（浏览器打开，可开关图层、旋转缩放）+ 图像合并图 + 数据合并图，存到结果文件夹", "Report (PDF/HTML/MD with navigation coordinates) + web 3D (open in a browser; toggle layers, rotate, zoom) + combined views + combined data, saved to the result folder"))
        self.btnExportAll.connect("clicked()", self.onExportAll); hb.addWidget(self.btnExportAll, 1); self._quickRow = hb
        f.addRow(hb)
        self.quickStatus = qt.QLabel(""); self.quickStatus.wordWrap = True; self.quickStatus.setObjectName("muted"); self.quickStatus.visible = False; f.addRow(self.quickStatus)
        self._quickForm = f
        self.quickReg = qt.QWidget(); hr = qt.QHBoxLayout(self.quickReg); hr.setContentsMargins(0, 0, 0, 0); hr.setSpacing(6)
        lab = qt.QLabel(INBRAINPlannerLib.i18n.L("纤维束偏少，请看一眼配准：", "Few tracts, please check the registration:")); lab.wordWrap = True; hr.addWidget(lab, 2)
        for txt, fn in [(INBRAINPlannerLib.i18n.L("看配准图", "Show overlay"), self.onRegQC),
                        (INBRAINPlannerLib.i18n.L("✓ 对齐", "✓ Aligned"), lambda: self.onRegVerdict(True)),
                        (INBRAINPlannerLib.i18n.L("✗ 错位", "✗ Misaligned"), lambda: self.onRegVerdict(False))]:
            b = qt.QPushButton(txt); b.connect("clicked()", fn); hr.addWidget(b, 1)
        self.quickReg.setToolTip(INBRAINPlannerLib.i18n.L("配准 = 把弥散图（算纤维束用）和 T1c 结构图对齐。看图时彩色 FA 的脑轮廓、脑室应和灰色 T1c 重合；错位几毫米以上纤维束和方案都不可靠",
                                                          "Registration aligns the diffusion map (used for tracts) with the T1c anatomy. In the overlay the FA brain outline and ventricles should sit on the grey T1c; a shift of several mm makes tracts and plan unreliable"))
        self.quickReg.visible = False; f.addRow(self.quickReg)

        # ---- 1 数据 ----
        box, f = self.section(T("① 数据（下载的病例文件夹）"), True); self._f1 = f
        self.caseDir = ctk.ctkPathLineEdit(); self.caseDir.filters = ctk.ctkPathLineEdit.Dirs
        self.caseDir.setToolTip(T("例如 …/UCSF-PDGM-0007_nifti，里面要有 DTI_eddy_noreg、bvec、T1c、分割文件"))
        self.caseDir.connect("currentPathChanged(QString)", self.onCaseDir)
        f.addRow(T("病例文件夹"), self.caseDir)
        self.caseName = qt.QLineEdit(); f.addRow(T("病例编号"), self.caseName)
        self.outDir = ctk.ctkPathLineEdit(); self.outDir.filters = ctk.ctkPathLineEdit.Dirs; self._out_auto = True
        self.outDir.setToolTip(T("结果放在这里的“病例文件夹名_Slicer”子文件夹里；默认是病例文件夹所在的目录"))
        self.outDir.connect("currentPathChanged(QString)", self.onOutDir)
        f.addRow(T("输出位置"), self.outDir)
        self.outLabel = qt.QLabel(""); self.outLabel.wordWrap = True; f.addRow("", self.outLabel)
        self.side = qt.QComboBox(); self.side.addItems([T(x) for x in ["自动判断", "R 右侧", "L 左侧"]]); f.addRow(T("肿瘤侧别"), self.side)
        self.flip = qt.QComboBox(); self.flip.addItems([T(x) for x in ["自动检测", "z", "y", "x", "none"]]); self.flip.setToolTip(T("梯度表翻转；自动检测约多 10 分钟"))
        f.addRow(T("梯度翻转"), self.flip)
        self.add_params(f, P_TRACT)
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        self.btnPre = qt.QPushButton(T("预处理")); self.btnPre.setObjectName("accent")
        self.btnPre.setToolTip(T("张量 → 配准 → 纤维束（后台 Slicer 运行，不弹窗口）"))
        self.btnPre.connect("clicked()", self.onPreprocess); hb.addWidget(self.btnPre, 2)
        self.btnCancel = qt.QPushButton(T("取消")); self.btnCancel.setObjectName("danger")
        self.btnCancel.enabled = False; self.btnCancel.connect("clicked()", self.onCancelPre); hb.addWidget(self.btnCancel, 1)
        self.btnLoad = qt.QPushButton(T("载入场景")); self.btnLoad.connect("clicked()", self.onLoad); hb.addWidget(self.btnLoad, 1)
        f.addRow(hb)
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        b = qt.QPushButton(T("配准检查")); b.setToolTip(T("把 FA 叠在 T1c 上，拖滑条对比脑轮廓、脑室是否对齐")); b.connect("clicked()", self.onRegQC)
        try: b.setMaximumWidth(110)
        except Exception: pass
        hb.addWidget(b)
        self.regOp = ctk.ctkSliderWidget(); self.regOp.minimum = 0; self.regOp.maximum = 100; self.regOp.decimals = 0; self.regOp.value = 50; self.regOp.suffix = " %"
        try: self.regOp.setMinimumWidth(110)
        except Exception: pass
        self.regOp.enabled = False; self.regOp.connect("valueChanged(double)", lambda v: slicer.util.setSliceViewerLayers(foregroundOpacity=v/100.0)); hb.addWidget(self.regOp, 1)
        f.addRow(hb)
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        for txt, ok in [("配准通过", True), ("配准不通过", False)]:
            b = qt.QPushButton(T(txt)); b.connect("clicked()", lambda ok=ok: self.onRegVerdict(ok)); hb.addWidget(b, 1)
        f.addRow(hb)
        self.progress = qt.QProgressBar(); self.progress.setRange(0, 1000); self.progress.value = 0
        self.progress.setFormat("%p%"); self.progress.visible = False
        self.progLabel = qt.QLabel(""); self.progLabel.visible = False
        pw = qt.QWidget(); v = qt.QVBoxLayout(pw); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
        v.addWidget(self.progress); v.addWidget(self.progLabel); f.addRow(pw)
        self.clock = qt.QTimer(); self.clock.setInterval(1000); self.clock.connect("timeout()", self.update_progress)
        self.loadBar, self.loadLab = self.make_progress(f)

        # ---- 2 器件 ----
        box, f = self.section(T("② 器件参数"), True)
        self.preset = qt.QComboBox(); self.preset.addItems([T(x) for x in list(PRESETS) + ["自定义（导入 JSON）"]])
        self.preset.connect("currentIndexChanged(int)", self.onPreset); f.addRow(T("预设"), self.preset)
        self.small = qt.QCheckBox(T("大触点之间有只记录的小触点")); self.small.checked = True; f.addRow(self.small)
        self.small_layout = "cells"
        self.stimModel = qt.QCheckBox(T("刺激范围按电流算")); self.stimModel.checked = True
        self.stimModel.setToolTip(T("激活半径 r = √(I/k) + 触点半径；语言段按 Penfield 双极，运动段按 Taniguchi 单极。不勾 = 固定 3 mm 判定容差")); f.addRow(self.stimModel)
        self.add_params(f, P_DEVICE)
        hb = qt.QHBoxLayout()
        b = qt.QPushButton(T("导入器件 JSON")); b.connect("clicked()", self.onImportDevice); hb.addWidget(b); self.devJsonBtns = [b]
        b = qt.QPushButton(T("导出器件 JSON")); b.connect("clicked()", self.onExportDevice); hb.addWidget(b); self.devJsonBtns.append(b)
        f.addRow(hb)
        self.devInfo = qt.QLabel(""); self.devInfo.wordWrap = True; f.addRow(self.devInfo)

        # ---- 3 目标点 ----
        box, f = self.section(T("③ 参考目标区（刺激区 / 记录区）"), False); self.targetBox = box
        n3 = qt.QLabel(T("这两类区域只用来给开颅入口打分、在 3D 里作参考；阵列放在哪由切除边界段决定")); n3.wordWrap = True; f.addRow(n3)
        self.add_params(f, P_TARGET)

        # ---- 4 开颅 ----
        box, f = self.section(T("④ 开颅位置和骨窗"), False)
        self.entryMode = qt.QComboBox(); self.entryMode.addItems([T(x) for x in ["自动：可开颅区域里评分最高", "离肿瘤核心最近的皮层点", "手动：用我放的 Entry 点", "以肿瘤投影为中心（临床常规）"]])
        f.addRow(T("入口点"), self.entryMode)
        b = qt.QPushButton(T("在 3D 里放 Entry 点")); b.connect("clicked()", self.onPlaceEntry); f.addRow(b)
        self.winPreset = qt.QComboBox(); self.winPreset.addItems([T(x[0]) for x in WIN_PRESETS]); f.addRow(T("骨窗预设"), self.winPreset)
        self.winPreset.connect("activated(int)", self.onWinPreset)
        self.winShape = qt.QComboBox(); self.winShape.addItems([T(x) for x in ["圆形", "椭圆", "圆角矩形"]]); f.addRow(T("骨窗形状"), self.winShape)
        self.winShape.connect("currentIndexChanged(int)", self.onWinShape)
        self.add_params(f, P_CRANIO); self.winShape.setCurrentIndex(1); self.onWinShape(1)   # 默认卵圆骨窗，长轴对齐肿瘤投影（先评分再定骨窗时自动转）
        self.skullSrc = qt.QComboBox(); self.skullSrc.addItems([T(x) for x in ["自动（有颅骨影像时使用，否则模拟）", "用颅骨文件（CT 或颅骨分割）", "从 MRI 提取（没去颅骨的影像）", "模拟颅骨"]])
        f.addRow(T("颅骨来源"), self.skullSrc)
        self.skullFile = ctk.ctkPathLineEdit(); self.skullFile.filters = ctk.ctkPathLineEdit.Files
        self.skullFile.setToolTip(T("可选：CT（自动按 HU 阈值取骨）或颅骨分割 NIfTI；要和病例 MRI 在同一坐标系"))
        f.addRow(T("颅骨文件"), self.skullFile)
        self.add_params(f, P_SKULL)
        self.autoSkull = qt.QCheckBox(T("生成方案后自动生成颅骨并开出骨窗")); self.autoSkull.checked = True; f.addRow(self.autoSkull)
        self.winFit = qt.QCheckBox(T("先评分再定骨窗（按选定放置调整骨窗位置和大小）")); self.winFit.checked = True
        self.winFit.setToolTip(T("上面的骨窗尺寸当作最大可开范围：先在里面选放置，再找能放下这些阵列和肿瘤投影的最小骨窗，重跑一遍；判定段不减少、放置次数不增加才采用")); f.addRow(self.winFit)
        self.nceTarget = qt.QCheckBox(INBRAINPlannerLib.i18n.L("FLAIR 残留未达标（> 5 cm³）时自动扩大骨窗", "Enlarge the window when the FLAIR residual is above 5 cm³")); self.nceTarget.checked = True
        self.nceTarget.setToolTip(INBRAINPlannerLib.i18n.L("入口不动，每次半径加 5 mm 重新规划；残留降到 5 cm³ 以下、或再扩一步减少不到“扩窗最小收益”、或到“扩窗上限半径”就停", "Same entry, radius +5 mm per step; stops below 5 cm³, when a step gains less than the minimum gain, or at the radius limit"))
        f.addRow(self.nceTarget)
        self.autoShape = qt.QCheckBox(INBRAINPlannerLib.i18n.L("按肿瘤投影自动选骨窗形状和角度（非圆形时）", "Choose window shape and angle from the tumour projection (non-round)")); self.autoShape.checked = True
        self.autoShape.setToolTip(INBRAINPlannerLib.i18n.L("长轴对齐肿瘤投影的主方向，长宽比按投影；投影接近矩形用圆角矩形，否则卵圆；可分离段不减少才采用", "Long axis along the tumour projection, aspect from the projection; rounded rectangle when the projection fills its box, otherwise oval; kept only if separable segments do not drop"))
        f.addRow(self.autoShape)
        b = qt.QPushButton(T("生成颅骨")); b.connect("clicked()", self.onSkull); f.addRow(b); self.skullBtn = b
        self.skullBar, self.skullLab = self.make_progress(f)

        # ---- 5 优化 ----
        box, f = self.section(T("⑤ 优化目标和打分权重"), False)
        self.add_params(f, P_OPT)
        self.bndFlair = qt.QCheckBox(T("边界改用 FLAIR 外缘（扩大切除）")); self.bndFlair.checked = False; f.addRow(self.bndFlair)
        self.reqHealthy = qt.QCheckBox(T("要有健康参照触点")); self.reqHealthy.checked = True
        self.reqHealthy.setToolTip(T("离 FLAIR 边界 > 30 mm 的触点当病人内对照，比较病灶、瘤周和健康皮层的 ECoG（Díaz-Fernández 2025）")); f.addRow(self.reqHealthy)
        self.fmriPath = ctk.ctkPathLineEdit(); self.fmriPath.filters = ctk.ctkPathLineEdit.Files
        self.fmriPath.setToolTip(T("可选：术前任务 fMRI 的 z 值图（NIfTI，与 T1c 同一空间），用于给边界段风险加权")); f.addRow(T("术前 fMRI（可选）"), self.fmriPath)
        self.ntmsPath = ctk.ctkPathLineEdit(); self.ntmsPath.filters = ctk.ctkPathLineEdit.Files
        self.ntmsPath.setToolTip(INBRAINPlannerLib.i18n.L("可选：术前 nTMS 阳性点（.fcsv / .mrk.json，或 CSV：x, y, z, 标签；RAS，与 T1c 同一空间）。标签含 lang 或“语言”的算语言点，其余算运动点", "Optional: preoperative nTMS positive points (.fcsv / .mrk.json, or CSV x, y, z, label; RAS, same space as T1c). Labels containing 'lang' count as language points, the rest as motor"))
        f.addRow(INBRAINPlannerLib.i18n.L("术前 nTMS（可选）", "Preoperative nTMS (optional)"), self.ntmsPath)

        # ---- 6 时间 ----
        box, f = self.section(T("⑥ 术中时间参数"), False); self.__dict__.setdefault("advBoxes", []).append(box)
        self.add_params(f, P_TIME)
        self.asleepFirst = qt.QCheckBox(T("第一片阵列麻醉期放好")); self.asleepFirst.checked = True; f.addRow(self.asleepFirst)
        self.passiveAsleep = qt.QCheckBox(T("被动定位放在麻醉期（全麻下听觉任务高 γ）")); self.passiveAsleep.checked = True
        self.passiveAsleep.setToolTip(T("麻醉期对每次放置做 CCEP 和被动任务记录；清醒期只对含可疑触点的放置进行刺激确认")); f.addRow(self.passiveAsleep)
        self.motorAwake = qt.QCheckBox(T("运动定位放在清醒期（否 = 麻醉下 MEP）")); f.addRow(self.motorAwake)
        self.adStrip = qt.QCheckBox(T("传统流程加一条后放电监测条带")); self.adStrip.checked = True
        self.adStrip.setToolTip(T("探针刺激时需在旁放置一条 ECoG 条带监测后放电（参考资料）：增加一条条带的器件费；麻醉期放置一次，清醒期每更换刺激区域重新放置一次。INBRAIN 阵列由刺激触点周围的记录触点监测")); f.addRow(self.adStrip)

        # ---- 7 成本 ----
        box, f = self.section(T("⑦ 成本参数"), False); self.__dict__.setdefault("advBoxes", []).append(box)
        self.add_params(f, P_COST)
        for k in P_COST: self.w[k[0]].connect("valueChanged(double)", lambda *a: self.show_cost())

        # ---- 8 脑移位 ----
        box, f = self.section(T("⑧ 脑移位分析"), False); self.__dict__.setdefault("advBoxes", []).append(box)
        self.autoShift = qt.QCheckBox(T("按肿瘤体积自动设下沉量（侧向 = 下沉 × 0.4）")); self.autoShift.checked = True; f.addRow(self.autoShift)
        self.add_params(f, P_SHIFT)
        b = qt.QPushButton(T("运行脑移位分析")); b.connect("clicked()", self.onShift); f.addRow(b)
        self.shiftTable = qt.QTableWidget(); self.shiftTable.setMinimumHeight(150); f.addRow(self.shiftTable)
        self.shiftNote = qt.QLabel(T("尚未分析")); self.shiftNote.wordWrap = True; f.addRow(self.shiftNote)
        self.shift_rows = None

        # ---- 9 脑区图谱 ----
        box, f = self.section(T("⑨ 脑区图谱（阳性概率和任务建议）"), False); self.__dict__.setdefault("advBoxes", []).append(box)
        self.atlasDir = ctk.ctkPathLineEdit(); self.atlasDir.filters = ctk.ctkPathLineEdit.Dirs
        self.atlasDir.setToolTip(T("含 tpl-harvardoxford 的 space 文件夹（trajectoryGuide 的模板包）"))
        ad = str(qt.QSettings().value(ATLAS_KEY, "") or "")
        if not ad or not os.path.isdir(ad):
            ad = ""
            for c in [os.path.join(HERE, "Resources", "ExtLibs", "space"), os.path.expanduser("~/Downloads/space")]:
                if os.path.isdir(c): ad = os.path.normpath(c); break
        self.atlasDir.currentPath = ad; f.addRow(T("模板/图谱文件夹"), self.atlasDir)
        self.usePrior = qt.QCheckBox(T("按脑区阳性概率给边界段加权")); self.usePrior.checked = True; f.addRow(self.usePrior)
        b = qt.QPushButton(T("配准到标准脑并标注脑区")); b.connect("clicked()", self.onAtlas); f.addRow(b)
        self.atlasBar, self.atlasLab = self.make_progress(f)
        self.atlasNote = qt.QLabel(T("还没有配准到标准脑")); self.atlasNote.wordWrap = True; f.addRow(self.atlasNote)

        # ---- 运行 ----
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        self.btnRun = qt.QPushButton(T("生成方案")); self.btnRun.setObjectName("primary")
        self.btnRun.connect("clicked()", self.onRun); hb.addWidget(self.btnRun, 2)
        b = qt.QPushButton(T("保存参数")); b.connect("clicked()", self.onSaveParams); hb.addWidget(b, 1)
        b = qt.QPushButton(T("读取参数")); b.connect("clicked()", self.onLoadParams); hb.addWidget(b, 1)
        self.runRow = qt.QWidget(); self.runRow.setLayout(hb); hb.setContentsMargins(0, 0, 0, 0); L.addWidget(self.runRow)
        fr = qt.QFormLayout(); L.addLayout(fr); self.runBar, self.runLab = self.make_progress(fr)

        # ---- 显示样式 ----
        box, f = self.section(T("显示样式（颜色、透明度）"), False)
        self.styleBox = box
        self.style_w = {}
        for key, zh, en, kind, match, col, op in STYLES:
            dcol, dop, dvis = self.default_style(key, col, op)
            st = self.saved_style(key, dcol, dop)
            row = qt.QHBoxLayout()
            vis = qt.QCheckBox(); vis.checked = dvis; vis.setToolTip(T("显示/隐藏"))
            cb = ctk.ctkColorPickerButton(); cb.displayColorName = False
            cb.color = qt.QColor.fromRgbF(*st[0]); cb.setFixedSize(26, 20)     # 只露一个小色块，不留大空框
            try: cb.setIconSize(qt.QSize(16, 12)); cb.setStyleSheet("padding:0px; margin:0px;")
            except Exception: pass
            sl = ctk.ctkSliderWidget(); sl.minimum = 0; sl.maximum = 100; sl.singleStep = 5; sl.decimals = 0; sl.value = round(st[1]*100); sl.suffix = " %"
            if kind == "multi":
                sp_ = cb.sizePolicy; sp_.setRetainSizeWhenHidden(True); cb.setSizePolicy(sp_); cb.visible = False       # 多色图层（如边界分段）只调显示和透明度，颜色由含义决定
            row.setContentsMargins(0, 0, 0, 0); row.setSpacing(6)
            row.addWidget(vis); row.addWidget(cb); row.addWidget(sl, 1)
            full = zh if lang() == "zh" else en
            lab = qt.QLabel(full.split("（")[0].split(" (")[0].strip()); lab.setToolTip(full)   # 只显示短名，括号里的说明放悬停
            sl.setMinimumWidth(90)
            f.addRow(lab, row); self.style_w[key] = (vis, cb, sl)
            for sig, obj in [("toggled(bool)", vis), ("colorChanged(QColor)", cb), ("valueChanged(double)", sl)]:
                obj.connect(sig, lambda *a, k=key: self.apply_style(k, save=True))
        hb = qt.QHBoxLayout()
        b = qt.QPushButton(T("设为默认样式")); b.setToolTip(T("把现在的颜色、透明度、显示设置存成默认")); b.connect("clicked()", self.onSetDefaultStyle); hb.addWidget(b)
        b = qt.QPushButton(T("加载默认样式")); b.setToolTip(T("恢复为“设为默认”保存的样式；未保存时使用出厂样式")); b.connect("clicked()", self.onResetStyle); hb.addWidget(b)
        f.addRow(hb)
        b = qt.QPushButton(T("恢复出厂样式")); b.connect("clicked()", lambda: self.onResetStyle(factory=True)); f.addRow(b)

        # ---- 视图工具（参考 trajectoryGuide 的 settingsPanel） ----
        box, f = self.section(T("视图工具"), False)
        hb = qt.QGridLayout(); self.viewChecks = {}      # 两行三列，窄面板也放得下
        for i_, (key, txt) in enumerate([("cross", "十字光标"), ("link", "视图联动"), ("inter", "3D 里显示切片"), ("marker", "方位小人"), ("labels", "方位字母和外框")]):
            cb = qt.QCheckBox(T(txt)); cb.connect("toggled(bool)", lambda on, k=key: self.onViewToggle(k, on)); hb.addWidget(cb, i_ // 3, i_ % 3); self.viewChecks[key] = cb
        f.addRow(hb)
        # Slicer 的 S/I/A/P/R/L 字母贴在整个场景的包围盒上，外框一隐藏、相机拉近，字母就飘在脑子上和外框错位；
        # 默认改用角上的方位小人（永远和视角一致），字母和外框只能一起开
        self.viewChecks["labels"].setToolTip(T("S/I/A/P/R/L 字母贴在场景包围盒的面上，只有和外框一起看才不错位"))
        self.viewChecks["marker"].checked = True
        hb = qt.QHBoxLayout()
        b = qt.QPushButton(T("重新居中")); b.connect("clicked()", self.onRecenter); hb.addWidget(b)
        hb.addWidget(qt.QLabel(T("布局")))
        self.layoutBox = qt.QComboBox(); self.layoutBox.addItems([T(x) for x in ["只看 3D", "3D + 三视图", "四宫格", "只看红色切片"]])
        self.layoutBox.connect("activated(int)", self.onLayout); hb.addWidget(self.layoutBox, 1)
        f.addRow(hb)

        # ---- 结果 ----
        box, f = self.section(T("结果"), True); self.resultBox = box
        self.value = qt.QLabel(""); self.value.wordWrap = True; self.value.visible = False
        self.value.setObjectName("valueCard"); self.value.setTextFormat(qt.Qt.RichText)
        try: self.value.setAlignment(qt.Qt.AlignLeft | qt.Qt.AlignTop)
        except Exception: pass
        f.addRow(self.value)
        self.summary = qt.QLabel(T("尚未生成方案")); self.summary.wordWrap = True; self.summary.setObjectName("muted"); f.addRow(self.summary)
        self.winNote = qt.QLabel(""); self.winNote.wordWrap = True; f.addRow(self.winNote)
        self.checkNote = qt.QLabel(""); self.checkNote.wordWrap = True; self.checkNote.visible = False; f.addRow(self.checkNote)
        self.planTable = qt.QTableWidget(); self.planTable.setColumnCount(11)
        self.planTable.setHorizontalHeaderLabels([T(x) for x in ["次序", "阶段", "角度", "判定段", "触点分区", "记录区覆盖", "贴合 mm", "形变", "近静脉", "纤维束", "脑区"]])
        self.planTable.setSelectionBehavior(qt.QAbstractItemView.SelectRows); self.planTable.setMinimumHeight(150)
        self.planTable.connect("itemSelectionChanged()", self.onPlanSelect); f.addRow(self.planTable)
        self.whyLabel = qt.QLabel(""); self.whyLabel.wordWrap = True; f.addRow(self.whyLabel)
        self.whyTable = qt.QTableWidget(); self.whyTable.setColumnCount(4)
        self.whyTable.setHorizontalHeaderLabels([T(x) for x in ["段", "纤维束", "现状", "下一步"]]); self.whyTable.setMinimumHeight(110)
        self.whyTable.setSelectionBehavior(qt.QAbstractItemView.SelectRows); self.whyTable.connect("itemSelectionChanged()", self.onWhySelect)
        self.whyTable.setToolTip(T("点一行，3D 视图转到这一段")); f.addRow(self.whyTable)
        self.timeTable = qt.QTableWidget(); self.timeTable.setColumnCount(5)
        self.timeTable.setHorizontalHeaderLabels([T(x) for x in ["方案", "清醒期 min", "麻醉期额外 min", "全部 min", "预计漏检位点"]])
        f.addRow(self.timeTable)
        self.costTable = qt.QTableWidget(); self.costTable.setColumnCount(4)
        self.costTable.setHorizontalHeaderLabels([T(x) for x in ["方案", "时间成本 €", "器件 €", "合计 €"]])
        f.addRow(self.costTable)
        self.costNote = qt.QLabel(""); self.costNote.wordWrap = True; f.addRow(self.costNote)
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        for txt, fn in [("◀ 上一片", lambda: self.onStep(-1)), ("下一片 ▶", lambda: self.onStep(1))]:
            b = qt.QPushButton(T(txt)); b.connect("clicked()", fn); hb.addWidget(b, 1)
        f.addRow(hb)
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        for txt, fn in [("显示全部放置", self.onShowAll), ("显示/隐藏入口评分", self.onToggleEntryMap)]:
            b = qt.QPushButton(T(txt)); b.connect("clicked()", fn); hb.addWidget(b, 1)
        f.addRow(hb)
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        for txt, fn in [("导出汇报图", self.onExportFigure), ("导出网页版 3D", self.onExportWeb), ("生成报告", self.onReport)]:
            b = qt.QPushButton(T(txt)); b.connect("clicked()", fn); hb.addWidget(b, 1)
        f.addRow(hb)
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        b = qt.QPushButton(INBRAINPlannerLib.i18n.L("合并图：图像", "Combined: views")); b.setToolTip(INBRAINPlannerLib.i18n.L("手术视角、斜视、全脑侧面、内部结构四个 3D 视角拼成一张图，带图例和关键数字", "Surgical, oblique, lateral and internal 3D views in one figure with legend and key numbers")); b.connect("clicked()", self.onExportComboViews); hb.addWidget(b, 1)
        b = qt.QPushButton(INBRAINPlannerLib.i18n.L("合并图：数据", "Combined: data")); b.setToolTip(INBRAINPlannerLib.i18n.L("边界段、放置与采样、时间、成本四个对比图拼成一张图（INBRAIN 对比传统流程）", "Boundary, placements and sampling, time and cost charts in one figure (INBRAIN vs conventional)")); b.connect("clicked()", self.onExportComboData); hb.addWidget(b, 1)
        f.addRow(hb)
        hb = qt.QHBoxLayout(); hb.setSpacing(6)
        for txt, fn in [("保存场景 .mrb", self.onSaveScene), ("打开结果文件夹", self.onOpenDir)]:
            b = qt.QPushButton(T(txt)); b.connect("clicked()", fn); hb.addWidget(b, 1)
        f.addRow(hb)
        hb = qt.QHBoxLayout()
        b = qt.QPushButton(T("导出导航坐标")); b.connect("clicked()", self.onExportNav); hb.addWidget(b)
        b = qt.QPushButton(T("通道视图")); b.setToolTip(T("沿入口到肿瘤核心的手术通道切片，拖动滑条看每个深度离纤维束多远")); b.connect("clicked()", self.onCorridor); hb.addWidget(b)
        self.corrSlider = ctk.ctkSliderWidget(); self.corrSlider.minimum = 0; self.corrSlider.maximum = 60; self.corrSlider.decimals = 0; self.corrSlider.suffix = " mm"
        try: self.corrSlider.setMinimumWidth(110)
        except Exception: pass
        self.corrSlider.enabled = False; self.corrSlider.connect("valueChanged(double)", self.onCorridorDepth); hb.addWidget(self.corrSlider, 1)
        f.addRow(hb)
        self.corrLabel = qt.QLabel(""); self.corrLabel.wordWrap = True; f.addRow(self.corrLabel)

        box, f = self.section(T("运行日志"), False)
        self.log = qt.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMinimumHeight(160); f.addRow(self.log)
        # ---- 精简：自动处理的控件不显示（功能保留，值用默认/自动） ----
        def _hide_row(form, wdg):
            wdg.hide(); lab = form.labelForField(wdg)
            if lab is not None: lab.hide()
        _hide_row(self._f1, self.caseName); _hide_row(self._f1, self.flip)
        _hide_row(self._f1, self.caseDir)          # 病例文件夹只在快速开始里选（两处同步）
        # 配准检查只留快速开始里那一行（需要时才出现）；叠图透明度滑条也挪过去
        for b in self._f1.parentWidget().findChildren(qt.QPushButton):
            if b.text in (T("配准检查"), T("配准通过"), T("配准不通过")): b.hide()
        self.quickReg.layout().addWidget(self.regOp, 1)
        for wdg in [self.btnPre, self.btnLoad, self.skullBtn, self.targetBox] + self.devJsonBtns: wdg.hide()
        try: self.w["SHIFT_SINK"].parentWidget().hide()     # 下沉量、侧向量按肿瘤体积自动设
        except Exception: pass
        self.btnRun.hide()
        # ---- 高级（研究用）：时间、成本、脑移位、图谱、保存/读取参数，默认折叠 ----
        self.advBox = ctk.ctkCollapsibleButton(); self.advBox.text = INBRAINPlannerLib.i18n.L("高级（研究用）", "Advanced (research)"); self.advBox.collapsed = True
        self.advBox.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Preferred)
        av = qt.QVBoxLayout(self.advBox); av.setContentsMargins(6, 2, 6, 4); av.setSpacing(6)
        note = qt.QLabel(INBRAINPlannerLib.i18n.L("这些参数已按文献和 20 例批量校准，只影响时间、成本估算或附加分析；改动前先保存参数。", "These parameters are calibrated to the literature and a 20-case batch; they only affect time and cost estimates or extra analyses. Save parameters before changing them."))
        note.wordWrap = True; note.setObjectName("muted"); av.addWidget(note)
        L.insertWidget(L.indexOf(self.runRow), self.advBox)
        for b in self.advBoxes: av.addWidget(b)
        av.addWidget(self.runRow)
        # 取消按钮放到快速开始（预处理时可以停）
        self._quickRow.addWidget(self.btnCancel, 1); self.btnCancel.visible = False   # 只在预处理时出现，和一键规划同一行
        # 进度条放到快速开始里，两种模式都看得到
        self._quickForm.addRow(self.progress); self._quickForm.addRow(self.progLabel)
        self.quickDir.connect("currentPathChanged(QString)", lambda p: self._sync_dirs(self.quickDir, self.caseDir))
        self.caseDir.connect("currentPathChanged(QString)", lambda p: self._sync_dirs(self.caseDir, self.quickDir))
        self.quickDir.currentPath = self.caseDir.currentPath
        self.onMode(1)   # 只有一种模式：全部分区可见，研究用参数在“高级”里折叠
        L.addStretch(1)
        for k, (zh, en) in WIDGET_TIPS.items():
            wdg = getattr(self, k, None)
            if wdg is not None and not wdg.toolTip: wdg.setToolTip(zh if lang() == "zh" else en)
        self.watch_width()
        self.apply_theme()
        self.onPreset(0)
        st = getattr(slicer, "_inbrain_stash", None)     # 切换语言后恢复刚才的参数
        if st:
            slicer._inbrain_stash = None
            self.caseDir.currentPath = st.get("_caseDir", ""); self.caseName.text = st.get("_case", ""); self.outDir.currentPath = st.get("_out", "") or self.outDir.currentPath
            self.apply_params(st)
            if st.get("_log"): self.log.setPlainText(st["_log"])

    def onLang(self, i):
        qt.QSettings().setValue(LANG_KEY, i)
        st = self.all_params(); st.update(_caseDir=self.caseDir.currentPath, _case=self.caseName.text, _out=self.outDir.currentPath, _log=self.log.toPlainText())
        slicer._inbrain_stash = st
        qt.QTimer.singleShot(0, lambda: slicer.util.reloadScriptedModule("INBRAINPlanner"))

    # ---------- 进入/离开模块：本插件里不显示“数据探针” ----------
    def enter(self):
        self.apply_theme()                 # 进入模块时按当前外观（浅色/深色）重新套一次
        self.restore_params_from_scene()
        try:    # 左侧模块栏第一次进入时缩窄四分之一；之后用户手动拖的宽度不再改
            mw = slicer.util.mainWindow(); dock = mw.findChild(qt.QDockWidget, "PanelDockWidget")
            if dock:
                dock.setMinimumWidth(200)          # 每次进入（含切换语言后）都放开最小宽度，方便拖窄
                self.unpin_width()
                if not getattr(slicer, "_inbrain_dock_done", False):
                    mw.resizeDocks([dock], [440], qt.Qt.Horizontal)      # 每次打开 Slicer 第一次进入时回到两栏紧凑的最窄宽度
                    slicer._inbrain_dock_done = True
        except Exception: pass
        qt.QTimer.singleShot(0, self.planner_layout)
        try:    # Slicer 自带的“帮助及致谢”折叠栏跟 Slicer 语言走；本模块里改成中英双语，离开时还原
            hb = slicer.util.findChild(slicer.util.mainWindow(), "HelpCollapsibleButton")
            if not hasattr(self, "_help_text"): self._help_text = hb.text
            hb.text = "帮助及致谢 / Help && Acknowledgement"
        except Exception: pass
        try:
            self._probe_was = slicer.util.findChild(slicer.util.mainWindow(), "DataProbeCollapsibleWidget").visible
            slicer.util.setDataProbeVisible(False)
        except Exception: self._probe_was = None

    def exit(self):
        try:
            if hasattr(self, "_help_text"):
                slicer.util.findChild(slicer.util.mainWindow(), "HelpCollapsibleButton").text = self._help_text
        except Exception: pass
        try:
            if getattr(self, "_probe_was", None): slicer.util.setDataProbeVisible(True)
        except Exception: pass

    # ---------- 界面工具 ----------
    def make_progress(self, form):
        bar = qt.QProgressBar(); bar.setRange(0, 1000); bar.value = 0; bar.setFormat("%p%"); bar.visible = False
        lab = qt.QLabel(""); lab.visible = False
        # 进度条和文字放进同一个零边距容器、只占一行：Qt5 表单里隐藏的行仍算行距，两行会留出空白
        box = qt.QWidget(); v = qt.QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
        v.addWidget(bar); v.addWidget(lab); form.addRow(box); return bar, lab

    def hide_later(self, bar, lab, ms=3000):
        """完成后过几秒把进度条和文字收起来；期间又开始新任务就不收"""
        def h():
            if bar.value >= 1000: bar.visible = False; lab.visible = False
        qt.QTimer.singleShot(ms, h)

    def set_progress(self, bar, lab, frac, text, t0=None):
        import time
        bar.visible = lab.visible = True; bar.value = int(1000*max(0.0, min(frac, 1.0)))
        txt = text.split("|")[0 if lang() == "zh" else -1]
        if t0 is not None:
            t = int(time.time() - t0); txt += L(f"  已用 {t//60}:{t%60:02d}", f"  elapsed {t//60}:{t%60:02d}")
        lab.text = txt; slicer.app.processEvents()

    # ---------- 简洁模式与一键流程 ----------
    def onMode(self, i):
        simple = False   # 简洁模式已取消，保留这个函数只用来统一设置各分区的显示
        for b in self.boxes:
            b.visible = (not simple) or b in (self.quickBox, self.resultBox, getattr(self, "styleBox", None))
            if b is getattr(self, "targetBox", None): b.visible = False   # 参考目标区只影响显示，不进评分，不再显示
        if hasattr(self, "advBox"): self.advBox.visible = not simple
        # 结果区：简洁模式只留要点卡、检查、逐片切换；明细表和单项导出按钮在专业模式里
        keep = {T("◀ 上一片"), T("下一片 ▶"), T("显示全部放置")}
        for t in self.resultBox.findChildren(qt.QTableWidget): t.visible = (not simple) and (t is not self.whyTable or self.whyTable.rowCount > 0)
        for b in self.resultBox.findChildren(qt.QPushButton): b.visible = (not simple) or b.text in keep
        for wdg in (getattr(self, "corrSlider", None), getattr(self, "corrLabel", None), getattr(self, "winNote", None)):
            if wdg is not None: wdg.visible = not simple

    def _sync_dirs(self, src, dst):
        if dst.currentPath != src.currentPath: dst.currentPath = src.currentPath

    def onAuto(self):
        if not os.path.isdir(self.caseDir.currentPath or ""):
            slicer.util.errorDisplay(INBRAINPlannerLib.i18n.L("先选病例文件夹", "Choose a case folder first")); return
        try:
            case, work, D = self.case_paths()
            have = all(os.path.exists(os.path.join(D, f"{case}_tract_{t}.vtk")) for t in ("CST", "AF"))
        except Exception: have = False
        if not have:
            self._auto = True; self.quickStatus.visible = True; self.quickStatus.text = INBRAINPlannerLib.i18n.L("预处理中，约 10–20 分钟", "Preprocessing, about 10–20 min")
            self.onPreprocess(); return
        self._auto_continue()

    def auto_reg_check(self):
        """配准自动判定：没有人工结论时，按纤维束条数判断（配准错位或梯度方向错时纤维束会很少或断掉）"""
        rs = self.reg_status()
        if rs and "自动" not in rs and "auto" not in rs: return rs                    # 人工结论优先
        nl = {n.GetName()[6:]: (n.GetPolyData().GetNumberOfLines() if n.GetPolyData() else 0) for n in slicer.util.getNodesByClass("vtkMRMLModelNode") if n.GetName().startswith("tract_")}
        cst, af = nl.get("CST", 0), nl.get("AF", 0); ok = cst >= REG_MIN_TRACTS and af >= REG_MIN_TRACTS
        try:
            case, work, D = self.case_paths()
            open(os.path.join(D, "registration_check.txt"), "w", encoding="utf-8").write(("pass" if ok else "fail") + INBRAINPlannerLib.i18n.L(f"（自动：纤维束 CST {cst}、AF {af}）", f" (auto: tracts CST {cst}, AF {af})"))
        except Exception as e: self.say("reg auto:", e)
        self.quickReg.visible = not ok
        return self.reg_status()

    def _auto_continue(self):
        self._auto = False
        self.quickStatus.visible = True; self.quickStatus.text = INBRAINPlannerLib.i18n.L("生成方案中…", "Planning…"); slicer.app.processEvents()
        try:
            self.onLoad(); self.auto_reg_check(); self.onRun()
        except Exception as e:
            self.quickStatus.visible = True; self.quickStatus.text = str(e); return
        if self.G is None:
            self.quickStatus.visible = True; self.quickStatus.text = INBRAINPlannerLib.i18n.L("没有生成方案，详情见运行日志", "No plan generated; see the log"); return
        B = self.G.get("BND") or {}
        self.quickStatus.visible = True; self.quickStatus.text = INBRAINPlannerLib.i18n.L(f"完成：放置 {len(self.G['PLAN'])} 次，可分离 {B.get('sep', 0)} / {B.get('n_req', 0)} 段", f"Done: {len(self.G['PLAN'])} placements, {B.get('sep', 0)} / {B.get('n_req', 0)} segments separable")

    def onExportAll(self):
        if self.G is None: slicer.util.errorDisplay(INBRAINPlannerLib.i18n.L("先生成方案", "Generate a plan first")); return
        out = []
        for fn in (self.onReport, self.onExportWeb, self.onExportComboViews, self.onExportComboData):   # 报告、网页版 3D（可开关图层）、两张合并图
            try:
                r = fn()
                if r: out.append(os.path.basename(r))
            except Exception as e: self.say("export:", e)
        self.quickStatus.visible = True; self.quickStatus.text = INBRAINPlannerLib.i18n.L("已导出：", "Exported: ") + "、".join(out) + ""
        try: self.onOpenDir()
        except Exception: pass

    def section(self, title, expanded):
        box = ctk.ctkCollapsibleButton(); box.text = title; box.collapsed = not expanded
        box.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Preferred)   # 最小宽度按内容真正的最小值，不按长文字的理想宽度撑开
        self.__dict__.setdefault("boxes", []).append(box)
        # 表单放进内层 QWidget：折叠时整块隐藏，分节不会因为隐藏表单的最小高度留出空白
        outer = qt.QVBoxLayout(box); outer.setContentsMargins(0, 0, 0, 0)
        inner = qt.QWidget(); inner.setObjectName("sectionBody"); outer.addWidget(inner)
        f = qt.QFormLayout(inner)
        try:
            f.setContentsMargins(10, 4, 10, 6); f.setHorizontalSpacing(12); f.setVerticalSpacing(4)
            f.setLabelAlignment(qt.Qt.AlignLeft | qt.Qt.AlignVCenter)
            f.setFieldGrowthPolicy(qt.QFormLayout.AllNonFixedFieldsGrow)
        except Exception: pass
        self.layout.addWidget(box)
        return box, f

    def add_params(self, form, spec):
        """两栏排：长标签放左、短标签放右；数字框最小，窄面板也放得下；超长标签换行不撑宽"""
        fm = qt.QLabel("").fontMetrics()
        def spin(item):
            key, lab, dv, lo, hi, st, dec, tip = item
            sb = qt.QDoubleSpinBox(); sb.setRange(lo, hi); sb.setSingleStep(st); sb.setDecimals(dec); sb.value = dv
            try: sb.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
            except Exception: pass
            try: sb.setFixedWidth(72)
            except Exception: pass
            tt = self.param_tip(key, tip)
            if tt: sb.setToolTip(tt)
            self.w[key] = sb
            return sb
        items = sorted(spec, key=lambda it: -fm.width(T(it[1])))
        half = (len(items) + 1) // 2
        left, right = items[:half], items[half:]
        # 参数区用一个网格：面板宽时两栏（长左短右），窄时自动排成单栏（见 relayout_params）
        box = qt.QWidget(); g = qt.QGridLayout(box)
        g.setContentsMargins(0, 0, 0, 0); g.setHorizontalSpacing(6); g.setVerticalSpacing(4)
        cells = [(qt.QLabel(T(it[1])), spin(it)) for it in left + right]
        for lab_, sb_ in cells:
            lab_.setToolTip(sb_.toolTip)        # 标签上也能看到说明
            lab_.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Preferred)   # 标签不换行，两栏紧凑排
        form.addRow(box)
        self.__dict__.setdefault("_grids", []).append((g, cells, half))
        self.place_grid(g, cells, half, two=True)

    @staticmethod
    def param_tip(key, tip=""):
        """参数说明：优先用 PARAM_TIPS（中英文），没有就用参数表里的提示"""
        if key in PARAM_TIPS: return PARAM_TIPS[key][0 if lang() == "zh" else 1]
        return T(tip) if tip else ""

    def unpin_width(self):
        """Slicer 载入模块时把滚动区内容的最小宽度钉成模块的理想宽度（长文字一多就很宽），改回真正需要的最小宽度"""
        try:
            self.parent.setSizePolicy(qt.QSizePolicy.Preferred, self.parent.sizePolicy.verticalPolicy())   # Slicer 默认 Minimum：理想宽度变成硬下限
            x = self.parent.parentWidget()
            while x is not None and x.objectName != "scrollAreaWidgetContents": x = x.parentWidget()
            if x is not None: x.setMinimumWidth(min(x.minimumWidth, self.parent.minimumSizeHint.width()))
        except Exception: pass

    def place_grid(self, g, cells, half, two):
        for lab, sb in cells: g.removeWidget(lab); g.removeWidget(sb)
        for c in range(5): g.setColumnStretch(c, 0); g.setColumnMinimumWidth(c, 0)
        for k, (lab, sb) in enumerate(cells):
            if two:
                r, c = (k, 0) if k < half else (k - half, 2)
            else:
                r, c = k, 0
            lab.setAlignment((qt.Qt.AlignRight if (two and c == 2) else qt.Qt.AlignLeft) | qt.Qt.AlignVCenter)
            lab.setContentsMargins(12 if (two and c == 2) else 0, 0, 0, 0)
            g.addWidget(lab, r, c); g.addWidget(sb, r, c + 1)
        # 多出来的宽度给标签列（标签可换行），数字框列保持固定宽
        if two: g.setColumnStretch(0, 1); g.setColumnStretch(2, 1)
        else: g.setColumnStretch(0, 1)

    def relayout_params(self, width):
        """面板宽度低于阈值时参数排单栏，高于时恢复两栏"""
        two = True   # 参数一直两栏紧凑排
        if getattr(self, "_two_col", None) == two: return
        self._two_col = two
        for g, cells, half in getattr(self, "_grids", []):
            self.place_grid(g, cells, half, two)
        qt.QTimer.singleShot(0, self.unpin_width)

    def watch_width(self):
        class _F(qt.QObject):
            def __init__(s, cb): qt.QObject.__init__(s); s.cb = cb
            def eventFilter(s, obj, ev):
                try:
                    if ev.type() == qt.QEvent.Resize: s.cb(obj.width)
                except Exception: pass
                return False
        self._wfilter = _F(self.relayout_params)
        self.parent.installEventFilter(self._wfilter)
        self.relayout_params(self.parent.width)
        for cb in self.parent.findChildren(qt.QComboBox):      # 下拉框按 14 个字宽排，长名字省略显示，悬停看全名
            try:
                cb.setSizeAdjustPolicy(qt.QComboBox.AdjustToMinimumContentsLengthWithIcon); cb.setMinimumContentsLength(14)
                cb.setToolTip(cb.toolTip or ""); cb.connect("currentIndexChanged(int)", lambda i, c=cb: c.setToolTip(c.currentText))
                cb.setToolTip(cb.currentText)
            except Exception: pass

    # ---------- 外观：主题、表格、卡片（只影响观感） ----------
    def apply_theme(self):
        """统一配色、字体和间距；不改变任何参数、计算或回调"""
        try:
            self.setStyleSheet(themed(THEME))
        except Exception:
            try: self.parent.setStyleSheet(themed(THEME))
            except Exception: pass
        for t, h in [(getattr(self, "planTable", None), 150), (getattr(self, "timeTable", None), 96),
                     (getattr(self, "costTable", None), 96), (getattr(self, "shiftTable", None), 110)]:
            if t is not None: self.tidy_table(t, h)

    def tidy_table(self, t, min_h):
        """表格观感：斑马纹、无网格、隐藏行号、只读、统一行高"""
        try:
            t.setAlternatingRowColors(True); t.setShowGrid(False); t.setWordWrap(False)
            t.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
            t.verticalHeader().setVisible(False)
            try: t.verticalHeader().setDefaultSectionSize(26)
            except Exception: pass
            t.horizontalHeader().setHighlightSections(False)
            try: t.horizontalHeader().setDefaultAlignment(qt.Qt.AlignLeft | qt.Qt.AlignVCenter)
            except Exception: pass
        except Exception: pass
        try: t.setMinimumHeight(min_h)
        except Exception: pass

    def val(self, k):
        return self.w[k].value

    def say(self, *a):
        self.log.appendPlainText(" ".join(str(x) for x in a)); slicer.app.processEvents()

    def case_paths(self):
        case = self.caseName.text.strip(); work = CACHE_DIR
        if not case: raise RuntimeError(L("先选病例文件夹或填病例编号", "Choose a case folder or enter a case ID first"))
        D = os.path.join(work, "w" + case)
        out = self.result_dir()
        if out and os.path.isdir(out) and not os.path.isdir(D):    # 缓存清掉了但结果文件夹还在：拷回来接着用，不用重新预处理
            import shutil
            shutil.copytree(out, D)
        return case, work, D

    def set_af_weight(self, side):
        """左侧（通常语言优势侧）AF 权重 1，右侧 0.5；侧别改了就跟着改"""
        w = 1.0 if side == "L" else 0.5
        if self.w["W_AF"].value != w:
            self.w["W_AF"].value = w; self.say(L(f"侧别 {side}：AF 权重设为 {w:g}", f"Side {side}: AF weight set to {w:g}"))

    def side_value(self, D, case):
        i = self.side.currentIndex
        if i == 1: return "R"
        if i == 2: return "L"
        try:
            sd = self.logic.detect_side(D, case); dx = getattr(self.logic, "side_dx", 99)
            if dx < 10:
                msg = L(f"注意：肿瘤核心离中线只有 {dx:.0f} mm，可能是中线或双侧肿瘤，自动判断的侧别（{sd}）不一定对，请在“肿瘤侧别”里手动确认",
                        f"Warning: tumour core only {dx:.0f} mm from the midline (midline or bilateral tumour?); the detected side ({sd}) may be wrong, please confirm Tumour side manually")
                self.say(msg); slicer.util.showStatusMessage(msg, 8000)
            return sd
        except Exception as e: self.say(L("侧别自动判断失败，按 R：", "Side detection failed, using R:"), e); return "R"

    # ---------- 1 数据 ----------
    def onCaseDir(self, path):
        if path: self.caseName.text = self.logic.case_id(path)
        if path and self._out_auto:      # 没手动选过输出位置：默认放在病例文件夹旁边；旁边有“分析”文件夹就放进去
            par = os.path.dirname(os.path.normpath(path)); ana = os.path.join(par, "分析")
            self._setting_out = True; self.outDir.currentPath = ana if os.path.isdir(ana) else par; self._setting_out = False
        self.update_out_label()

    def onOutDir(self, path):
        if not getattr(self, "_setting_out", False): self._out_auto = not path
        self.update_out_label()

    def result_dir(self):
        """用户看得到的结果文件夹：<输出位置>/<病例文件夹名（去掉 _nifti）>_Slicer"""
        cd = os.path.normpath(self.caseDir.currentPath or "")
        if not cd or cd == ".": return None
        base = self.outDir.currentPath or os.path.dirname(cd)
        name = os.path.basename(cd); name = name[:-6] if name.lower().endswith("_nifti") else name
        return os.path.join(base, name + "_Slicer")

    def update_out_label(self):
        r = self.result_dir(); self.outLabel.text = (L("结果文件夹：", "Result folder: ") + r) if r else ""

    def sync_out(self):
        """计算在纯英文路径的缓存里做（Slicer 命令行模块要求），做完把新文件和改过的文件同步到结果文件夹"""
        if getattr(self, "_testing", False): return
        try: case, work, D = self.case_paths()
        except Exception: return
        out = self.result_dir()
        if not out or not os.path.isdir(D): return
        import shutil
        for root, dirs, files in os.walk(D):
            rel = os.path.relpath(root, D); tgt = os.path.join(out, rel) if rel != "." else out
            os.makedirs(tgt, exist_ok=True)
            for fn in files:
                a, b = os.path.join(root, fn), os.path.join(tgt, fn)
                try:
                    if not os.path.exists(b) or os.path.getsize(a) != os.path.getsize(b) or os.path.getmtime(a) > os.path.getmtime(b) + 1:
                        shutil.copy2(a, b)
                except OSError as e: self.say("sync:", e)

    def pub(self, fn):
        """导出的文件：同步到结果文件夹，返回结果文件夹里的路径"""
        if not fn: return fn
        self.sync_out()
        if getattr(self, "_testing", False): return fn
        try: case, work, D = self.case_paths(); return os.path.join(self.result_dir(), os.path.relpath(fn, D))
        except Exception: return fn

    def onPreprocess(self):
        try:
            case, work, _ = self.case_paths()
            D, missing = self.logic.prepare(self.caseDir.currentPath, work, case)
            if missing: raise RuntimeError(L("病例文件夹里缺：", "Missing in case folder: ") + ", ".join(missing))
            for nt in getattr(self.logic, "notes", []): self.say(nt)
        except Exception as e:
            slicer.util.errorDisplay(str(e)); return
        side = self.side_value(D, case); self.say(L(f"病例 {case}，侧别 {side}，工作目录 {D}", f"Case {case}, side {side}, work folder {D}"))
        self.set_af_weight(side)
        fl = self.flip.currentText
        if self.flip.currentIndex != 0: open(os.path.join(D, "flip.txt"), "w").write(fl)
        env = qt.QProcessEnvironment.systemEnvironment()
        for k, v in dict(CASE=case, SIDE=side, WORK=work, SCRIPTS=SCRIPTS,
                         **{k: str(self.val(k)) for k, *_ in P_TRACT}).items(): env.insert(k, v)
        self.env = env
        self.queue = ([] if os.path.exists(os.path.join(D, "flip.txt")) else ["s0_flip.py"]) + ["s1_dti.py", "s2_tract.py"]
        self.steps_total = len(self.queue); self.steps_done = 0; self.cur = None; self.hits = set()
        import time; self.t0 = time.time()
        self.progress.value = 0; self.progress.visible = True; self.progLabel.visible = True; self.clock.start()
        self.btnPre.enabled = False; self.next_step()

    def onCancelPre(self):
        self.cancelled = True; self.queue = []
        if getattr(self, "proc", None) is not None and self.proc.state() != qt.QProcess.NotRunning: self.proc.kill()
        self.say(L("预处理已取消（已完成的步骤结果保留在工作目录）", "Preprocessing cancelled (results of finished steps stay in the work folder)"))

    def next_step(self):
        if getattr(self, "cancelled", False):
            self.cancelled = False; self.cur = None; self.clock.stop(); self.progLabel.text = L("已取消", "Cancelled")
            self.progress.value = 1000; self.hide_later(self.progress, self.progLabel); self.btnPre.enabled = True; self.btnCancel.enabled = False; self.btnCancel.visible = False; return
        self.btnCancel.enabled = True; self.btnCancel.visible = True
        if self.cur: self.steps_done += 1
        self.cur = None; self.hits = set(); self.update_progress()
        if not self.queue:
            self.clock.stop(); self.progress.value = 1000
            self.progLabel.text = L("完成", "Done") + f"  ({self.elapsed()})"; self.hide_later(self.progress, self.progLabel)
            self.btnPre.enabled = True; self.btnCancel.enabled = False; self.btnCancel.visible = False; self.sync_out()
            self.say(L("预处理完成，可以点“载入场景”；结果已同步到 ", "Preprocessing done; click “Load scene”; results copied to ") + (self.result_dir() or ""))
            if getattr(self, "_auto", False): qt.QTimer.singleShot(300, self._auto_continue)
            return
        sc = self.queue.pop(0); self.cur = sc; self.update_progress(); self.say(L(f"== 运行 {sc}（后台 Slicer，不弹窗口）", f"== Running {sc} (background Slicer, no window)"))
        self.proc = qt.QProcess(); self.proc.setProcessEnvironment(self.env)
        self.proc.setProcessChannelMode(qt.QProcess.MergedChannels)
        self.proc.connect("readyReadStandardOutput()", self.onProcOut)
        self.proc.connect("finished(int,QProcess::ExitStatus)", self.onProcDone)
        self.proc.start(slicer_exe(), ["--no-splash", "--no-main-window", "--python-script", os.path.join(SCRIPTS, sc)])

    def onProcOut(self):
        txt = bytes(self.proc.readAllStandardOutput().data()).decode("utf-8", "replace")
        for ln in txt.splitlines():
            if ln.startswith("LOG") or "Error" in ln or "Traceback" in ln: self.say(ln)
            if self.cur:
                for k, m in enumerate(MILESTONES.get(self.cur, [])):
                    if any(x in ln for x in m.split("|")): self.hits.add(k)
        self.update_progress()

    def elapsed(self):
        import time; t = int(time.time() - getattr(self, "t0", time.time())); return f"{t//60}:{t%60:02d}"

    def update_progress(self):
        if not getattr(self, "steps_total", 0): return
        frac = 0.0
        if self.cur:
            ms = MILESTONES.get(self.cur, []); frac = (len(self.hits) + 0.5) / (len(ms) + 1) if ms else 0.5
        self.progress.value = int(1000 * (self.steps_done + frac) / self.steps_total)
        if self.cur:
            zh, en = STEP_NAME.get(self.cur, (self.cur, self.cur))
            self.progLabel.text = L(f"第 {self.steps_done + 1}/{self.steps_total} 步：{zh}  已用 {self.elapsed()}",
                                    f"Step {self.steps_done + 1}/{self.steps_total}: {en}  elapsed {self.elapsed()}")

    def onProcDone(self, code, status):
        self.say(L(f"   结束（返回码 {code}）", f"   finished (exit code {code})")); self.next_step()

    def onLoad(self):
        try:
            case, work, D = self.case_paths()
            if not all(os.path.exists(os.path.join(D, f"{case}_{x}")) for x in ("T1c_bias.nii.gz", "brain_segmentation.nii.gz", "tumor_segmentation.nii.gz")):
                self.logic.prepare(self.caseDir.currentPath, work, case)
            chk = self.logic.check_inputs(D, case)
            bad = [t for l, t in chk if l == "bad"]; warn = [t for l, t in chk if l == "warn"]
            if bad:
                slicer.util.errorDisplay(L("输入数据不能用：\n", "Input data cannot be used:\n") + "\n".join("• " + t for t in bad)
                                         + L("\n\n插件需要 UCSF-PDGM / BraTS 格式：已去颅骨、各序列配准到 T1c、肿瘤标签 1/2/4（或 3）。", "\n\nThe planner expects UCSF-PDGM / BraTS format: skull-stripped, all series registered to T1c, tumour labels 1/2/4 (or 3)."))
                return
            for t in warn: self.say(L("注意：", "Note: ") + t)
            import time; t0 = time.time()
            self.clear_case()               # 先清掉上一个病例：否则旧病例的纤维束、分割、SWI 会混进新病例的规划
            self.logic.case_folder = self.caseDir.currentPath
            tr = self.logic.load(D, case, lambda fr, tx: self.set_progress(self.loadBar, self.loadLab, fr, L("载入：", "Loading: ") + tx, t0))
            self.hide_later(self.loadBar, self.loadLab)
            self.apply_all_styles()
            self.say(L(f"已载入 {case}；纤维束：{tr or '没有（先做预处理）'}", f"Loaded {case}; tracts: {tr or 'none (run preprocessing first)'}"))
            self.planner_layout()
        except Exception as e:
            slicer.util.errorDisplay(str(e))

    def clear_case(self):
        """载入新病例前清空场景和上一次的结果（图谱配准、方案、脑移位都绑定在旧病例上）"""
        slicer.mrmlScene.Clear(0)
        self.G = None
        for k in ("atlas",):
            if hasattr(self.logic, k): setattr(self.logic, k, None)
        for k in ("atlas_lines", "check_items"):
            if hasattr(self, k): setattr(self, k, [])

    # ---------- 2 器件 ----------
    def preset_name(self):
        i = self.preset.currentIndex; keys = list(PRESETS)
        return keys[i] if 0 <= i < len(keys) else None

    def onPreset(self, i):
        name = self.preset_name()
        if name in PRESETS:
            self.device_json = None
            self.small_layout = PRESETS[name].get("SMALL_LAYOUT", "cells")
            self.small_n = int(PRESETS[name].get("SMALL_N", 48))
            for k, v in PRESETS[name].items():
                if k == "SMALL": self.small.checked = v
                elif k in self.w: self.w[k].value = v
        for k in ["NX", "NY", "PITCH"]: self.w[k].enabled = name in PRESETS
        self.small.enabled = name in PRESETS
        self.update_dev_info()

    def update_dev_info(self):
        if self.device_json:
            d = self.device_json
            self.devInfo.text = L(f"自定义器件：{d.get('name', '')}，大触点 {len(d.get('large', []))} 个，小触点 {len(d.get('small', []))} 个",
                                 f"Custom device: {d.get('name', '')}, {len(d.get('large', []))} large and {len(d.get('small', []))} small contacts")
        else:
            nx, ny = int(self.val("NX")), int(self.val("NY")); rows_ = getattr(self, "small_layout", "cells") == "rows"
            ns = (nx*(ny-1) if rows_ else (nx-1)*(ny-1)) if self.small.checked and ny > 1 and (rows_ or nx > 1) else 0
            w_, h_ = (nx-1)*self.val('PITCH'), (ny-1)*self.val('PITCH')
            note = DEVICE_NOTES.get(self.preset_name(), ("", ""))
            self.devInfo.text = L(f"网格器件：大触点 {nx*ny} 个，小触点 {ns} 个；外形约 {w_:.0f} × {h_:.0f} mm（触点中心）", 
                                  f"Grid device: {nx*ny} large and {ns} small contacts; about {w_:.0f} × {h_:.0f} mm (contact centres)") + (("\n" + L(*note)) if any(note) else "")

    def onImportDevice(self):
        fn = qt.QFileDialog.getOpenFileName(None, T("导入器件 JSON"), "", "JSON (*.json)")
        if not fn: return
        try:
            d = json.load(open(fn, encoding="utf-8"))
            if "large" not in d and "nx" in d:   # 网格写法
                d = self.grid_device(int(d["nx"]), int(d["ny"]), float(d["pitch"]), bool(d.get("small", False)), d)
            for k, jk in [("STIM_REACH", "stim_reach"), ("REC_REACH_L", "rec_reach_large"), ("REC_REACH_S", "rec_reach_small")]:
                if jk in d: self.w[k].value = float(d[jk])
            self.device_json = d; self.preset.setCurrentIndex(self.preset.count - 1); self.update_dev_info()
            self.say(L("已导入器件：", "Device imported:"), fn)
        except Exception as e:
            slicer.util.errorDisplay(L("器件文件读不了：", "Cannot read device file: ") + str(e))

    @staticmethod
    def grid_device(nx, ny, pitch, small, extra=None):
        large = [[(i - (nx-1)/2)*pitch, (j - (ny-1)/2)*pitch] for i in range(nx) for j in range(ny)]
        sm = [[(i - (nx-2)/2)*pitch, (j - (ny-2)/2)*pitch] for i in range(nx-1) for j in range(ny-1)] if small and nx > 1 and ny > 1 else []
        d = dict(extra or {}); d.update(large=large, small=sm); return d

    def current_device(self):
        if self.device_json: d = dict(self.device_json)
        else: d = self.grid_device(int(self.val("NX")), int(self.val("NY")), self.val("PITCH"), self.small.checked, {"name": self.preset_name() or "custom"})
        d.update(stim_reach=self.val("STIM_REACH"), rec_reach_large=self.val("REC_REACH_L"), rec_reach_small=self.val("REC_REACH_S"))
        return d

    def onExportDevice(self):
        fn = qt.QFileDialog.getSaveFileName(None, T("导出器件 JSON"), "device.json", "JSON (*.json)")
        if fn: json.dump(self.current_device(), open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1); self.say(L("已导出：", "Exported:"), fn)

    # ---------- 4 开颅 ----------
    def onPlaceEntry(self):
        n = slicer.util.getFirstNodeByName("Entry")
        if n is None: n = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Entry")
        n.RemoveAllControlPoints(); n.SetMaximumNumberOfControlPoints(1)
        slicer.modules.markups.logic().StartPlaceMode(0)
        sel = slicer.app.applicationLogic().GetSelectionNode(); sel.SetActivePlaceNodeID(n.GetID())
        self.entryMode.setCurrentIndex(2); self.say(L("在 3D 视图的皮层上单击以放置入口点", "Click on the cortex in the 3D view to place the entry point"))

    # ---------- 参数 ----------
    def overrides(self, D, case):
        o = {k: self.val(k) for spec in [P_DEVICE, P_TARGET, P_CRANIO, P_OPT, P_TIME] for k, *_ in spec}
        for k in ["NX", "NY", "MAX_ARRAYS", "STRIP_N"]:
            if k in o: o[k] = int(o[k])
        o["MAX_STRAIN"] /= 100.0
        o["BND_SRC"] = "flair" if self.bndFlair.checked else "core"
        o["SMALL"] = self.small.checked; o["SMALL_LAYOUT"] = getattr(self, "small_layout", "cells"); o["SMALL_N"] = getattr(self, "small_n", 48)
        o["STIM_MODEL"] = self.stimModel.checked; o["AD_STRIP"] = self.adStrip.checked; o["REQ_HEALTHY"] = self.reqHealthy.checked
        o["FMRI_PATH"] = self.fmriPath.currentPath if os.path.isfile(self.fmriPath.currentPath or "") else ""
        o["NTMS_PATH"] = self.ntmsPath.currentPath if os.path.isfile(self.ntmsPath.currentPath or "") else ""
        o["ANGLES"] = list(range(0, 180, max(int(o.pop("ANGLE_STEP")), 1)))
        o["TRACT_W"] = {"CST": o.pop("W_CST"), "AF": o.pop("W_AF")}
        o["ASLEEP_FIRST"] = self.asleepFirst.checked; o["PASSIVE_ASLEEP"] = self.passiveAsleep.checked; o["MOTOR_AWAKE"] = self.motorAwake.checked
        o["DEVICE"] = self.current_device() if self.device_json else None
        m = self.entryMode.currentIndex
        o["WIN_SHAPE"] = ["circle", "ellipse", "rect"][self.winShape.currentIndex]; o["WIN_FIT"] = self.winFit.checked; o["NCE_TARGET"] = self.nceTarget.checked; o["AUTO_SHAPE"] = self.autoShape.checked
        o["ENTRY_MODE"] = {1: "nearest", 3: "centre"}.get(m, "auto"); o["ENTRY_NAME"] = "Entry" if m == 2 else "__no_manual_entry__"
        o["OUT"] = os.path.join(D, "placement_scores.csv")
        if self.usePrior.checked and getattr(self.logic, "atlas", None) is not None:
            pri = {int(k): float(v["prior"]) for k, v in ELOQ["regions"].items()}
            o["SITE_PRIOR"] = lambda P: [pri.get(int(l), 1.0) for l in self.logic.atlas_labels(P)]
        return o

    def all_params(self):
        d = {k: self.val(k) for spec in [P_DEVICE, P_TARGET, P_CRANIO, P_OPT, P_TIME, P_TRACT, P_SKULL, P_COST, P_SHIFT] for k, *_ in spec}
        d.update(SMALL=self.small.checked, ASLEEP_FIRST=self.asleepFirst.checked, PASSIVE_ASLEEP=self.passiveAsleep.checked, MOTOR_AWAKE=self.motorAwake.checked,
                 ENTRY_MODE=self.entryMode.currentIndex, PRESET=self.preset.currentIndex, DEVICE=self.device_json, WIN_SHAPE_IDX=self.winShape.currentIndex, WIN_FIT=self.winFit.checked,
                 STIM_MODEL=self.stimModel.checked, AD_STRIP=self.adStrip.checked, REQ_HEALTHY=self.reqHealthy.checked, FMRI_PATH=self.fmriPath.currentPath, NTMS_PATH=self.ntmsPath.currentPath)
        return d

    def onSaveParams(self):
        fn = qt.QFileDialog.getSaveFileName(None, T("保存参数"), "planner_params.json", "JSON (*.json)")
        if fn: json.dump(self.all_params(), open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1); self.say(L("参数已保存：", "Parameters saved:"), fn)

    def onLoadParams(self):
        fn = qt.QFileDialog.getOpenFileName(None, T("读取参数"), "", "JSON (*.json)")
        if not fn: return
        self.apply_params(json.load(open(fn, encoding="utf-8"))); self.say(L("参数已读取：", "Parameters loaded:"), fn)

    def apply_params(self, d):
        pr = d.get("PRESET", 0)
        if isinstance(pr, str): pr = list(PRESETS).index(pr) if pr in PRESETS else 0
        self.preset.setCurrentIndex(int(pr))
        for k, v in d.items():
            if k in self.w: self.w[k].value = v
        self.small.checked = d.get("SMALL", True); self.asleepFirst.checked = d.get("ASLEEP_FIRST", True)
        self.motorAwake.checked = d.get("MOTOR_AWAKE", False); self.entryMode.setCurrentIndex(d.get("ENTRY_MODE", 0))
        self.device_json = d.get("DEVICE"); self.update_dev_info()
        self.winShape.setCurrentIndex(int(d.get("WIN_SHAPE_IDX", 1))); self.winFit.checked = bool(d.get("WIN_FIT", True))
        self.stimModel.checked = bool(d.get("STIM_MODEL", True)); self.adStrip.checked = bool(d.get("AD_STRIP", True))
        self.reqHealthy.checked = bool(d.get("REQ_HEALTHY", True)); self.fmriPath.currentPath = d.get("FMRI_PATH", "") or ""; self.ntmsPath.currentPath = d.get("NTMS_PATH", "") or ""

    # ---------- 运行 ----------
    def onRun(self):
        try:
            case, work, D = self.case_paths()
        except Exception as e:
            slicer.util.errorDisplay(str(e)); return
        if not slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode"):
            self.onLoad()
        nt = sum(n.GetPolyData().GetNumberOfPoints() for n in slicer.util.getNodesByClass("vtkMRMLModelNode") if n.GetName().startswith("tract_") and n.GetPolyData())
        if nt == 0:
            slicer.util.errorDisplay(L("没有纤维束（0 条）：先检查梯度翻转（s0，“梯度翻转”选自动检测）并重新预处理，或放宽种子 FA。",
                                       "No tracts (0 streamlines): check the gradient flip (s0, set Gradient flip to Auto-detect) and preprocess again, or relax the seed FA.")); return
        self.set_af_weight(self.side_value(D, case))
        for nd in list(slicer.util.getNodesByClass("vtkMRMLModelNode")):
            if nd.GetName().startswith(("Plan_", "Targets_", "EntryMap_", "Window_edge", "Entry_point", "Veins_")): slicer.mrmlScene.RemoveNode(nd)
        for nd in list(slicer.util.getNodesByClass("vtkMRMLMarkupsNode")):
            if nd.GetName() in ("Order_labels", "Order_path", "Corridor"): slicer.mrmlScene.RemoveNode(nd)
        self.corr = None; self.corrSlider.enabled = False; self.corrLabel.text = ""
        self.shift_rows = None; self.shiftTable.setRowCount(0); self.shiftNote.text = T("尚未分析")
        self.btnRun.enabled = False; qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        self.say(L("== 生成方案 …", "== Running optimisation …"))
        try:
            import time; t0 = time.time()
            self.set_progress(self.runBar, self.runLab, 0.0, "开始|Starting", t0)
            self.G, out = self.logic.plan(D, case, self.overrides(D, case),
                                          lambda fr, tx: self.set_progress(self.runBar, self.runLab, fr, tx, t0))
            self.set_progress(self.runBar, self.runLab, 1.0, "完成|Done", t0); self.hide_later(self.runBar, self.runLab)
            if self.autoSkull.checked: self.make_window()
            for ln in out.splitlines(): self.say(ln)
            self.show_results(); self.save_params_to_scene(); self.sync_out()
        except Exception as e:
            import traceback; self.say(traceback.format_exc()); slicer.util.errorDisplay(L("运行出错：", "Run failed: ") + str(e))
        finally:
            qt.QApplication.restoreOverrideCursor(); self.btnRun.enabled = True

    def show_results(self):
        try: self.draw_order()
        except Exception:
            import traceback; self.say(traceback.format_exc())
        self.apply_all_styles(); self.show_cost()
        G = self.G; plan = G["PLAN"]; T = G["TIME"]; tr_ = globals()["T"]
        man = self.entryMode.currentIndex == 2; ms = T['scen']['MAIN'].get('stim', 0); ed = self.entry_desc()
        Bd = G.get("BND") or {}
        self.summary.text = L(f"入口点：{ed[0]}。切除边界靠功能区 {Bd.get('n_req', 0)} 段，完整判定 {Bd.get('full', 0)} 段。\n"
                              f"共 {len(plan)} 次放置；要测的语言位点 {T['lang_sites']} 个，经麻醉期筛选后清醒期约需刺激 {ms:.1f} 个；运动位点 {T['motor_sites']} 个。点击表格中的一行可单独查看该次放置。",
                              f"Entry: {ed[1]}. {Bd.get('n_req', 0)} boundary segments near function, {Bd.get('full', 0)} fully decided.\n"
                              f"{len(plan)} placements; {T['lang_sites']} language sites to test, about {ms:.1f} to stimulate awake after asleep screening; {T['motor_sites']} motor sites. Click a row to view that placement alone.")
        self.show_value(); self.show_atlas_summary(); self.show_win_check(); self.show_checks()
        for b in self.boxes: b.collapsed = (b is not self.resultBox and b is not getattr(self, "quickBox", None))     # 出结果后只展开结果区和快速开始
        self.planTable.setRowCount(len(plan))
        for k, p in enumerate(plan):
            r = p["r"]
            vals = [k + 1, tr_(G["phase"](r)[1]), f"{r['angle']}°", self.seg_cell(r), "/".join(map(str, r.get("zones", []))) or "—", f"{r['rec']:.0%}", f"{r['fit']:.1f}", f"{r.get('strain', 0):.0%}", r.get("vein_n", 0), "+".join(sorted(r["srcs"])) or "—", self.placement_regions(r)]
            for j, v in enumerate(vals): self.planTable.setItem(k, j, qt.QTableWidgetItem(str(v)))
        self.planTable.resizeColumnsToContents()
        self.show_why()
        sc = T["scen"]; self.timeTable.setRowCount(len(SCEN_NAMES))
        for k, (key, lab) in enumerate(SCEN_NAMES):
            v = sc[key]
            for j, x in enumerate([tr_(lab), f"{v['awake']:.1f}", f"{v['asleep']:.1f}", f"{v['total']:.1f}", f"{v['missed']:.1f}"]):
                self.timeTable.setItem(k, j, qt.QTableWidgetItem(x))
        self.timeTable.resizeColumnsToContents()
        self.fit_table(self.timeTable)
        lm = slicer.app.layoutManager(); self.planner_layout(fit3d=False)
        try:   # 从脑中心朝入口点方向看，白背景
            import numpy as np
            vn = lm.threeDWidget(0).mrmlViewNode(); vn.SetBackgroundColor(1, 1, 1); vn.SetBackgroundColor2(1, 1, 1)
            lab = self.viewChecks["labels"].checked; vn.SetBoxVisible(lab); vn.SetAxisLabelsVisible(lab)
            if self.viewChecks["marker"].checked: vn.SetOrientationMarkerType(slicer.vtkMRMLAbstractViewNode.OrientationMarkerTypeHuman)
            c = G["SP"].mean(0); n = G["entry"] - c; n /= np.linalg.norm(n)
            cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(vn)
            cam.SetFocalPoint(*c); cam.SetPosition(*(c + n*420)); cam.SetViewUp(0, 0, 1)
            self.fit_3d()
        except Exception:
            lm.threeDWidget(0).threeDView().resetFocalPoint()

    # ---------- 脑区图谱 ----------
    def onAtlas(self):
        try: case, work, D = self.case_paths()
        except Exception as e: slicer.util.errorDisplay(str(e)); return
        space = self.atlasDir.currentPath
        if not space or not os.path.isdir(space): slicer.util.errorDisplay(L("先选模板/图谱文件夹", "Choose the template / atlas folder first")); return
        qt.QSettings().setValue(ATLAS_KEY, space)
        if slicer.util.getFirstNodeByName(f"{case}_T1c_bias") is None: self.onLoad()
        import time; t0 = time.time(); qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self.logic.register_atlas(D, case, space, lambda fr, tx: self.set_progress(self.atlasBar, self.atlasLab, fr, tx, t0))
            self.hide_later(self.atlasBar, self.atlasLab)
            self.atlasNote.text = L(f"已配准到 Harvard-Oxford 模板（刚体 + 仿射，肿瘤核心已遮掉），用时 {self.elapsed_from(t0)}。重新生成方案后生效。",
                                    f"Registered to the Harvard-Oxford template (rigid + affine, tumour core masked) in {self.elapsed_from(t0)}. Generate the plan again to use it.")
            self.say(self.atlasNote.text)
            if self.G is not None: self.show_atlas_summary()
        except Exception as e:
            import traceback; self.say(traceback.format_exc()); slicer.util.errorDisplay(str(e))
        finally: qt.QApplication.restoreOverrideCursor()

    @staticmethod
    def elapsed_from(t0):
        import time; t = int(time.time() - t0); return f"{t//60}:{t%60:02d}"

    def placement_regions(self, r):
        if getattr(self.logic, "atlas", None) is None: return "—"
        import numpy as np
        mix = self.logic.atlas_mix(r["L"])
        if not mix:
            labs = self.logic.atlas_labels(r["L"]); labs = labs[labs > 0]
            if not len(labs): return "—"
            u, c = np.unique(labs, return_counts=True); mix = [(int(u[i]), c[i]/c.sum()) for i in np.argsort(-c)]
        return " / ".join(f"{region_name(l)} {p:.0%}" for l, p in mix[:2] if p >= 0.1) or region_name(mix[0][0])

    def show_atlas_summary(self):
        """肿瘤附近（病灶 15 mm 内）皮层的脑区构成 → 按位置给重点测试的功能、任务和纤维束"""
        self.atlas_lines = []
        if self.G is None or getattr(self.logic, "atlas", None) is None: return
        import numpy as np
        G = self.G; near = np.where(np.asarray(G["d_core"]) <= 25)[0]      # 肿瘤核心 25 mm 内的皮层（FLAIR 带可能很大，不用它）
        labs = self.logic.atlas_labels(G["SP"][near]); labs = labs[labs > 0]
        if not len(labs): return
        u, c = np.unique(labs, return_counts=True); o = np.argsort(-c); tot = c.sum()
        top = [(int(u[i]), c[i]/tot) for i in o[:5]]
        gcount = {}
        for lab, cnt in zip(u, c):
            g = ELOQ["regions"].get(str(int(lab)), {}).get("group")
            if g: gcount[g] = gcount.get(g, 0) + cnt
        if not gcount: return
        groups = [g for g, n in sorted(gcount.items(), key=lambda x: -x[1]) if n/tot >= 0.2][:2] or [max(gcount, key=gcount.get)]
        zh = lang() == "zh"
        regs = ("、" if zh else ", ").join(f"{region_name(l)} {p:.0%}" for l, p in top)
        lines = [L("肿瘤核心附近皮层（25 mm 内）：", "Cortex near the tumour core (within 25 mm): ") + regs]
        for g in groups:
            q = ELOQ["groups"][g]
            lines.append(L(f"{q['name_zh']} → 重点测：{q['functions_zh']}；任务：{q['tasks_zh']}；关注纤维束：{q['tracts_zh']}",
                           f"{q['name']} → focus: {q['functions']}; tasks: {q['tasks']}; tracts: {q['tracts']}"))
        if np.any(np.asarray(G.get("SITE_W", 1.0)) != 1.0):
            lines.append(L("边界段风险已按脑区阳性概率加权（中央前回、额下回岛盖部、颞上/中回后部、缘上回最高）。",
                           "Stimulation targets weighted by regional positive probability (highest: precentral, pars opercularis, posterior superior/middle temporal, supramarginal)."))
        self.atlas_lines = lines
        self.atlasNote.text = T("重点测试建议") + L("：\n", ":\n") + "\n".join(lines)
        self.say(*lines)

    # ---------- 配准检查（参考 trajectoryGuide：叠图对比 + 通过/不通过） ----------
    def onRegQC(self):
        try: case, work, D = self.case_paths()
        except Exception as e: slicer.util.errorDisplay(str(e)); return
        fa_fn, tf_fn = os.path.join(D, f"{case}_FA.nrrd"), os.path.join(D, f"{case}_DWI_to_T1c.h5")
        if not os.path.exists(fa_fn): slicer.util.errorDisplay(L("先做预处理（没有 FA）", "Run preprocessing first (no FA found)")); return
        t1c = slicer.util.getFirstNodeByName(f"{case}_T1c_bias")
        if t1c is None: self.onLoad(); t1c = slicer.util.getFirstNodeByName(f"{case}_T1c_bias")
        fa = slicer.util.getFirstNodeByName("FA_check")
        if fa is None:
            fa = slicer.util.loadVolume(fa_fn); fa.SetName("FA_check")
            if os.path.exists(tf_fn):
                tf = slicer.util.loadTransform(tf_fn); tf.SetName("DWI_to_T1c_check"); fa.SetAndObserveTransformNodeID(tf.GetID())
            fa.GetDisplayNode().SetAutoWindowLevel(False); fa.GetDisplayNode().SetWindowLevel(0.8, 0.4)
        slicer.util.setSliceViewerLayers(background=t1c, foreground=fa, foregroundOpacity=self.regOp.value/100.0)
        self.planner_layout()
        self.regOp.enabled = True
        self.say(L("配准检查：FA 叠在 T1c 上，拖滑条看脑轮廓、侧脑室、胼胝体是否对齐，然后点通过或不通过",
                   "Registration check: FA over T1c; drag the slider to compare brain outline, ventricles and corpus callosum, then mark OK or failed"))

    def reg_status(self):
        try: case, work, D = self.case_paths(); return open(os.path.join(D, "registration_check.txt"), encoding="utf-8").read().strip()
        except Exception: return ""

    def onRegVerdict(self, ok):
        try: case, work, D = self.case_paths()
        except Exception as e: slicer.util.errorDisplay(str(e)); return
        import datetime
        txt = ("pass" if ok else "fail") + " " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        open(os.path.join(D, "registration_check.txt"), "w", encoding="utf-8").write(txt)
        self.say(L("配准检查已记录：", "Registration check recorded: ") + (L("通过", "OK") if ok else L("不通过", "failed")))
        if hasattr(self, "quickReg"): self.quickReg.visible = not ok
        if not ok:
            slicer.util.warningDisplay(L("配准不通过：换一个梯度翻转设置或检查数据后重新预处理，纤维束和方案都依赖这一步。",
                                         "Registration failed: change the gradient flip setting or check the data, then preprocess again; tracts and plan depend on this step."))

    # ---------- 通道视图（参考 trajectoryGuide 的探针眼视图） ----------
    def onCorridor(self):
        if self.G is None: slicer.util.errorDisplay(L("先生成方案", "Generate a plan first")); return
        import numpy as np
        G = self.G; e = np.asarray(G["entry"], float); tum = G["tumor"]
        a = slicer.util.arrayFromVolume(tum); idx = np.argwhere(np.isin(np.rint(a), [1, 3, 4]))
        if not len(idx): slicer.util.errorDisplay(L("没有肿瘤核心", "No tumour core found")); return
        m = vtk.vtkMatrix4x4(); tum.GetIJKToRASMatrix(m); M = slicer.util.arrayFromVTKMatrix(m)
        tgt = (M @ np.r_[idx.mean(0)[::-1], 1.0])[:3]
        v = tgt - e; length = float(np.linalg.norm(v)); n = v / length
        self.corr = (e, n, length)
        self.corr_tracts = {nd.GetName()[6:]: slicer.util.arrayFromModelPoints(nd).copy()
                            for nd in slicer.util.getNodesByClass("vtkMRMLModelNode") if nd.GetName().startswith("tract_")}
        for nd in list(slicer.util.getNodesByClass("vtkMRMLMarkupsNode")):
            if nd.GetName() == "Corridor": slicer.mrmlScene.RemoveNode(nd)
        ln = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", "Corridor")
        ln.AddControlPoint(vtk.vtkVector3d(*[float(x) for x in e])); ln.AddControlPoint(vtk.vtkVector3d(*[float(x) for x in tgt])); ln.SetLocked(True)
        dn = ln.GetDisplayNode(); dn.SetSelectedColor(0.0, 0.8, 0.8); dn.SetColor(0.0, 0.8, 0.8); dn.SetPropertiesLabelVisibility(False); dn.SetLineThickness(0.5)
        t1c = slicer.util.getFirstNodeByName(f"{self.caseName.text.strip()}_T1c_bias")
        if t1c: slicer.util.setSliceViewerLayers(background=t1c, foregroundOpacity=0)
        self.planner_layout(fit3d=False)
        self.corrSlider.enabled = True; self.corrSlider.maximum = round(length + 20)
        self.corrSlider.value = 0; self.onCorridorDepth(0)

    def onCorridorDepth(self, d):
        if not getattr(self, "corr", None): return
        import numpy as np
        e, n, length = self.corr; p = e + n*float(d)
        t = np.cross(n, [0, 0, 1.0])
        if np.linalg.norm(t) < 1e-3: t = np.cross(n, [1.0, 0, 0])
        t /= np.linalg.norm(t)
        sn = slicer.app.layoutManager().sliceWidget("Red").mrmlSliceNode()
        sn.SetSliceToRASByNTP(*n, *t, *p, 0)
        for nm in ("Green", "Yellow"): slicer.app.layoutManager().sliceWidget(nm).mrmlSliceNode().JumpSliceByCentering(*p)
        parts = []
        for k, pts in sorted(self.corr_tracts.items()):
            sl = pts[np.abs((pts - p) @ n) < 1.5]
            if len(sl):
                r = (sl - p) - np.outer((sl - p) @ n, n); parts.append(f"{k} {np.linalg.norm(r, axis=1).min():.0f} mm")
            else: parts.append(f"{k} —")
        self.corrLabel.text = L(f"深度 {d:.0f} mm（离核心中心 {length - d:.0f} mm）：通道轴到纤维束最近 " + "，".join(parts) + "（— = 这一层没有）",
                                f"Depth {d:.0f} mm ({length - d:.0f} mm to core centre): nearest tract to the corridor axis " + ", ".join(parts) + " (— = none at this depth)")

    # ---------- 参数存进场景（参考 trajectoryGuide 的参数节点）：保存 .mrb 后参数跟着走 ----------
    PARAM_NODE = "INBRAINPlanner_parameters"

    def save_params_to_scene(self):
        nd = slicer.mrmlScene.GetFirstNodeByName(self.PARAM_NODE)
        if nd is None:
            nd = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode", self.PARAM_NODE); nd.SetHideFromEditors(True)
        d = self.all_params(); d.update(_caseDir=self.caseDir.currentPath, _case=self.caseName.text, _out=self.outDir.currentPath)
        nd.SetAttribute("params", json.dumps(d, ensure_ascii=False))

    def restore_params_from_scene(self):
        nd = slicer.mrmlScene.GetFirstNodeByName(self.PARAM_NODE)
        if nd is None or nd.GetAttribute("params") is None or getattr(self, "_restored_from", None) == nd.GetID(): return
        try:
            d = json.loads(nd.GetAttribute("params")); self._restored_from = nd.GetID()
            if d.get("_caseDir"): self.caseDir.currentPath = d["_caseDir"]
            if d.get("_case"): self.caseName.text = d["_case"]
            if d.get("_out"): self.outDir.currentPath = d["_out"]
            self.apply_params(d); self.say(L("已从场景恢复参数", "Parameters restored from the scene"))
        except Exception as e: self.say("restore:", e)

    # ---------- 导出导航坐标：每片中心、法向、长轴和四个角，RAS 和 LPS 两套 ----------
    def nav_rows(self):
        import numpy as np
        G = self.G; rows = []
        e = np.asarray(G["entry"], float); rows.append(dict(name="Entry", order=0, phase="", p=e, n=None, u=None))
        for k, pl in enumerate(G["PLAN"], 1):
            Lc = np.asarray(pl["r"]["L"], float); c0 = Lc.mean(0)
            _, i = G["stree"].query(c0); c = G["SP"][i]; n = G["SN"][i]
            X = Lc - c0; X -= np.outer(X @ n, n)
            u = np.linalg.svd(X, full_matrices=False)[2][0] if len(Lc) > 1 else np.cross(n, [0, 0, 1.0])
            u -= (u @ n)*n; u /= np.linalg.norm(u); v = np.cross(n, u)
            a, b = X @ u, X @ v
            corners = [c + a.min()*u + b.min()*v, c + a.max()*u + b.min()*v, c + a.max()*u + b.max()*v, c + a.min()*u + b.max()*v]
            ph = globals()["T"](G["phase"](pl["r"])[1])
            rows.append(dict(name=f"Plan_{k}_center", order=k, phase=ph, p=c, n=n, u=u))
            for j, q in enumerate(corners, 1): rows.append(dict(name=f"Plan_{k}_corner{j}", order=k, phase=ph, p=q, n=None, u=None))
        return rows

    def onExportNav(self):
        if self.G is None: slicer.util.errorDisplay(L("先生成方案", "Generate a plan first")); return None
        import csv
        case, work, D = self.case_paths(); rows = self.nav_rows()
        fn_csv = os.path.join(D, f"{case}_plan_navigation.csv")
        with open(fn_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "order", "phase", "R", "A", "S", "L_lps", "P_lps", "S_lps", "normal_R", "normal_A", "normal_S", "axis_R", "axis_A", "axis_S"])
            for r in rows:
                p = r["p"]; n = r["n"] if r["n"] is not None else [""]*3; u = r["u"] if r["u"] is not None else [""]*3
                fmt = lambda x: f"{x:.2f}" if x != "" else ""
                w.writerow([r["name"], r["order"], r["phase"], *[fmt(x) for x in p], fmt(-p[0]), fmt(-p[1]), fmt(p[2]), *[fmt(x) for x in n], *[fmt(x) for x in u]])
        for nd in list(slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode")):
            if nd.GetName() == "Plan_navigation": slicer.mrmlScene.RemoveNode(nd)
        fid = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Plan_navigation")
        for r in rows: fid.AddControlPoint(vtk.vtkVector3d(*[float(x) for x in r["p"]]), r["name"])
        fid.GetDisplayNode().SetVisibility(False)
        fn_fcsv = os.path.join(D, f"{case}_plan_navigation.fcsv")
        slicer.util.saveNode(fid, fn_fcsv)
        fn_bm = self.export_segment_bookmarks(D, case)
        res = tuple(self.pub(x) for x in (fn_csv, fn_fcsv, fn_bm) if x)
        self.say(L("导航坐标已导出：", "Navigation coordinates exported:"), *res)
        return res

    def export_segment_bookmarks(self, D, case):
        """边界段导出成导航书签（代替术中贴在脑表面的 post-it）：每段一个点，名字 = 段号、纤维束、规划状态；
        术中在导航里改名或改描述记下刺激结果（阴性 / 阳性 / 后放电）"""
        import numpy as np, csv
        G = self.G; B = G.get("BND") or {}
        if not B.get("n_seg"): return None
        SEGC, req, src = np.asarray(G["SEGC"]), np.asarray(G["SEG_REQ"]), G["seg_src"]
        done = np.asarray(G["SEG_DONE"]); why = {w["seg"]: w for w in G.get("SEG_WHY", [])}
        st = {3: L("可分离", "separable"), 2: L("仅功能可判", "function only"), 1: L("仅确认边界", "edge only"), 0: L("待测", "to test")}
        sep = np.asarray(G.get("SEG_SEP", np.zeros(len(SEGC), bool)))
        for nd in list(slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode")):
            if nd.GetName() == "Boundary_bookmarks": slicer.mrmlScene.RemoveNode(nd)
        fid = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Boundary_bookmarks")
        fn_csv = os.path.join(D, f"{case}_boundary_bookmarks.csv")
        with open(fn_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["label", "segment", "tract", "planned_status", "next_step", "R", "A", "S", "L_lps", "P_lps", "S_lps", "intraop_result"])
            for k, p in enumerate(SEGC):
                if req[k]: status = st[3 if sep[k] else int(done[k])]; tract = str(src[k])
                else: status = L("低风险（按影像）", "low risk (imaging)"); tract = "—"
                nxt = L(why[k]["zh"], why[k]["en"]) if k in why else ""
                lab = f"S{k + 1} {tract} {status}"
                i = fid.AddControlPoint(vtk.vtkVector3d(*[float(x) for x in p]), lab); fid.SetNthControlPointDescription(i, nxt)
                w.writerow([lab, k + 1, tract, status, nxt, *[f"{x:.2f}" for x in p], f"{-p[0]:.2f}", f"{-p[1]:.2f}", f"{p[2]:.2f}", ""])
        dn = fid.GetDisplayNode(); dn.SetVisibility(False); dn.SetTextScale(2.5)
        fn_fcsv = os.path.join(D, f"{case}_boundary_bookmarks.fcsv"); slicer.util.saveNode(fid, fn_fcsv)
        return fn_fcsv

    # ---------- 视图工具（参考 trajectoryGuide 的 settingsPanel） ----------
    def onViewToggle(self, key, on):
        lm = slicer.app.layoutManager()
        if key == "cross":
            ch = slicer.util.getNode("Crosshair"); ch.SetCrosshairMode(ch.ShowBasic if on else ch.NoCrosshair)
        elif key == "link":
            for cn in slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode"): cn.SetLinkedControl(on)
        elif key == "inter":
            for nm in lm.sliceViewNames():
                sn = lm.sliceWidget(nm).mrmlSliceNode(); sn.SetSliceVisible(on)
        elif key == "labels":
            for vn in slicer.util.getNodesByClass("vtkMRMLViewNode"): vn.SetBoxVisible(on); vn.SetAxisLabelsVisible(on)
        elif key == "marker":
            t = slicer.vtkMRMLAbstractViewNode.OrientationMarkerTypeHuman if on else slicer.vtkMRMLAbstractViewNode.OrientationMarkerTypeNone
            for vn in slicer.util.getNodesByClass("vtkMRMLAbstractViewNode"): vn.SetOrientationMarkerType(t)

    # ---------- 骨窗形状和边界检查 ----------
    def onWinShape(self, i):
        for k in ["WIN_LEN", "WIN_WID", "WIN_ANGLE"]: self.w[k].enabled = i in (1, 2)
        self.w["WIN_CORNER"].enabled = i == 2; self.w["WINDOW_R"].enabled = i == 0

    def onWinPreset(self, i):
        name, shape, prm = WIN_PRESETS[i]
        if shape is None: return
        self.winShape.setCurrentIndex(shape)
        for k, v in prm.items(): self.w[k].value = v

    @staticmethod
    def win_tier(a):
        """按面积给骨窗分档（清醒开颅胶质瘤 + 皮层定位的常见尺寸）"""
        if a < 13: return L("钥匙孔", "keyhole")
        if a < 20: return L("小骨窗", "small tailored window")
        if a <= 50: return L("标准凸面骨瓣", "standard convexity flap")
        if a <= 80: return L("大骨瓣", "large flap")
        return L("超出肿瘤手术常规骨瓣", "beyond a usual tumour flap")

    def win_desc(self):
        """临床说法：约 8 × 6 cm 卵圆骨窗（38 cm²，标准凸面骨瓣），而不是“半径 35 mm”"""
        G = self.G or {}
        sh = G.get("WIN_SHAPE", ["circle", "ellipse", "rect"][self.winShape.currentIndex])
        cm = lambda v: f"{v/10:.1f}".rstrip("0").rstrip(".")
        Lw, Ww, ang = G.get("WIN_LEN", self.val("WIN_LEN")), G.get("WIN_WID", self.val("WIN_WID")), G.get("WIN_ANGLE", self.val("WIN_ANGLE"))
        if sh == "ellipse": t = L(f"约 {cm(Lw)} × {cm(Ww)} cm 卵圆骨窗（长轴 {ang:g}°）", f"oval window about {cm(Lw)} × {cm(Ww)} cm (long axis {ang:g}°)")
        elif sh == "rect": t = L(f"约 {cm(Lw)} × {cm(Ww)} cm 圆角矩形骨窗（长轴 {ang:g}°）", f"rounded-rectangle window about {cm(Lw)} × {cm(Ww)} cm (long axis {ang:g}°)")
        else: t = L(f"直径约 {cm(2*G.get('WINDOW_R', self.val('WINDOW_R')))} cm 圆形骨窗", f"round window about {cm(2*G.get('WINDOW_R', self.val('WINDOW_R')))} cm across")
        if G.get("WIN_CHECK"):
            a = G["WIN_CHECK"]["area_cm2"]; t += L(f"，{a:.0f} cm²，{self.win_tier(a)}", f", {a:.0f} cm², {self.win_tier(a)}")
        return t

    def show_win_check(self):
        c = (self.G or {}).get("WIN_CHECK"); self.win_lines = []
        if not c: self.winNote.text = ""; return
        warn = []
        if c["contra"]: warn.append(L("骨窗边缘跨过中线到了对侧", "Window edge crosses the midline"))
        elif c["mid_mm"] < self.val("MIDLINE_EX"): warn.append(L(f"骨窗边缘离中线只有 {c['mid_mm']:.0f} mm，进入中线禁区，可能伤及上矢状窦和桥静脉",
                                                                    f"Window edge only {c['mid_mm']:.0f} mm from the midline: inside the exclusion zone, risk to the superior sagittal sinus and bridging veins"))
        info = [L(f"骨窗：{self.win_desc()}；边缘离中线最近 {c['mid_mm']:.0f} mm", f"Window: {self.win_desc()}; edge {c['mid_mm']:.0f} mm from the midline at the closest")]
        if c["area_cm2"] > 80: warn.append(L(f"骨窗 {c['area_cm2']:.0f} cm² 超出肿瘤手术常规骨瓣（≤ 80 cm²），接近减压性大骨瓣，请缩小或分期", f"Window {c['area_cm2']:.0f} cm² is beyond a usual tumour flap (≤ 80 cm²), close to a decompressive craniectomy; shrink it or stage the surgery"))
        if ((self.G or {}).get("WIN_SHAPE") or "") == "circle": info.append(L("圆形骨窗相当于小骨窗或钥匙孔，暴露可能不够做皮层定位；凸面肿瘤建议用卵圆骨窗", "A round window behaves like a small or keyhole window and may not expose enough cortex for mapping; an oval window is usual for convexity tumours"))
        info.append(L("骨窗是几何近似：真实骨瓣边缘还有钻孔和锯口；皮肤切口一般比骨瓣长 2–4 cm", "The window is a geometric approximation: real flaps have burr holes and saw cuts; the skin incision is usually 2–4 cm longer than the flap"))
        pin, exp = c.get("proj_in", float("nan")), c.get("expose", float("nan"))
        if pin == pin:
            if pin < 0: warn.append(L(f"肿瘤在皮层的投影伸出骨窗 {-pin:.0f} mm：切除入路可能不足，建议扩大或移动骨窗",
                                      f"The tumour's cortical projection extends {-pin:.0f} mm beyond the window: resection access may be too tight; enlarge or move the window"))
            elif pin < self.val("EXPOSE_MIN") - 1: info.append(L(f"肿瘤投影离骨窗边缘最近 {pin:.0f} mm，少于设定的 {self.val('EXPOSE_MIN'):g} mm",
                                                                 f"Tumour projection comes within {pin:.0f} mm of the window edge (target {self.val('EXPOSE_MIN'):g} mm)"))
        if exp == exp and exp > self.val("EXPOSE_MAX"):
            info.append(L(f"骨窗露出肿瘤投影外最远 {exp:.0f} mm，比定制骨窗常见的 2–3 cm 大",
                          f"The window exposes up to {exp:.0f} mm beyond the tumour projection, more than the 2–3 cm of tailored craniotomies "))
        fi = (self.G or {}).get("WIN_FIT_INFO")
        if fi: info.append(L(f"先评分再定骨窗：{fi['area0']:.0f} → {fi['area']:.0f} cm²（小 {1 - fi['area']/fi['area0']:.0%}），判定段 {fi['full0']} → {fi['full']}",
                             f"Window fitted after scoring: {fi['area0']:.0f} → {fi['area']:.0f} cm² ({1 - fi['area']/fi['area0']:.0%} smaller), decided segments {fi['full0']} → {fi['full']}"))
        if c["base"]: info.append(L("骨窗边缘到了颅底面", "Window edge reaches the skull-base surface"))
        if c["post"]: info.append(L("骨窗边缘到了后下部（横窦附近）", "Window edge reaches the postero-inferior region (near the transverse sinus)"))
        if c["low"]: info.append(L("边缘到了低位外侧（颧弓、耳附近），注意颞肌和面神经分支", "Edge reaches the low lateral region (zygomatic arch, ear): mind the temporalis muscle and facial nerve branches"))
        if not (25 <= c["area_cm2"] <= 80): info.append(L(f"面积 {c['area_cm2']:.0f} cm²，超出常见骨瓣约 25–80 cm² 的范围", f"Area {c['area_cm2']:.0f} cm² is outside the usual 25–80 cm² flap range"))
        self.win_lines = info + [L("⚠ ", "⚠ ") + x for x in warn]
        self.winNote.text = "\n".join(info + [L("⚠ ", "⚠ ") + x for x in warn])
        self.winNote.setStyleSheet(themed("color:#b00020") if warn else "")

    # ---------- 网页版 3D（参考 BrainViz、Mithra）：一个 HTML 文件，浏览器打开就能转着看 ----------
    def onExportWeb(self):
        if self.G is None: slicer.util.errorDisplay(L("先生成方案", "Generate a plan first")); return None
        import numpy as np
        case, work, D = self.case_paths(); layers = []
        def mesh(pd, frac):
            tri = vtk.vtkTriangleFilter(); tri.SetInputData(pd); tri.Update(); dec = vtk.vtkQuadricDecimation(); dec.SetInputData(tri.GetOutput())
            dec.SetTargetReduction(frac); dec.Update(); o = dec.GetOutput()
            from vtk.util import numpy_support as ns
            pts = ns.vtk_to_numpy(o.GetPoints().GetData()).round(1); cells = ns.vtk_to_numpy(o.GetPolys().GetData()).reshape(-1, 4)[:, 1:]
            return pts.ravel().tolist(), cells.ravel().tolist()
        def seg_mesh(name, labels, key, frac):
            sn = next((n for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode") if n.GetName() == name), None)
            if sn is None: return
            sn.CreateClosedSurfaceRepresentation()
            S = sn.GetSegmentation(); spec = next(x for x in STYLES if x[0] == key); col, op, vis = self.style_value(key)
            for i in range(S.GetNumberOfSegments()):
                if labels and not any(S.GetNthSegment(i).GetName().endswith(l) for l in labels): continue
                pd = vtk.vtkPolyData(); sn.GetClosedSurfaceRepresentation(S.GetNthSegmentID(i), pd)
                if pd.GetNumberOfPoints() == 0: continue
                v, f = mesh(pd, frac); layers.append(dict(name=L(spec[1], spec[2]), type="mesh", v=v, f=f, color=col, opacity=op, visible=vis))
        seg_mesh("brain", [], "brain", 0.92); seg_mesh("tumor", ["4", "1", "3"], "core", 0.7); seg_mesh("tumor", ["2"], "flair", 0.85)
        for key, zh, en, kind, match, *_ in STYLES:
            if kind not in ("model", "plan", "multi") or key.startswith("em_"): continue
            col, op, vis = self.style_value(key)
            for nd in self.style_nodes(key):
                pd = nd.GetPolyData()
                if pd is None or pd.GetNumberOfPoints() == 0: continue
                from vtk.util import numpy_support as ns
                P = ns.vtk_to_numpy(pd.GetPoints().GetData())
                if kind == "multi":   # 边界段：每个状态一个图层，颜色取自节点本身（绿 可分离 / 青 仅功能可判 / 黄 仅确认边界 / 红 未判定 / 灰 低风险）
                    nm = nd.GetName()
                    if nm == "Boundary_line": continue
                    lab = {"Boundary_decided": L("边界段：可分离（绿）", "Boundary: separable (green)"), "Boundary_function_only": L("边界段：仅功能可判（青）", "Boundary: function only (teal)"),
                           "Boundary_edge_only": L("边界段：仅确认边界（黄）", "Boundary: edge confirmed only (yellow)"), "Boundary_open": L("边界段：未判定（红）", "Boundary: undecided (red)"),
                           "Boundary_low_risk": L("边界段：低风险（灰）", "Boundary: low risk (grey)")}.get(nm, nm)
                    dn = nd.GetDisplayNode(); c3 = dn.GetColor() if dn else (0.5, 0.5, 0.5)
                    layers.append(dict(name=lab, type="points", v=P.round(1).ravel().tolist(), color=list(c3), opacity=1.0, visible=bool(dn.GetVisibility()) if dn else True, size=4.0))
                    continue
                if key in ("cst", "af"):
                    lines = []; ids = vtk.vtkIdList(); pd.GetLines().InitTraversal()
                    while pd.GetLines().GetNextCell(ids) and len(lines) < 400:
                        q = [ids.GetId(j) for j in range(0, ids.GetNumberOfIds(), 3)]
                        if len(q) > 1: lines.append(P[q].round(1).ravel().tolist())
                    layers.append(dict(name=L(zh, en), type="lines", lines=lines, color=col, opacity=op, visible=vis))
                else:
                    step = max(1, len(P) // 6000)
                    layers.append(dict(name=L(zh, en) + ("" if kind != "plan" else " " + nd.GetName().split("_")[1]), type="points", v=P[::step].round(1).ravel().tolist(),
                                       color=col, opacity=op, visible=vis, size=2.0 if key in ("large", "entry") else 1.2))
        for k, pl in enumerate(self.G["PLAN"], 1):
            c = np.asarray(pl["r"]["L"]).mean(0) + 0.0
            layers.append(dict(name="#%d" % k, type="label", p=c.round(1).tolist(), text=str(k), visible=True))
        c = np.asarray(self.G["SP"]).mean(0).round(1).tolist()
        info = "<br>".join([L(f"UCSF-PDGM-{case} · INBRAIN Planner", f"UCSF-PDGM-{case} · INBRAIN Planner")] + self.key_numbers()[0] + [DISCLAIMER()])
        html = WEB_TEMPLATE.replace("__TITLE__", f"INBRAIN Planner {case}").replace("__INFO__", info).replace("__CENTER__", json.dumps(c)) \
                           .replace("__DATA__", json.dumps(layers, separators=(",", ":"))).replace("__OPACITY__", L("脑表面透明度", "Brain opacity"))
        fn = os.path.join(D, f"{case}_plan_3d_{lang()}.html"); open(fn, "w", encoding="utf-8").write(html)
        fn = self.pub(fn)
        self.say(L("网页版 3D 已导出（浏览器打开）：", "Web 3D exported (open in a browser):"), fn, f"{os.path.getsize(fn)/1e6:.1f} MB"); return fn

    # ---------- 检查清单：把各处的警告集中到一处（绿 = 正常，黄 = 注意，红 = 要处理） ----------
    def checks(self):
        import numpy as np
        G = self.G; out = []
        rs = self.reg_status()
        out.append(("ok" if rs.startswith("pass") else ("bad" if rs.startswith("fail") else "warn"),
                    L("配准检查：", "Registration check: ") + ((L("通过", "OK") + rs[4:].split(" 20")[0]) if rs.startswith("pass") else ((L("不通过", "failed") + rs[4:].split(" 20")[0] + L("，在快速开始里点“看配准图”确认，或重做预处理", "; use “Show overlay” in Quick start or preprocess again")) if rs else L("未进行（点“一键规划”会自动判定）", "not done (“Plan in one click” checks it automatically)")))))
        nl = {n.GetName()[6:]: (n.GetPolyData().GetNumberOfLines() if n.GetPolyData() else 0) for n in slicer.util.getNodesByClass("vtkMRMLModelNode") if n.GetName().startswith("tract_")}
        out.append(("bad" if not nl or min(nl.values()) == 0 else "ok", L("纤维束：", "Tracts: ") + (", ".join(f"{k} {v}" for k, v in sorted(nl.items())) or "0")))
        dx = getattr(self.logic, "side_dx", None)
        if self.side.currentIndex == 0 and dx is not None:
            out.append(("warn" if dx < 10 else "ok", L(f"侧别（自动）：核心离中线 {dx:.0f} mm", f"Side (auto): core {dx:.0f} mm from the midline") + (L("，请手动确认", ", please confirm manually") if dx < 10 else "")))
        ei = int(np.argmin(np.linalg.norm(G["SP"] - np.asarray(G["entry"]), axis=1)))
        if G["on_core"][ei]: out.append(("warn", L("入口在肿瘤核心正上方（浅表肿瘤常见；核心表面已不放阵列）", "Entry lies over the tumour core (common for superficial tumours; arrays avoid the core surface)")))
        try:   # 刺激电流和单触点电荷安全线（k = 1.5，每相 0.5 ms）比较
            d_mm = float(self.val("CONTACT_D")); A = np.pi*(d_mm/20.0)**2; i_safe = (A*10**1.5)**0.5/0.5   # mA
            n_need = int(np.ceil(self.val("STIM_I")/max(i_safe, 1e-9)))
            if self.val("STIM_I") > i_safe:
                out.append(("warn", L(f"刺激电流 {self.val('STIM_I'):g} mA 超过 Ø{d_mm:g} mm 单触点的电荷安全线（约 {i_safe:.1f} mA，每相 0.5 ms）：需 {n_need} 个大触点并联分担，或缩短脉宽",
                                      f"Stimulation {self.val('STIM_I'):g} mA exceeds the charge safety line of one Ø{d_mm:g} mm contact (about {i_safe:.1f} mA, 0.5 ms per phase): share it over {n_need} large contacts or shorten the pulse")))
        except Exception as e: self.say("stim safety:", e)
        B = G.get("BND") or {}
        if B.get("n_req"):
            lv = "ok" if B["full"] >= B["n_arr"] else "warn"
            out.append((lv, L(f"切除边界：靠功能区 {B['n_req']} 段，完整判定 {B['full']} 段", f"Resection boundary: {B['n_req']} segments near function, {B['full']} fully decided")
                        + (L(f"，{B['unreach']} 段超出阵列可达范围", f", {B['unreach']} out of reach") if B.get("unreach") else "")
                        + (L("；没判定完的段见结果区的“下一步”表", "; see the next-step table in Results for the rest") if B["full"] < B["n_req"] else "")))
        else:
            out.append(("info", L("切除边界：附近没有功能区，可按影像切除", "Resection boundary: no functional area nearby, follow imaging")))
        z = (B or {}).get("zones")
        if z:
            out.append(("ok" if z[3] > 0 else "warn", L(f"触点分区（病灶/近瘤周/远瘤周/健康）：{z[0]}/{z[1]}/{z[2]}/{z[3]}", f"Contact zones (lesion/close/far/healthy): {z[0]}/{z[1]}/{z[2]}/{z[3]}")
                        + ("" if z[3] > 0 else L("；没有健康参照触点，ECoG 特征无法做病人内对照", "; no healthy reference contact for within-patient ECoG comparison"))))
        hi = G.get("HEALTHY_INFO")
        if hi: out.append(("ok" if hi["n_healthy"] >= 3 else "warn", L(f"健康参照：加了一片只记录的参照片，{hi['n_healthy']} 个大触点离 FLAIR > 30 mm，中位 {hi['median_mm']:.0f} mm",
                                                                    f"Healthy reference: one record-only array added, {hi['n_healthy']} large contacts > 30 mm from FLAIR, median {hi['median_mm']:.0f} mm")
                         + ("" if hi["n_healthy"] >= 3 else L("；骨窗内没有真正的健康区，这片只是离病灶最远的位置", "; no truly healthy cortex in reach, this is the farthest position"))))
        if G.get("BUDGET"):
            out.append(("info", L(f"固定片数模式：只放 {G['BUDGET']} 次，判定的段是这几片能做到的最多", f"Fixed-count mode: {G['BUDGET']} placements, deciding as many segments as these can")))
        if G.get("vein_tree") is not None:
            vv = int(G.get("VEIN_VIOL", 0))
            out.append(("warn" if vv else "ok", L(f"阵列与静脉：安全距离 {G['VEIN_SAFE']:g} mm 内的触点 {vv} 个", f"Arrays vs veins: {vv} contacts within the {G['VEIN_SAFE']:g} mm margin")))
        ms = float(G.get("MAX_STRAIN_PLAN", 0))
        out.append(("warn" if ms > 0.15 else "ok", L(f"阵列贴合：触点间距最大形变 {ms:.0%}", f"Array conformity: max contact-spacing strain {ms:.0%}")))
        c = G.get("WIN_CHECK")
        if c:
            bad = c["contra"] or c["mid_mm"] < self.val("MIDLINE_EX")
            out.append(("bad" if bad else "ok", L(f"骨窗：边缘离中线 {c['mid_mm']:.0f} mm，面积 {c['area_cm2']:.0f} cm²", f"Window: edge {c['mid_mm']:.0f} mm from the midline, area {c['area_cm2']:.0f} cm²") + (L("，进入中线禁区", ", inside the midline exclusion zone") if bad else "")))
        aw, win = G["TIME"]["scen"]["MAIN"]["awake"], self.val("AWAKE_WINDOW")
        out.append(("bad" if aw > win else ("warn" if aw > 0.8*win else "ok"), L(f"清醒期：{aw:.0f} / {win:.0f} min", f"Awake phase: {aw:.0f} / {win:.0f} min")))
        if getattr(self.logic, "atlas", None) is None: out.append(("info", L("脑区图谱：未进行（可选，⑨）", "Brain atlas: not done (optional, ⑨)")))
        return out

    WHY_KIND = {"hidden": ("骨窗视野外", "outside the window view"), "unreach": ("超出可达范围", "out of reach"), "edge": ("仅确认边界", "edge only"), "budget": ("放置次数已满", "placement limit reached"),
                "vein": ("因静脉未放置", "not placed due to veins"), "blocked": ("无合格放置", "no valid placement"), "grad": ("缺记录梯度", "no recording gradient"), "nofit": ("无合适方向", "no suitable orientation")}

    def why_rows(self):
        G = self.G or {}; out = []
        for w in G.get("SEG_WHY", []):
            k = self.WHY_KIND.get(w["kind"], (w["kind"], w["kind"]))
            out.append([w["seg"] + 1, w["src"], L(*k), L(w["zh"], w["en"])])
        return out

    def show_why(self):
        rows = self.why_rows(); B = (self.G or {}).get("BND") or {}
        if not B.get("n_req"): self.whyLabel.text = ""; self.whyTable.setRowCount(0); self.whyTable.visible = False; return
        cnt = B.get("why") or {}
        parts = "，".join(f"{L(*self.WHY_KIND[k])} {v}" for k, v in cnt.items() if k in self.WHY_KIND) if lang() == "zh" else \
                ", ".join(f"{L(*self.WHY_KIND[k])} {v}" for k, v in cnt.items() if k in self.WHY_KIND)
        self.whyLabel.text = (L(f"<b>没判定完的段：{len(rows)} / {B['n_req']}</b>（{parts}）", f"<b>Segments not fully decided: {len(rows)} / {B['n_req']}</b> ({parts})")
                              if rows else L("<b>靠功能区的段都已完整判定</b>", "<b>All segments near function are fully decided</b>"))
        self.whyTable.visible = bool(rows); self.whyTable.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate(r): self.whyTable.setItem(i, j, qt.QTableWidgetItem(str(v)))
        self.whyTable.resizeColumnsToContents(); self.whyTable.horizontalHeader().setStretchLastSection(True)

    def onWhySelect(self):
        try:
            import numpy as np
            i = self.whyTable.currentRow(); w = self.G["SEG_WHY"][i]; p = np.asarray(w["pos"])
            w3 = slicer.app.layoutManager().threeDWidget(0); cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(w3.mrmlViewNode())
            c = self.G["SP"].mean(0); n = p - c; n /= np.linalg.norm(n)
            cam.SetFocalPoint(*p); cam.SetPosition(*(p + n*220)); cam.SetViewUp(0, 0, 1)
            w3.threeDView().renderWindow().GetRenderers().GetFirstRenderer().ResetCameraClippingRange(); w3.threeDView().forceRender()
        except Exception as e: self.say("why:", e)

    def show_checks(self):
        try: items = self.checks()
        except Exception as e: self.say("checks:", e); return
        col = {k: themed(v) for k, v in {"ok": "#1b7f3b", "warn": "#b26a00", "bad": "#b00020", "info": "#666666"}.items()}
        mark = {"ok": "✓", "warn": "!", "bad": "✗", "info": "·"}
        self.check_items = items
        self.checkNote.text = f"<b>{L('检查', 'Checks')}</b><br>" + "<br>".join(f"<span style='color:{col[l]}'>{mark[l]} {t}</span>" for l, t in items)
        self.checkNote.visible = True

    def entry_desc(self):
        return [("自动推荐", "recommended"), ("离核心最近", "closest to core"), ("手动", "manual"), ("以肿瘤投影为中心", "centred on tumour")][self.entryMode.currentIndex]

    def onRecenter(self):
        self.fit_slices(); self.fit_3d()

    def onLayout(self, i):
        Lo = slicer.vtkMRMLLayoutNode
        if i == 1: self.planner_layout(); return
        slicer.app.layoutManager().setLayout([Lo.SlicerLayoutOneUp3DView, None, Lo.SlicerLayoutFourUpView, Lo.SlicerLayoutOneUpRedSliceView][i])

    # ---------- 默认布局：上面 3D，下面三个 MRI 并排；每个视图都缩放到刚好装下大脑 ----------
    LAYOUT_ID = 5601

    def planner_layout(self, fit3d=True):
        lm = slicer.app.layoutManager(); vp = lm.viewport()
        W, H = max(int(vp.width), 600), max(int(vp.height), 400)
        bottom = int(min(W/3.0, H*0.55)*0.75); top = max(H - bottom, 150)      # 下面一排矮一点；切片按高度装下整个大脑，左右留黑边
        def sv(tag, ori, col):
            return (f'<item><view class="vtkMRMLSliceNode" singletontag="{tag}"><property name="orientation" action="default">{ori}</property>'
                    f'<property name="viewlabel" action="default">{tag[0]}</property><property name="viewcolor" action="default">{col}</property></view></item>')
        xml = ('<layout type="vertical" split="true">'
               f'<item splitSize="{top}"><view class="vtkMRMLViewNode" singletontag="1"><property name="viewlabel" action="default">1</property></view></item>'
               f'<item splitSize="{bottom}"><layout type="horizontal" split="true">'
               + sv("Red", "Axial", "#F34A33") + sv("Yellow", "Sagittal", "#EDD54C") + sv("Green", "Coronal", "#6EB04B") +
               '</layout></item></layout>')
        ln = lm.layoutLogic().GetLayoutNode()
        if ln.IsLayoutDescription(self.LAYOUT_ID): ln.SetLayoutDescription(self.LAYOUT_ID, xml)
        else: ln.AddLayoutDescription(self.LAYOUT_ID, xml)
        lm.setLayout(self.LAYOUT_ID); slicer.app.processEvents()
        self.fit_slices()
        if fit3d: self.fit_3d()

    def brain_box(self):
        """脑分割的 RAS 包围盒（min, max）；没有就用背景体积"""
        import numpy as np
        nds = [n for n in slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode") if n.GetName().endswith("brain_segmentation")]
        if not nds: return None
        nd = nds[0]; key = (nd.GetID(), nd.GetMTime())
        if getattr(self, "_bbox_key", None) == key: return self._bbox
        kji = np.argwhere(slicer.util.arrayFromVolume(nd) > 0)
        if not len(kji): return None
        lo, hi = kji.min(0)[::-1], kji.max(0)[::-1]
        m = vtk.vtkMatrix4x4(); nd.GetIJKToRASMatrix(m); M = slicer.util.arrayFromVTKMatrix(m)
        corners = np.array([[x, y, z, 1] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ M.T
        self._bbox_key = key; self._bbox = (corners[:, :3].min(0), corners[:, :3].max(0)); return self._bbox

    def fit_slices(self):
        import numpy as np
        lm = slicer.app.layoutManager(); bb = self.brain_box()
        for nm in ["Red", "Yellow", "Green"]:
            w = lm.sliceWidget(nm)
            if w is None: continue
            w.sliceLogic().FitSliceToAll()
            if bb is None: continue
            sn = w.mrmlSliceNode(); lo, hi = bb; c = (lo + hi)/2; ext = hi - lo
            ax = {"Red": (0, 1), "Yellow": (1, 2), "Green": (0, 2)}[nm]
            dims = sn.GetDimensions(); asp = dims[1]/max(dims[0], 1)
            fx = max(ext[ax[0]], ext[ax[1]]/max(asp, 1e-3))*1.06
            sn.SetFieldOfView(fx, fx*asp, sn.GetFieldOfView()[2])
            sn.JumpSliceByCentering(*c)

    def fit_3d(self):
        """保持当前视角方向，按大脑包围盒（加颅骨厚度）算相机距离，刚好装下大脑"""
        import numpy as np, math
        w3 = slicer.app.layoutManager().threeDWidget(0); v = w3.threeDView()
        bb = self.brain_box()
        if bb is None: v.resetFocalPoint(); return
        lo, hi = bb; c = (lo + hi)/2; rad = 0.5*float(np.linalg.norm(hi - lo)) + 12.0
        cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(w3.mrmlViewNode()).GetCamera()
        d = np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint()); d = d/np.linalg.norm(d) if np.linalg.norm(d) > 0 else np.array([1.0, 0, 0])
        asp = max(v.width, 1)/max(v.height, 1); half = math.radians(cam.GetViewAngle()/2)
        half = min(half, math.atan(math.tan(half)*asp))            # 视图窄的一边决定距离
        cam.SetFocalPoint(*c); cam.SetPosition(*(c + d*rad/math.sin(half)*0.92))
        v.renderWindow().GetRenderers().GetFirstRenderer().ResetCameraClippingRange(); v.forceRender()

    @staticmethod
    def seg_cell(r):
        a, b = len(r.get("seg_new_full", ())), len(r.get("seg_new_edge", ()))
        return f"{a}" + (f" (+{b})" if b else "")

    # ---------- INBRAIN 价值摘要 ----------
    def value_items(self):
        """(标题, INBRAIN, 传统, 说明) 列表"""
        G = self.G; sc = G["TIME"]["scen"]; c = G["TIME"]["counts"]; cov = self.logic.coverage(G)
        a_i, a_s = sc["MAIN"]["awake"], sc["STD"]["awake"]; win = self.val("AWAKE_WINDOW")
        st_i = sc["MAIN"].get("stim", 0.0); st_s = sc["STD"].get("stim", 0.0)
        nch = len(G["PLAN"][0]["r"]["L"]) + len(G["PLAN"][0]["r"]["S"]) if G["PLAN"] else 0
        items = [(L("清醒期时长", "Awake phase"), f"{a_i:.0f} min", f"{a_s:.0f} min",
                  (L(f"缩短 {a_s - a_i:.0f} min（{(a_s - a_i)/max(a_s, 1e-9):.0%}），占清醒窗口 {a_i/win:.0%}", f"{a_s - a_i:.0f} min shorter ({(a_s - a_i)/max(a_s, 1e-9):.0%}), {a_i/win:.0%} of awake window") if a_s >= a_i else
                   L(f"多 {a_i - a_s:.0f} min，但判定的边界段更多；占清醒窗口 {a_i/win:.0%}", f"{a_i - a_s:.0f} min longer but more boundary decided; {a_i/win:.0%} of awake window"))),
                 (L("清醒期需刺激位点", "Sites stimulated awake"), f"{st_i:.1f}", f"{st_s:.1f}",
                  (L("麻醉期 CCEP + 被动高 γ 双重筛选，清醒期只刺激两样都阳性的触点", "Asleep CCEP + passive high gamma screen; only contacts positive on both are stimulated awake ")
                   if self.passiveAsleep.checked else L("麻醉期 CCEP 和任务记录先筛选，清醒期只刺激阳性触点", "Asleep CCEP and task recording screen first; only positive contacts are stimulated awake"))),
                ]
        B = G.get("BND")
        if B and B["n_req"]:
            cm = B["seg_len"]/10.0
            items[:0] = [
                (L("可区分肿瘤与功能组织的边界段", "Segments separating tumour from functional tissue"), f"{B.get('sep', 0)} / {B['n_req']}", f"{B.get('strip_sep', 0)} / {B['n_req']}",
                 L("刺激两点（边界上、边界外）判定功能，并有跨边界的记录梯度（病灶内到边界外 15 mm）区分浸润组织和正常皮层",
                   "stimulation at two sites (on and outside the boundary) decides function, and a recording gradient across the boundary (inside to 15 mm outside) separates infiltrated from normal cortex")),
                (L("靠功能区的边界有结论", "Boundary near function decided"), f"{B['full']} / {B['n_req']}", f"{B.get('strip_full', B['n_probe'])} / {B['n_req']}",
                 L(f"边界每 {B['seg_len']:g} mm 一段；传统列是 1×{B.get('strip_n', 4)} 条带按同一流程放 {B.get('strip_placements', 0)} 次（INBRAIN {len(G['PLAN'])} 次）",
                   f"one segment per {B['seg_len']:g} mm; conventional = 1×{B.get('strip_n', 4)} strips, same workflow, {B.get('strip_placements', 0)} placements (INBRAIN {len(G['PLAN'])})")),
                (L(f"可评估扩大切除 {B['supra']:g} mm 的边界", f"Boundary checked for +{B['supra']:g} mm"), f"{B['full']*cm:.0f} cm", f"{B.get('strip_full', B['n_probe'])*cm:.0f} cm",
                 L("这些段的两处刺激均为阴性时，可在保留功能的前提下扩大切除；切除范围扩大与生存期延长相关",
                   "where both sites are negative, the resection can be extended while preserving function; a larger extent of resection is associated with longer survival")),
                (L("每段瘤周 15 mm 内的采样点", "Samples per segment within 15 mm of the border"), f"{B.get('radial_inb', 0):.1f}", f"{B.get('radial_strip', 2):.0f}",
                 L("麻醉期被动记录可比较病灶、瘤周与健康皮层的 ECoG（δ 功率升高、β 功率降低、频谱斜率变化），用于评估 MRI 未显示的浸润；传统条带触点间距为 10 mm",
                   "passive asleep recording compares ECoG over lesion, peritumoral and healthy cortex (delta up, beta down, spectral slope) to estimate infiltration MRI misses; conventional strips have 10 mm spacing"))]
        if B and B.get("sep"):
            items.insert(1, (L("边界定位精度（半个记录间距）", "Boundary localisation (half recording pitch)"), f"±{B['loc_inb']:.1f} mm", f"±{B['loc_std']:.0f} mm",
                             L(f"同样判定为可分离的段，按精度差少留安全带，合计约 {B['margin_cm2']:.1f} cm² 皮层可纳入切除评估",
                               f"for segments judged separable, the finer pitch needs a narrower safety margin: about {B['margin_cm2']:.1f} cm² of cortex can enter the resection assessment")))
        N = (B or {}).get("nce") if B else None
        if N and N.get("total"):
            items.insert(2, (L(f"非强化（FLAIR）残留估计（阈值 {N['thr']:g} mL）", f"Residual non-enhancing (FLAIR) tumour, est. (threshold {N['thr']:g} mL)"), f"{N['res_inb']:.1f} mL", f"{N['res_std']:.1f} mL",
                             L(f"FLAIR 区共 {N['total']:.1f} mL；可分离段或低风险段旁的 FLAIR 组织计为可切，靠功能区且未分离的段保留。残留 ≤ {N['thr']:g} mL 与更长生存相关（65 岁以下）",
                               f"FLAIR total {N['total']:.1f} mL; FLAIR next to separable or low-risk segments counts as resectable, next to unseparated segments near function it stays. Residual ≤ {N['thr']:g} mL is associated with longer survival (age < 65)")))
        if self.shift_rows:
            keys = list(G["KEYS"]); w = {k: min(cc[k] for _, cc in self.shift_rows[1:]) for k in keys}
            items.append((L("脑移位后参考目标覆盖（最差）", "Reference-target coverage after brain shift (worst)"), " / ".join(f"{k} {w[k]:.0%}" for k in keys), "—",
                          L(f"下沉 {self.val('SHIFT_SINK'):g} mm + 侧向 {self.val('SHIFT_TAN'):g} mm", f"sinking {self.val('SHIFT_SINK'):g} mm + lateral {self.val('SHIFT_TAN'):g} mm")))
        return items

    def show_value(self):
        if self.G is None: return
        rows = []
        for i, (t, a, b, n) in enumerate(self.value_items()):
            bg = " bgcolor='#f8fcfa'" if i % 2 else ""
            rows.append(
                f"<tr{bg}><td colspan='2' style='padding:5px 8px 0 0'><b>{t}</b></td>"
                f"<td align='right' width='88' style='padding:5px 8px 0 8px;color:#0f6b52'><b>{a}</b></td>"
                f"<td align='right' width='60' style='padding:5px 0 0 0;color:#8a9491'>{b}</td></tr>"
                f"<tr{bg}><td colspan='4' style='padding:1px 0 4px 0;color:#6d7873;font-size:10px'>{n}</td></tr>")
        self.value.text = (
            f"<div style='font-size:13px;font-weight:600;color:#123f33'>{L('INBRAIN 方案要点', 'INBRAIN plan highlights')}</div>"
            f"<table width='100%' cellspacing='0' cellpadding='0'>"
            f"<tr><td colspan='2' style='padding:6px 0 2px 0'></td>"
            f"<td align='right' style='padding:6px 8px 2px 8px;color:#66736e;font-size:10px'><b>INBRAIN</b></td>"
            f"<td align='right' style='padding:6px 0 2px 0;color:#8a9491;font-size:10px'>{L('传统流程', 'Conventional')}</td></tr>"
            + "".join(rows) + "</table>")
        self.value.text = themed(self.value.text)
        self.value.visible = True
        try: qt.QTimer.singleShot(0, self._fit_card)
        except Exception: pass

    def _fit_card(self):
        """富文本自动换行时 QLabel 不会自己长高，按当前宽度补一次最小高度"""
        try:
            h = self.value.heightForWidth(max(self.value.width, 200))
            if h and h > 0: self.value.setMinimumHeight(h + 4)
        except Exception: pass

    # ---------- 放置顺序和路径 ----------
    def draw_order(self):
        """每一片中心（往外抬 4 mm）标编号，按顺序连线"""
        import numpy as np
        G = self.G; plan = G["PLAN"]
        if not plan: return
        pts = []
        for p in plan:
            _, i = G["stree"].query(p["r"]["L"].mean(0)); pts.append(G["SP"][i] + G["SN"][i]*4.0)
        f = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Order_labels")
        for k, q in enumerate(pts, 1): f.AddControlPoint(vtk.vtkVector3d(*[float(x) for x in q]), str(k))
        f.SetLocked(True); dn = f.GetDisplayNode()
        dn.SetTextScale(5.0); dn.SetGlyphScale(2.5); dn.SetPropertiesLabelVisibility(False); dn.SetPointLabelsVisibility(True)
        if len(pts) > 1:
            c = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsCurveNode", "Order_path"); c.SetCurveTypeToLinear()
            for q in pts: c.AddControlPoint(vtk.vtkVector3d(*[float(x) for x in q]))
            c.SetLocked(True); cd = c.GetDisplayNode()
            cd.SetPropertiesLabelVisibility(False); cd.SetPointLabelsVisibility(False); cd.SetGlyphScale(0.5); cd.SetLineThickness(0.4)
        self.path_mm = float(sum(np.linalg.norm(np.diff(np.array(pts), axis=0), axis=1))) if len(pts) > 1 else 0.0

    def onStep(self, d):
        n = self.planTable.rowCount
        if not n: return
        rows = sorted(set(i.row() for i in self.planTable.selectedIndexes()))
        k = (rows[0] + d) if rows else (0 if d > 0 else n - 1)
        self.planTable.selectRow(max(0, min(n - 1, k)))

    # ---------- 成本 ----------
    def cost_rows(self):
        if self.G is None: return None
        sc = self.G["TIME"]["scen"]; v = self.val
        dev = {"MAIN": v("N_ARRAY")*v("PRICE_INBRAIN"), "STD": (v("N_STRIP") + (1 if self.adStrip.checked else 0))*v("PRICE_STRIP")}
        out = []
        for key, lab in SCEN_NAMES:
            t = sc[key]["total"]*v("OR_COST") + sc[key]["awake"]*v("AWAKE_EXTRA")
            out.append((key, lab, t, dev[key], t + dev[key]))
        return out

    @staticmethod
    def fit_table(t):
        """表格高度刚好装下表头和所有行，不留空白"""
        t.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        hh = t.horizontalHeader(); hh.setSectionResizeMode(0, qt.QHeaderView.Stretch)
        for k in range(1, t.columnCount): hh.setSectionResizeMode(k, qt.QHeaderView.ResizeToContents)
        t.verticalHeader().setVisible(False); t.resizeRowsToContents()
        h = t.horizontalHeader().height + sum(t.rowHeight(i) for i in range(t.rowCount)) + 2*t.frameWidth + 2
        t.setMinimumHeight(h); t.setMaximumHeight(h); t.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)

    def show_cost(self):
        rows = self.cost_rows()
        if rows is None: return
        tr_ = globals()["T"]; self.costTable.setRowCount(len(rows))
        for k, (key, lab, t, d, tot) in enumerate(rows):
            for j, x in enumerate([tr_(lab), f"{t:,.0f}", f"{d:,.0f}", f"{tot:,.0f}"]): self.costTable.setItem(k, j, qt.QTableWidgetItem(x))
        self.costTable.resizeColumnsToContents(); self.fit_table(self.costTable)
        r = {k: (t, d, tot) for k, _, t, d, tot in rows}
        diff = r["STD"][2] - r["MAIN"][2]; tdiff = r["STD"][0] - r["MAIN"][0]
        be = (r["STD"][2] - r["MAIN"][0]) / max(self.val("N_ARRAY"), 1)
        self.cost_summary = (diff, tdiff, be)
        aw = self.G["TIME"]["scen"]["STD"]["awake"] - self.G["TIME"]["scen"]["MAIN"]["awake"]
        self.costNote.text = L(f"每例差价（INBRAIN − 传统）：{-diff:+,.0f} €，其中手术室时间 {-tdiff:+,.0f} €、器件 {r['MAIN'][1] - r['STD'][1]:+,.0f} €；清醒期缩短 {aw:.0f} min。"
                               + (f"阵列单价 ≤ {be:,.0f} € 时每例总成本持平或更低。" if be > 0 else ""),
                               f"Per-case difference (INBRAIN − conventional): {-diff:+,.0f} € (OR time {-tdiff:+,.0f} €, device {r['MAIN'][1] - r['STD'][1]:+,.0f} €); awake phase {aw:.0f} min shorter. "
                               + (f"Break-even array price: {be:,.0f} €." if be > 0 else ""))

    # ---------- 脑移位 ----------
    def lesion_volumes(self):
        """切除核心（强化 + 坏死）和 FLAIR 水肿带体积 ml"""
        import numpy as np
        nd = self.G.get("tumor"); a = slicer.util.arrayFromVolume(nd); sp = np.prod(nd.GetSpacing()) / 1000.0
        core = float(np.isin(np.rint(a), [1, 3, 4]).sum()*sp); edema = float((np.rint(a) == 2).sum()*sp)
        return core, edema

    def onShift(self):
        if self.G is None: slicer.util.errorDisplay(L("先生成方案", "Run the optimisation first")); return
        self.shift_basis = ""
        if self.autoShift.checked:
            try:
                core, edema = self.lesion_volumes()
                sink = next(s for lim, s in SHIFT_BY_VOL if core < lim) + (2.0 if edema > core else 0.0)
                self.w["SHIFT_SINK"].value = sink; self.w["SHIFT_TAN"].value = round(sink*0.4*2)/2
                self.shift_basis = L(f"核心 {core:.0f} ml、水肿 {edema:.0f} ml → 下沉 {sink:g} mm{'（水肿大于核心 +2 mm）' if edema > core else ''}，侧向 {self.val('SHIFT_TAN'):g} mm。",
                                     f"Core {core:.0f} ml, oedema {edema:.0f} ml → sinking {sink:g} mm{' (oedema > core, +2 mm)' if edema > core else ''}, lateral {self.val('SHIFT_TAN'):g} mm. ")
            except Exception as e: self.say("volume:", e)
        try:
            rows = self.logic.shift_sim(self.G, self.val("SHIFT_SINK"), self.val("SHIFT_TAN"))
        except Exception as e:
            import traceback; self.say(traceback.format_exc()); slicer.util.errorDisplay(str(e)); return
        self.shift_rows = rows; keys = list(self.G["KEYS"])
        self.shiftTable.setColumnCount(len(keys) + 2)
        self.shiftTable.setHorizontalHeaderLabels([T("情况")] + [L(f"{k} 刺激", f"{k} stim") for k in keys] + [T("记录区覆盖")])
        self.shiftTable.setRowCount(len(rows))
        for i, (name, c) in enumerate(rows):
            for j, x in enumerate([name] + [f"{c[k]:.0%}" for k in keys] + [f"{c['rec']:.0%}"]): self.shiftTable.setItem(i, j, qt.QTableWidgetItem(x))
        self.shiftTable.resizeColumnsToContents()
        base = rows[0][1]; worst = {k: min(c[k] for _, c in rows[1:]) for k in keys + ["rec"]}
        self.shiftNote.text = self.shift_basis + L("最差方向：" + "，".join(f"{k} 刺激 {base[k]:.0%} → {worst[k]:.0%}" for k in keys) + f"，记录 {base['rec']:.0%} → {worst['rec']:.0%}。"
                                "模型：电极保持术前位置，皮层随脑移位移动。术中可用阵列记录结果或重新配准校正。",
                                "Worst direction: " + ", ".join(f"{k} stim {base[k]:.0%} → {worst[k]:.0%}" for k in keys) + f", recording {base['rec']:.0%} → {worst['rec']:.0%}. "
                                "Model: electrodes keep their pre-operative position while the cortex shifts. Intra-operative recordings or re-registration can correct it.")
        self.say(self.shiftNote.text); self.show_value()

    # ---------- 导出汇报图 ----------
    def layer_present(self, key):
        spec = next(s for s in STYLES if s[0] == key)
        if not self.style_value(key)[2]: return False
        if spec[3] == "seg":
            return any(sn.GetName() == spec[4][0] for sn in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"))
        return bool(self.style_nodes(key))

    def key_numbers(self):
        G = self.G; sc = G["TIME"]["scen"]; cov = self.logic.coverage(G)
        lines = [L(f"放置 {len(G['PLAN'])} 次，", f"{len(G['PLAN'])} placements, ") + self.win_desc(),
                 L(f"靠功能区的边界：完整判定 {(G.get('BND') or {}).get('full', 0)} / {(G.get('BND') or {}).get('n_req', 0)} 段", f"Boundary near function: {(G.get('BND') or {}).get('full', 0)} / {(G.get('BND') or {}).get('n_req', 0)} segments decided"),
                 L(f"清醒期：INBRAIN {sc['MAIN']['awake']:.0f} min", f"Awake: INBRAIN {sc['MAIN']['awake']:.0f} min"),
                 L(f"　　　　传统流程 {sc['STD']['awake']:.0f} min", f"   conventional {sc['STD']['awake']:.0f} min")]
        if getattr(self, "cost_summary", None):
            lines.append(L(f"清醒期缩短 {sc['STD']['awake'] - sc['MAIN']['awake']:.0f} min", f"Awake phase {sc['STD']['awake'] - sc['MAIN']['awake']:.0f} min shorter"))
        return lines, cov

    def onExportFigure(self):
        if self.G is None: slicer.util.errorDisplay(L("先生成方案", "Run the optimisation first")); return None
        try:
            import ScreenCapture, numpy as np
            case, work, D = self.case_paths()
            lm = slicer.app.layoutManager(); view = lm.threeDWidget(0).threeDView(); view.forceRender()
            raw = os.path.join(D, f"{case}_3d_raw.png")
            vn = lm.threeDWidget(0).mrmlViewNode(); ax = vn.GetAxisLabelsVisible(); vn.SetAxisLabelsVisible(False); view.forceRender()
            ScreenCapture.ScreenCaptureLogic().captureImageFromView(view, raw)
            vn.SetAxisLabelsVisible(ax)
            im = qt.QImage(raw); W, H = im.width(), im.height()
            fs = max(14, H // 42); pw = max(int(W*0.45), fs*24)
            out = qt.QImage(W + pw, H, qt.QImage.Format_RGB32); out.fill(qt.QColor(255, 255, 255))
            p = qt.QPainter(out); p.setRenderHint(qt.QPainter.Antialiasing); p.drawImage(0, 0, im)
            font = qt.QFont("Helvetica"); font.setPixelSize(fs); bold = qt.QFont("Helvetica"); bold.setPixelSize(int(fs*1.25)); bold.setBold(True)
            x0, y = W + fs, int(fs*2)
            p.setFont(bold); p.setPen(qt.QColor(20, 20, 20))
            ttl = f"UCSF-PDGM-{case} · {self.preset.currentText.split('（')[0].split(' (')[0]}"
            while qt.QFontMetrics(bold).width(ttl) > pw - 2*fs and bold.pixelSize() > fs*0.8: bold.setPixelSize(bold.pixelSize() - 1); p.setFont(bold)
            p.drawText(x0, y, ttl); y += int(fs*2)
            p.setFont(font)
            for key, zh, en, *_ in STYLES:
                if key.startswith("em_") or not self.layer_present(key): continue
                col, op, _ = self.style_value(key)
                p.setBrush(qt.QBrush(qt.QColor.fromRgbF(*col))); p.setPen(qt.QColor(90, 90, 90))
                p.drawEllipse(x0, y - int(fs*0.8), int(fs*0.9), int(fs*0.9))
                p.setPen(qt.QColor(20, 20, 20)); p.drawText(x0 + int(fs*1.5), y, zh if lang() == "zh" else en); y += int(fs*1.45)
            y += fs; p.setPen(qt.QPen(qt.QColor(180, 180, 180))); p.drawLine(x0, y - fs, W + pw - fs, y - fs)
            p.setPen(qt.QColor(20, 20, 20))
            for ln in self.key_numbers()[0]: p.drawText(x0, y, ln); y += int(fs*1.45)
            y += int(fs*0.5); small = qt.QFont("Helvetica"); small.setPixelSize(int(fs*0.75)); p.setFont(small); p.setPen(qt.QColor(110, 110, 110))
            p.drawText(x0, y, DISCLAIMER())
            try:   # 比例尺：按入口处的深度算
                cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(lm.threeDWidget(0).mrmlViewNode()).GetCamera()
                dist = np.linalg.norm(np.array(cam.GetPosition()) - np.asarray(self.G["entry"]))
                px_mm = H / (2*dist*np.tan(np.radians(cam.GetViewAngle()/2)))
                bar = int(20*px_mm); bx, by = int(fs*1.5), H - int(fs*1.5)
                p.setPen(qt.QPen(qt.QColor(20, 20, 20), max(3, fs//5))); p.drawLine(bx, by, bx + bar, by)
                p.setFont(font); p.setPen(qt.QColor(20, 20, 20)); p.drawText(bx, by - int(fs*0.5), L("20 mm（入口处）", "20 mm (at entry)"))
            except Exception as e: self.say("scale bar:", e)
            p.end()
            fn = os.path.join(D, f"{case}_figure_{lang()}.png"); out.save(fn)
            try: os.remove(raw)
            except OSError: pass
            fn = self.pub(fn); self.say(L("汇报图已导出：", "Figure exported:"), fn); return fn
        except Exception as e:
            import traceback; self.say(traceback.format_exc()); slicer.util.errorDisplay(str(e)); return None

    # ---------- 合并图：图像组（多个 3D 视角）和数据组（对比柱状图），各导出一张 ----------
    def _combo_header(self, p, W, fs, title, sub=""):
        bold = qt.QFont("Helvetica"); bold.setPixelSize(int(fs*1.5)); bold.setBold(True)
        p.setFont(bold); p.setPen(qt.QColor(20, 20, 20)); p.drawText(fs, int(fs*2.0), title)
        if sub:
            f = qt.QFont("Helvetica"); f.setPixelSize(fs); p.setFont(f); p.setPen(qt.QColor(90, 90, 90)); p.drawText(fs, int(fs*3.4), sub)

    def _combo_legend(self, p, x0, y, fs, width):
        """图例 + 关键数字 + 免责声明，返回结束的 y"""
        f = qt.QFont("Helvetica"); f.setPixelSize(fs); p.setFont(f)
        for key, zh, en, *_ in STYLES:
            if key.startswith("em_") or not self.layer_present(key): continue
            col, op, vis = self.style_value(key)
            if not vis: continue
            p.setBrush(qt.QBrush(qt.QColor.fromRgbF(*col))); p.setPen(qt.QColor(90, 90, 90))
            p.drawEllipse(x0, y - int(fs*0.8), int(fs*0.9), int(fs*0.9))
            p.setPen(qt.QColor(20, 20, 20))
            txt = zh if lang() == "zh" else en
            p.drawText(qt.QRect(x0 + int(fs*1.5), y - fs, width - int(fs*1.5), int(fs*2.6)), qt.Qt.TextWordWrap, txt)
            y += int(fs*1.45) * (2 if qt.QFontMetrics(f).width(txt) > width - fs*1.5 else 1)
        y += int(fs*0.6); p.setPen(qt.QPen(qt.QColor(180, 180, 180))); p.drawLine(x0, y - fs, x0 + width, y - fs)
        p.setPen(qt.QColor(20, 20, 20))
        for ln in self.key_numbers()[0]:
            p.drawText(qt.QRect(x0, y - fs, width, int(fs*2.6)), qt.Qt.TextWordWrap, ln)
            y += int(fs*1.45) * (2 if qt.QFontMetrics(f).width(ln) > width else 1)
        small = qt.QFont("Helvetica"); small.setPixelSize(int(fs*0.75)); p.setFont(small); p.setPen(qt.QColor(110, 110, 110))
        p.drawText(qt.QRect(x0, y, width, fs*6), qt.Qt.TextWordWrap, DISCLAIMER())
        return y

    def onExportComboViews(self):
        """图像组：手术视角 / 斜视 / 全脑侧面 / 内部结构，2×2 拼图 + 右侧图例"""
        if self.G is None: slicer.util.errorDisplay(L("先生成方案", "Run the optimisation first")); return None
        import ScreenCapture, numpy as np
        case, work, D = self.case_paths(); G = self.G
        lm = slicer.app.layoutManager(); tw = lm.threeDWidget(0); view = tw.threeDView(); vn = tw.mrmlViewNode()
        camN = slicer.modules.cameras.logic().GetViewActiveCameraNode(vn); cam = camN.GetCamera()
        saved = (cam.GetPosition(), cam.GetFocalPoint(), cam.GetViewUp(), cam.GetViewAngle()); ax = vn.GetAxisLabelsVisible(); om = vn.GetOrientationMarkerType()
        e = np.asarray(G["entry"], float); n = np.asarray(G["SN"][G["ei"]], float); n /= np.linalg.norm(n) + 1e-9
        sup = np.array([0.0, 0.0, 1.0]); up = sup - n*np.dot(sup, n)
        up = up/np.linalg.norm(up) if np.linalg.norm(up) > 1e-3 else np.array([0.0, 1.0, 0.0])
        side = np.cross(up, n); side /= np.linalg.norm(side) + 1e-9
        obl = n*np.cos(np.radians(50)) + side*np.sin(np.radians(50))
        lat = np.array([1.0 if e[0] >= 0 else -1.0, 0.0, 0.0]); ctr = e - n*35
        views = [(L("手术视角（从骨窗往里看）", "Surgical view (through the window)"), e, e + n*230, up, None),
                 (L("斜视 50°（看阵列贴合）", "Oblique 50° (array conformity)"), e, e + obl*230, up, None),
                 (L("全脑侧面（开颅位置）", "Whole brain, lateral (craniotomy site)"), ctr, ctr + lat*430, sup, None),
                 (L("内部结构（颅骨隐藏、皮层半透明）", "Internal structures (skull hidden, cortex translucent)"), e - n*15, e - n*15 + n*260, up, "internal")]
        shots = []
        try:
            vn.SetAxisLabelsVisible(False); vn.SetOrientationMarkerType(0)
            for k, (ttl, foc, pos, vu, mode) in enumerate(views):
                if mode == "internal":
                    for sn in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
                        if sn.GetName() in ("颅骨_开窗", "骨瓣", "brain") and sn.GetDisplayNode():
                            dn = sn.GetDisplayNode(); S = sn.GetSegmentation()
                            for i in range(S.GetNumberOfSegments()):
                                dn.SetSegmentOpacity3D(S.GetNthSegmentID(i), 0.0 if sn.GetName() != "brain" else 0.18)
                cam.SetFocalPoint(*foc); cam.SetPosition(*pos); cam.SetViewUp(*vu); cam.SetViewAngle(30)
                view.renderWindow().GetRenderers().GetFirstRenderer().ResetCameraClippingRange(); view.forceRender()
                fn = os.path.join(D, f"{case}_combo_view{k}.png"); ScreenCapture.ScreenCaptureLogic().captureImageFromView(view, fn)
                shots.append((ttl, fn))
        finally:
            cam.SetPosition(*saved[0]); cam.SetFocalPoint(*saved[1]); cam.SetViewUp(*saved[2]); cam.SetViewAngle(saved[3])
            vn.SetAxisLabelsVisible(ax); vn.SetOrientationMarkerType(om); self.apply_all_styles(); view.forceRender()
        ims = [qt.QImage(f) for _, f in shots]; h = ims[0].height(); w = min(ims[0].width(), int(h*1.3))
        ims = [im.copy((im.width() - w)//2, 0, w, h) for im in ims]   # 取中间，去掉两边空白
        fs = max(14, h // 34); cap = int(fs*1.9); top = int(fs*4.2); pw = max(int(w*0.55), fs*24)
        W, H = 2*w + pw + fs, top + 2*(h + cap)
        out = qt.QImage(W, H, qt.QImage.Format_RGB32); out.fill(qt.QColor(255, 255, 255))
        p = qt.QPainter(out); p.setRenderHint(qt.QPainter.Antialiasing)
        self._combo_header(p, W, fs, f"UCSF-PDGM-{case} · {self.preset.currentText.split('（')[0].split(' (')[0]}",
                           L("同一方案的四个视角", "Four views of the same plan"))
        f = qt.QFont("Helvetica"); f.setPixelSize(int(fs*1.05)); f.setBold(True)
        for k, ((ttl, _), im) in enumerate(zip(shots, ims)):
            x, y = (k % 2)*w, top + (k // 2)*(h + cap)
            p.setFont(f); p.setPen(qt.QColor(20, 20, 20)); p.drawText(x + fs, y + int(fs*1.4), f"{'ABCD'[k]}  {ttl}")
            p.drawImage(x, y + cap, im)
        self._combo_legend(p, 2*w + fs, top + int(fs*1.4), fs, pw - fs)
        p.end()
        fn = os.path.join(D, f"{case}_合并图_图像_{lang()}.png" if lang() == "zh" else f"{case}_combined_views_{lang()}.png"); out.save(fn)
        for _, x in shots:
            try: os.remove(x)
            except OSError: pass
        fn = self.pub(fn); self.say(L("图像合并图已导出：", "Combined views exported:"), fn); return fn

    @staticmethod
    def _combo_bars(p, x, y, w, h, fs, title, groups, a, b, unit, names, hline=None, fmt="{:g}"):
        """一个分组柱状图面板：每组两根柱（INBRAIN 橙 / 传统 灰）"""
        f = qt.QFont("Helvetica"); f.setPixelSize(int(fs*1.1)); f.setBold(True); p.setFont(f); p.setPen(qt.QColor(20, 20, 20))
        p.drawText(qt.QRect(x, y, w, int(fs*1.8)), qt.Qt.AlignHCenter, title)
        f.setBold(False); f.setPixelSize(fs); p.setFont(f)
        x0, y0, x1, y1 = x + int(fs*3.2), y + int(fs*2.6), x + w - fs, y + h - int(fs*4.4)
        vmax = max([float(v) for v in a + b if v is not None] + [hline[0] if hline else 0, 1e-9])*1.18
        p.setPen(qt.QPen(qt.QColor(120, 120, 120))); p.drawLine(x0, y1, x1, y1); p.drawLine(x0, y0, x0, y1)
        p.save(); p.translate(x + int(fs*0.9), (y0 + y1)//2); p.rotate(-90); p.drawText(qt.QRect(-h//2, -fs, h, 2*fs), qt.Qt.AlignHCenter, unit); p.restore()
        gw = (x1 - x0)/len(groups); bw = gw*0.32
        cols = [qt.QColor(232, 158, 0), qt.QColor(128, 128, 128)]
        for i, g in enumerate(groups):
            for j, v in enumerate((a[i], b[i])):
                if v is None: continue
                bh = int((y1 - y0)*v/vmax); bx = int(x0 + gw*i + gw*0.16 + j*bw)
                p.fillRect(bx, y1 - bh, int(bw*0.92), bh, cols[j]); p.setPen(qt.QColor(20, 20, 20))
                p.drawText(qt.QRect(bx - fs, y1 - bh - int(fs*1.4), int(bw) + 2*fs, int(fs*1.3)), qt.Qt.AlignHCenter, fmt.format(v))
            p.setPen(qt.QColor(40, 40, 40))
            p.drawText(qt.QRect(int(x0 + gw*i), y1 + int(fs*0.3), int(gw), int(fs*2.6)), qt.Qt.AlignHCenter | qt.Qt.TextWordWrap, g)
        if hline:
            yy = y1 - int((y1 - y0)*hline[0]/vmax); p.setPen(qt.QPen(qt.QColor(200, 40, 40), max(2, fs//8), qt.Qt.DashLine)); p.drawLine(x0, yy, x1, yy)
            p.setPen(qt.QColor(200, 40, 40)); p.drawText(x1 - qt.QFontMetrics(f).width(hline[1]), yy - int(fs*0.3), hline[1])
        ly = y + h - int(fs*0.6); lx = x0
        for j, nm in enumerate(names):
            p.fillRect(lx, ly - int(fs*0.8), int(fs*0.9), int(fs*0.9), cols[j]); p.setPen(qt.QColor(20, 20, 20))
            p.drawText(lx + int(fs*1.3), ly, nm); lx += int(fs*1.3) + qt.QFontMetrics(f).width(nm) + 2*fs

    def onExportComboData(self):
        """数据组：边界段 / 放置与采样 / 时间 / 成本，2×2 柱状图"""
        if self.G is None: slicer.util.errorDisplay(L("先生成方案", "Run the optimisation first")); return None
        case, work, D = self.case_paths(); G = self.G; B = G.get("BND") or {}; sc = G["TIME"]["scen"]
        cost = {k: (t, d, tot) for k, lab, t, d, tot in self.cost_rows()}
        names = [L("INBRAIN 流程", "INBRAIN workflow"), L(f"传统流程（1×{B.get('strip_n', 4)} 条带）", f"Conventional (1×{B.get('strip_n', 4)} strip)")]
        fs = 22; pw, ph = 900, 620; top = int(fs*4.6); foot = int(fs*4.2)
        W, H = 2*pw, top + 2*ph + foot
        out = qt.QImage(W, H, qt.QImage.Format_RGB32); out.fill(qt.QColor(255, 255, 255))
        p = qt.QPainter(out); p.setRenderHint(qt.QPainter.Antialiasing)
        self._combo_header(p, W, fs, L(f"UCSF-PDGM-{case}：INBRAIN 流程对比传统流程", f"UCSF-PDGM-{case}: INBRAIN vs conventional workflow"),
                           L("两种器件跑同一套流程（麻醉期筛选、清醒期确认、同样的边界判定规则）", "Both devices run the same workflow (asleep screening, awake confirmation, same boundary rules)"))
        nreq = B.get("n_req", 0)
        panels = [
            (L(f"A  靠功能区的边界段（共 {nreq} 段）", f"A  Boundary segments near function ({nreq})"),
             [L("可区分肿瘤与功能组织", "Separable"), L("完整判定", "Fully decided"), L("至少确认边界", "Edge confirmed")],
             [B.get("sep"), B.get("full"), B.get("edge")], [B.get("strip_sep"), B.get("strip_full"), B.get("strip_edge")], L("段", "segments"), None, "{:g}"),
            (L("B  放置、采样与 FLAIR 残留", "B  Placements, sampling and FLAIR residual"),
             [L("放置次数", "Placements"), L("每段瘤周 15 mm 内采样点", "Samples per segment (≤15 mm)")] + ([L("FLAIR 残留估计 mL", "FLAIR residual, est. mL")] if (B.get("nce") or {}).get("total") else []),
             [len(G["PLAN"]), B.get("radial_inb")] + ([(B.get("nce") or {}).get("res_inb")] if (B.get("nce") or {}).get("total") else []),
             [B.get("strip_placements"), B.get("radial_strip")] + ([(B.get("nce") or {}).get("res_std")] if (B.get("nce") or {}).get("total") else []), L("次 / 个 / mL", "count / mL"), None, "{:.1f}"),
            (L("C  时间（min）", "C  Time (min)"), [L("清醒期", "Awake"), L("麻醉期额外", "Extra asleep"), L("定位相关全部", "Mapping total")],
             [sc["MAIN"]["awake"], sc["MAIN"]["asleep"], sc["MAIN"]["total"]], [sc["STD"]["awake"], sc["STD"]["asleep"], sc["STD"]["total"]], "min",
             (self.val("AWAKE_WINDOW"), L(f"清醒窗口 {self.val('AWAKE_WINDOW'):g} min", f"awake window {self.val('AWAKE_WINDOW'):g} min")), "{:.0f}"),
            (L("D  成本（€）", "D  Cost (€)"), [L("时间成本", "Time"), L("器件", "Devices"), L("合计", "Total")],
             list(cost["MAIN"]), list(cost["STD"]), "€", None, "{:,.0f}")]
        for k, (ttl, gr, a, b, unit, hl, fmt) in enumerate(panels):
            self._combo_bars(p, (k % 2)*pw, top + (k // 2)*ph, pw, ph, fs, ttl, gr, a, b, unit, names, hl, fmt)
        small = qt.QFont("Helvetica"); small.setPixelSize(int(fs*0.75)); p.setFont(small); p.setPen(qt.QColor(110, 110, 110))
        note = L(f"器件：{self.preset.currentText}；刺激电流 {self.val('STIM_I'):g} mA；每次放置 {self.val('T_PLACE'):g} min，每片 CCEP {self.val('T_CCEP'):g} min；"
                 f"手术室 {self.val('OR_COST'):g} €/min，INBRAIN {self.val('PRICE_INBRAIN'):,.0f} €/片，条带 {self.val('PRICE_STRIP'):,.0f} €/条。",
                 f"Device: {self.preset.currentText}; stimulation {self.val('STIM_I'):g} mA; placement {self.val('T_PLACE'):g} min, CCEP {self.val('T_CCEP'):g} min per placement; "
                 f"OR {self.val('OR_COST'):g} €/min, INBRAIN {self.val('PRICE_INBRAIN'):,.0f} € each, strip {self.val('PRICE_STRIP'):,.0f} € each.") + " " + DISCLAIMER()
        p.drawText(qt.QRect(fs, top + 2*ph + int(fs*0.4), W - 2*fs, foot), qt.Qt.TextWordWrap, note)
        p.end()
        fn = os.path.join(D, f"{case}_合并图_数据_{lang()}.png" if lang() == "zh" else f"{case}_combined_data_{lang()}.png"); out.save(fn)
        fn = self.pub(fn); self.say(L("数据合并图已导出：", "Combined data figure exported:"), fn); return fn

    # ---------- 报告 ----------
    def onReport(self):
        if self.G is None: slicer.util.errorDisplay(L("先生成方案", "Run the optimisation first")); return None
        fig = self.onExportFigure()
        if not fig: return None
        import numpy as np, datetime, html as H_
        G = self.G; case, work, D = self.case_paths(); tr_ = globals()["T"]; sc = G["TIME"]["scen"]
        lines, cov = self.key_numbers(); e = np.asarray(G["entry"])
        try: where = G["region"](G["entry"], G["SN"][G["ei"]]) if lang() == "zh" else ""
        except Exception: where = ""
        lv = {"ok": L("正常", "OK"), "warn": L("注意", "Check"), "bad": L("要处理", "Action needed"), "info": L("提示", "Note")}
        tabs = [(L("检查", "Checks"), [L("状态", "Status"), L("内容", "Item")], [[lv[l], t] for l, t in getattr(self, "check_items", [])]),
                (L("INBRAIN 方案要点", "INBRAIN plan highlights"), ["", "INBRAIN", L("传统流程", "Conventional"), L("说明", "Note")], [list(x) for x in self.value_items()])]
        tabs.append((L("放置计划", "Placement plan"), [tr_(x) for x in ["次序", "阶段", "角度", "判定段", "触点分区", "记录区覆盖", "贴合 mm", "形变", "近静脉", "纤维束", "脑区"]],
                     [[k + 1, tr_(G["phase"](p["r"])[1]), f"{p['r']['angle']}°", self.seg_cell(p['r']), "/".join(map(str, p['r'].get("zones", []))) or "—", f"{p['r']['rec']:.0%}", f"{p['r']['fit']:.1f}", f"{p['r'].get('strain', 0):.0%}", p['r'].get('vein_n', 0), "+".join(sorted(p["r"]["srcs"])) or "—", self.placement_regions(p["r"])]
                      for k, p in enumerate(G["PLAN"])]))
        if self.why_rows():
            tabs.append((L("没判定完的段和下一步", "Segments not fully decided and next steps"), [T(x) for x in ["段", "纤维束", "现状", "下一步"]], self.why_rows()))
        tabs.append((L("时间对比（min）", "Time comparison (min)"), [tr_(x) for x in ["方案", "清醒期 min", "麻醉期额外 min", "全部 min", "预计漏检位点"]],
                     [[tr_(lab), f"{sc[k]['awake']:.1f}", f"{sc[k]['asleep']:.1f}", f"{sc[k]['total']:.1f}", f"{sc[k]['missed']:.1f}"] for k, lab in SCEN_NAMES]))
        cr = self.cost_rows()
        tabs.append((L("成本估算（€）", "Cost estimate (€)"), [tr_(x) for x in ["方案", "时间成本 €", "器件 €", "合计 €"]],
                     [[tr_(lab), f"{t:,.0f}", f"{d:,.0f}", f"{tot:,.0f}"] for _, lab, t, d, tot in cr]))
        if self.shift_rows:
            keys = list(G["KEYS"])
            tabs.append((L(f"脑移位模拟（下沉 {self.val('SHIFT_SINK'):g} mm，侧向 {self.val('SHIFT_TAN'):g} mm）", f"Brain shift (sink {self.val('SHIFT_SINK'):g} mm, lateral {self.val('SHIFT_TAN'):g} mm)"),
                         [T("情况")] + [L(f"{k} 刺激", f"{k} stim") for k in keys] + [T("记录区覆盖")],
                         [[n] + [f"{c[k]:.0%}" for k in keys] + [f"{c['rec']:.0%}"] for n, c in self.shift_rows]))
        prm = {k: v for k, v in self.all_params().items() if k != "DEVICE"}
        prm["AUTO_SHIFT"] = self.autoShift.checked
        if self.device_json: prm["DEVICE"] = json.dumps(self.device_json, ensure_ascii=False)
        labels = {k: T(lab) for spec in [P_DEVICE, P_TARGET, P_CRANIO, P_OPT, P_TIME, P_TRACT, P_SKULL, P_COST, P_SHIFT] for k, lab, *_ in spec}
        _tipsrc = {it[0]: it[-1] for spec in [P_DEVICE, P_TARGET, P_CRANIO, P_OPT, P_TIME, P_TRACT, P_SKULL, P_COST, P_SHIFT] for it in spec}
        _extra = {"WIN_SHAPE": L("骨窗形状", "Window shape"), "WIN_FIT": L("先评分再定骨窗", "Score first, then fit the window"), "NCE_TARGET": L("FLAIR 残留未达标时自动扩大骨窗", "Enlarge the window when the FLAIR residual is above target"),
                  "AUTO_SHIFT": L("按肿瘤体积自动设脑移位下沉量", "Brain-shift sink set from tumour volume"), "STIM_MODEL": L("刺激范围按电流算", "Stimulation reach from current"), "AD_STRIP": L("传统流程加后放电监测条带", "Conventional workflow adds an after-discharge strip"),
                  "REQ_HEALTHY": L("要求健康参照触点", "Require healthy reference contacts"), "FMRI_PATH": L("术前 fMRI 文件（空 = 未用）", "Preoperative fMRI file (empty = not used)"), "NTMS_PATH": L("术前 nTMS 文件（空 = 未用）", "Preoperative nTMS file (empty = not used)"),
                  "ANGLES": L("每个候选位置试的旋转角度", "Rotation angles tried at each candidate spot"), "DEVICE": L("自定义器件（JSON）", "Custom device (JSON)")}
        _names = {"SMALL": L("小触点", "Small contacts"), "ASLEEP_FIRST": L("第一片麻醉期放好", "First array placed asleep"), "PASSIVE_ASLEEP": L("被动定位放在麻醉期", "Passive mapping asleep"),
                  "MOTOR_AWAKE": L("运动定位放在清醒期", "Motor mapping awake"), "ENTRY_MODE": L("入口点", "Entry"), "PRESET": L("器件预设", "Device preset"), "WIN_SHAPE_IDX": L("骨窗形状", "Window shape"),
                  "WIN_FIT": L("先评分再定骨窗", "Score first, then fit"), "STIM_MODEL": L("刺激范围按电流算", "Stimulation reach from current"), "AD_STRIP": L("后放电监测条带", "After-discharge strip"),
                  "REQ_HEALTHY": L("健康参照触点", "Healthy reference"), "FMRI_PATH": L("术前 fMRI", "Preoperative fMRI"), "NTMS_PATH": L("术前 nTMS", "Preoperative nTMS"), "AUTO_SHIFT": L("脑移位自动设", "Auto brain shift"), "DEVICE": L("自定义器件", "Custom device")}
        _extra.update({"SMALL": L("大触点之间有只记录的小触点", "Record-only small contacts between the large ones"), "ASLEEP_FIRST": L("第一片在麻醉期就放好，醒来不用再放", "The first array is placed while asleep"),
                       "PASSIVE_ASLEEP": L("全麻下用听觉任务做被动高 γ 定位", "Passive high-gamma mapping with an auditory task under anaesthesia"), "MOTOR_AWAKE": L("否 = 运动区在麻醉下用 MEP 测", "No = motor mapping under anaesthesia with MEP"),
                       "ENTRY_MODE": L("自动推荐或手动放置", "Automatic or manual"), "PRESET": L("器件参数预设", "Device parameter preset"), "WIN_SHAPE_IDX": L("圆形 / 椭圆 / 圆角矩形", "Circle / ellipse / rounded rectangle")})
        def _val(k, v):
            if isinstance(v, bool) or str(v) in ("True", "False"): return L("是", "Yes") if str(v) == "True" else L("否", "No")
            if k == "ENTRY_MODE": return [L("自动推荐", "Automatic"), L("手动", "Manual")][int(v)] if str(v).isdigit() and int(v) < 2 else str(v)
            if k == "WIN_SHAPE_IDX": return [L("圆形", "Circle"), L("椭圆", "Ellipse"), L("圆角矩形", "Rounded rectangle")][int(v)] if str(v).isdigit() and int(v) < 3 else str(v)
            if k == "PRESET":
                try: return self.preset.itemText(int(v))
                except Exception: return str(v)
            if isinstance(v, float): return f"{v:g}"
            return str(v) if str(v) not in ("", "None") else "—"
        def _short(t):
            t = str(t or "").split("。")[0].split(". ")[0]
            return t if len(t) <= 70 else t[:68] + "…"
        tabs.append((L("参数快照（本次计算用的全部参数）", "Parameter snapshot (all parameters used in this run)"), [L("参数", "Parameter"), L("值", "Value"), L("说明", "Meaning")],
                     [[labels.get(k) or _names.get(k, k), _val(k, v), _short(self.param_tip(k, _tipsrc.get(k, "")) or _extra.get(k, ""))] for k, v in prm.items()]))
        title = L(f"INBRAIN 电极放置规划报告：UCSF-PDGM-{case}", f"INBRAIN array placement report: UCSF-PDGM-{case}")
        info = [L(f"生成时间：{datetime.datetime.now():%Y-%m-%d %H:%M}", f"Generated: {datetime.datetime.now():%Y-%m-%d %H:%M}"),
                L(f"器件：{self.preset.currentText}", f"Device: {self.preset.currentText}"),
                L(f"入口点：{self.entry_desc()[0]}，{where}，RAS ({e[0]:.0f}, {e[1]:.0f}, {e[2]:.0f})",
                  f"Entry: {self.entry_desc()[1]}, RAS ({e[0]:.0f}, {e[1]:.0f}, {e[2]:.0f})"),
                L(f"切除边界靠功能区 {(G.get('BND') or {}).get('n_req', 0)} 段，完整判定 {(G.get('BND') or {}).get('full', 0)} 段",
                  f"{(G.get('BND') or {}).get('n_req', 0)} boundary segments near function, {(G.get('BND') or {}).get('full', 0)} fully decided")] + lines
        try: nav = self.onExportNav(); info.append(L("导航坐标：", "Navigation coordinates: ") + ", ".join(os.path.basename(x) for x in nav))
        except Exception: pass
        info += getattr(self, "win_lines", [])
        if getattr(self, "atlas_lines", None): info += self.atlas_lines
        rs = self.reg_status()
        if rs: info.append(L("配准检查：", "Registration check: ") + (L("通过", "OK") if rs.startswith("pass") else L("不通过", "failed")) + rs[4:])
        try:   # 可复现信息：脚本指纹、参数指纹、Slicer 版本
            import hashlib
            fp = lambda fn: hashlib.sha256(open(fn, "rb").read()).hexdigest()[:8]
            ph = hashlib.sha256(json.dumps(prm, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:8]
            info.append(L("可复现信息：", "Reproducibility: ") + f"slicer_placement_score.py {fp(os.path.join(SCRIPTS, 'slicer_placement_score.py'))}, time_model.py {fp(os.path.join(SCRIPTS, 'time_model.py'))}, "
                        f"INBRAINPlanner.py {fp(os.path.realpath(__file__))}, params {ph}, 3D Slicer {slicer.app.applicationVersion}")
        except Exception as e: self.say("repro:", e)
        if getattr(self, "path_mm", 0): info.append(L(f"放置路径总长约 {self.path_mm:.0f} mm", f"Placement path length about {self.path_mm:.0f} mm"))
        note = DISCLAIMER() + L(" 时间和成本按参数快照中的数值计算，可根据本院情况修改。", " Time and cost follow the parameter snapshot and can be set to local values.")
        figname = os.path.basename(fig)
        md = [f"# {title}", ""] + [f"- {x}" for x in info] + ["", f"![]({figname})", ""]
        for t, hd, rows in tabs:
            md += [f"## {t}", "", "| " + " | ".join(hd) + " |", "|" + "---|"*len(hd)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows] + [""]
        md += [f"*{note}*", ""]
        base = os.path.join(D, f"{case}_report_{lang()}")
        open(base + ".md", "w", encoding="utf-8").write("\n".join(md))
        esc = H_.escape
        h = [f"<html><head><meta charset='utf-8'><style>body{{font-family:Helvetica,'PingFang SC',sans-serif;font-size:10pt}}"
             f"table{{border-collapse:collapse}}td,th{{border:1px solid #999;padding:2px 6px}}th{{background:#eee}}</style></head><body>",
             f"<h2>{esc(title)}</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in info) + "</ul>",
             f"<p><img src='{esc(figname)}' width='640'></p>"]
        for t, hd, rows in tabs:
            h.append(f"<h3>{esc(t)}</h3><table width='100%'><thead><tr>" + "".join(f"<th>{esc(str(c))}</th>" for c in hd) + "</tr></thead><tbody>"   # thead：跨页时表头自动重复
                     + "".join("<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>")
        h.append(f"<p><i>{esc(note)}</i></p></body></html>")
        htm = "".join(h); open(base + ".html", "w", encoding="utf-8").write(htm)
        out = base + ".md"
        try:
            doc = qt.QTextDocument(); doc.setBaseUrl(qt.QUrl.fromLocalFile(D + "/"))
            _img = qt.QImage(os.path.join(D, figname))
            if _img.isNull() and os.path.exists(fig): _img = qt.QImage(fig)
            if not _img.isNull():   # 直接把图放进文档资源，不依赖相对路径；先缩到 1600 px 宽，PDF 不会过大
                if _img.width() > 1600: _img = _img.scaledToWidth(1600, qt.Qt.SmoothTransformation)
                doc.addResource(qt.QTextDocument.ImageResource, qt.QUrl(figname), _img)
            doc.setHtml(htm)
            pr = qt.QPrinter(qt.QPrinter.HighResolution); pr.setOutputFormat(qt.QPrinter.PdfFormat); pr.setOutputFileName(base + ".pdf")
            doc.print_(pr) if hasattr(doc, "print_") else doc.print(pr); out = base + ".pdf"
        except Exception as ex:
            self.say(L("PDF 没生成（用 HTML/MD）：", "PDF not generated (use HTML/MD): "), ex)
        out = self.pub(out); self.say(L("报告已生成：", "Report generated:"), out)
        return out

    def plan_nodes(self):
        out = {}
        for nd in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            m = re.match(r"Plan_(\d+)_", nd.GetName())
            if m: out.setdefault(int(m.group(1)), []).append(nd)
        return out

    # ---------- 显示样式 ----------
    @staticmethod
    def saved_style(key, col, op):
        q = qt.QSettings()
        try:
            c = [float(x) for x in str(q.value(STYLE_KEY + key + "/color", "")).split(",")] or col
            if len(c) != 3: c = col
        except Exception: c = col
        try: o = float(q.value(STYLE_KEY + key + "/opacity", op))
        except Exception: o = op
        return tuple(c), o

    def style_value(self, key):
        vis, cb, sl = self.style_w[key]; c = cb.color
        return (c.redF(), c.greenF(), c.blueF()), sl.value / 100.0, vis.checked

    def style_nodes(self, key):
        spec = next(s for s in STYLES if s[0] == key); kind, match = spec[3], spec[4]
        if kind in ("model", "multi"):
            return [n for n in slicer.util.getNodesByClass("vtkMRMLModelNode") if n.GetName().startswith(tuple(match))]
        if kind == "markup":
            return [n for n in slicer.util.getNodesByClass("vtkMRMLMarkupsNode") if n.GetName() in match]
        if kind == "plan":
            return [n for n in slicer.util.getNodesByClass("vtkMRMLModelNode") if re.match(r"Plan_\d+" + match[0] + "$", n.GetName())]
        return []

    def apply_style(self, key, save=False):
        if key not in getattr(self, "style_w", {}): return
        col, op, vis = self.style_value(key)
        spec = next(s for s in STYLES if s[0] == key)
        if spec[3] == "seg":
            segname, labels = spec[4][0], spec[4][1:]
            for sn in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
                if sn.GetName() != segname or not sn.GetDisplayNode(): continue
                S = sn.GetSegmentation()
                for i in range(S.GetNumberOfSegments()):
                    sg = S.GetNthSegment(i); sid = S.GetNthSegmentID(i)
                    if labels == [""] or any(sg.GetName().endswith(x) for x in labels):
                        sg.SetColor(*col); dn = sn.GetDisplayNode()
                        dn.SetSegmentOpacity3D(sid, op); dn.SetSegmentVisibility(sid, vis)
        else:
            for nd in self.style_nodes(key):
                dn = nd.GetDisplayNode()
                if spec[3] == "markup":
                    dn.SetSelectedColor(*col); dn.SetColor(*col); dn.SetOpacity(op); dn.SetVisibility(vis); continue
                if spec[3] != "multi": dn.SetColor(*col)
                dn.SetScalarVisibility(False); dn.SetOpacity(op)
                if save or not key.startswith("em_"): dn.SetVisibility(vis)   # 入口评分默认隐藏，只在用户勾选时改
        if save:
            q = qt.QSettings(); q.setValue(STYLE_KEY + key + "/color", ",".join(f"{x:.3f}" for x in col)); q.setValue(STYLE_KEY + key + "/opacity", op)

    def apply_all_styles(self):
        for key, *_ in STYLES: self.apply_style(key)

    @staticmethod
    def default_style(key, col, op, factory=False):
        """用户“设为默认”存过的样式优先，否则出厂样式"""
        q = qt.QSettings(); k = STYLE_KEY + "Default/" + key + "/"
        if factory or q.value(k + "color") is None: return col, op, True
        try:
            c = tuple(float(x) for x in str(q.value(k + "color")).split(","))
            return c, float(q.value(k + "opacity")), str(q.value(k + "visible", "true")).lower() in ("true", "1")
        except Exception: return col, op, True

    def onSetDefaultStyle(self):
        q = qt.QSettings()
        for key, *_ in STYLES:
            col, op, vis = self.style_value(key); k = STYLE_KEY + "Default/" + key + "/"
            q.setValue(k + "color", ",".join(f"{x:.3f}" for x in col)); q.setValue(k + "opacity", op); q.setValue(k + "visible", "true" if vis else "false")
        self.say(L("已把当前样式设为默认", "Current style saved as default"))

    def onResetStyle(self, factory=False):
        for key, zh, en, kind, match, col0, op0 in STYLES:
            col, op, v = self.default_style(key, col0, op0, factory)
            vis, cb, sl = self.style_w[key]
            for o in (vis, cb, sl): o.blockSignals(True)
            vis.checked = v; cb.color = qt.QColor.fromRgbF(*col); sl.value = round(op*100)
            for o in (vis, cb, sl): o.blockSignals(False)
            self.apply_style(key, save=True)

    # ---------- 颅骨 ----------
    def onSkull(self):
        try:
            case, work, D = self.case_paths(); self.build_skull_ui(D, case)
            if self.G is not None: self.make_window()
        except Exception as e:
            import traceback; self.say(traceback.format_exc()); slicer.util.errorDisplay(str(e))

    def build_skull_ui(self, D, case):
        import time; t0 = time.time()
        how = self.logic.build_skull(D, case, self.skullSrc.currentIndex, self.skullFile.currentPath, self.val("SKULL_IN"),
                                     self.val("SKULL_THICK"), self.val("CT_HU"),
                                     lambda fr, tx: self.set_progress(self.skullBar, self.skullLab, fr, L("颅骨：", "Skull: ") + tx, t0))
        self.hide_later(self.skullBar, self.skullLab); self.say(L("颅骨：", "Skull: ") + how)
        self.skull_key = (D, self.skullSrc.currentIndex, self.skullFile.currentPath, self.val("SKULL_IN"), self.val("SKULL_THICK"), self.val("CT_HU"))
        self.apply_style("skull"); self.apply_style("flap")

    def make_window(self):
        """按当前入口点和骨窗半径挖骨窗"""
        try:
            case, work, D = self.case_paths()
            key = (D, self.skullSrc.currentIndex, self.skullFile.currentPath, self.val("SKULL_IN"), self.val("SKULL_THICK"), self.val("CT_HU"))
            if getattr(self.logic, "skull", None) is None or getattr(self, "skull_key", None) != key: self.build_skull_ui(D, case)
            self.logic.cut_skull(self.G["entry"], self.G["win_sdf"], self.G["WIN_N"])
            self.apply_style("skull"); self.apply_style("flap")
            self.say(L("已开骨窗：", "Bone window cut: ") + self.win_desc())
        except Exception as e:
            import traceback; self.say(traceback.format_exc())

    def onPlanSelect(self):
        rows = sorted(set(i.row() for i in self.planTable.selectedIndexes()))
        if not rows: return
        for k, nds in self.plan_nodes().items():
            for nd in nds:
                key = "large" if nd.GetName().endswith("_large") else "small"
                nd.GetDisplayNode().SetOpacity(self.style_value(key)[1] if (k - 1) in rows else 0.08)

    def onShowAll(self):
        self.apply_style("large"); self.apply_style("small")

    def onToggleEntryMap(self):
        nds = [n for n in slicer.util.getNodesByClass("vtkMRMLModelNode") if n.GetName().startswith("EntryMap_")]
        on = not (nds and nds[0].GetDisplayNode().GetVisibility())
        for n in nds: n.GetDisplayNode().SetVisibility(on)

    def onSaveScene(self):
        try: case, work, D = self.case_paths()
        except Exception as e: slicer.util.errorDisplay(str(e)); return
        fn = os.path.join(D, f"{case}_规划场景.mrb"); slicer.util.saveScene(fn); self.say(L("场景已保存：", "Scene saved:"), self.pub(fn))

    def onOpenDir(self):
        r = self.result_dir()
        if not r: return
        self.sync_out(); os.makedirs(r, exist_ok=True); qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(r))


# ---------------- 自动测试（Slicer 开发者模式里点 Reload and Test，或 slicer.modules.INBRAINPlannerInstance.runTest()） ----------------
class INBRAINPlannerTest(ScriptedLoadableModuleTest):
    """不需要数据的部分总会跑；有 0007 数据时再跑完整回归（环境变量 INBRAIN_TEST_CASE 可指定病例文件夹）"""

    def setUp(self):
        slicer.mrmlScene.Clear(0)

    def runTest(self):
        self.setUp(); self.test_resources()
        self.setUp(); self.test_case_regression()

    def test_resources(self):
        self.delayDisplay("Device library and style defaults")
        self.assertTrue(len(PRESETS) >= 2, "device library not loaded")
        self.assertTrue(all(k in v for v in PRESETS.values() for k in ("NX", "NY", "PITCH")))
        self.assertEqual(len(STYLES), len({s[0] for s in STYLES}))
        self.assertTrue(os.path.exists(os.path.join(SCRIPTS, "slicer_placement_score.py")), "pipeline/ not found")
        self.delayDisplay("Resources OK")

    def test_case_regression(self):
        folder = os.environ.get("INBRAIN_TEST_CASE") or os.path.normpath(os.path.join(HERE, "..", "..", "..", "UCSF-PDGM_Dataset", "UCSF-PDGM-0007_nifti"))
        if not os.path.isdir(folder):
            self.delayDisplay("No test case found, skipping regression"); return
        self.delayDisplay("Planning regression on " + os.path.basename(folder))
        slicer.util.selectModule("INBRAINPlanner"); w = slicer.modules.inbrainplanner.widgetRepresentation().self()
        w.caseDir.currentPath = folder; w.preset.setCurrentIndex(0); w.onLoad(); w.onRun()
        G = w.G; self.assertIsNotNone(G, "plan failed")
        n = len(G["PLAN"]); self.assertTrue(1 <= n <= 30, f"placements {n}")
        B = G["BND"]; self.assertGreater(B["n_req"], 0, "no boundary segments near function")
        self.assertGreaterEqual(B["full"], 0.8*B["n_arr"], f"boundary decided {B['full']}/{B['n_arr']}")
        w._testing = True   # 测试不往用户的结果文件夹同步
        nav = w.onExportNav(); self.assertTrue(len(nav) == 3 and all(os.path.exists(x) for x in nav))   # 放置 csv、fcsv、边界段书签
        self.assertEqual(sum(1 for _ in open(nav[0], encoding="utf-8")) - 1, 1 + 5*n)
        w._testing = False
        w.save_params_to_scene(); self.assertIsNotNone(slicer.mrmlScene.GetFirstNodeByName(w.PARAM_NODE))
        if w.atlasDir.currentPath and os.path.isdir(os.path.join(w.atlasDir.currentPath, "tpl-harvardoxford")):
            self.delayDisplay("Brain atlas")
            w.onAtlas(); self.assertIsNotNone(getattr(w.logic, "atlas", None), "atlas registration failed")
            labs = w.logic.atlas_labels(G["SP"]); self.assertGreater((labs > 0).mean(), 0.5, "too few cortical points labelled")
            w.onRun(); self.assertTrue(w.atlas_lines, "no task suggestion")
        self.delayDisplay(f"Regression OK: {n} placements, boundary decided {B['full']}/{B['n_req']}")
