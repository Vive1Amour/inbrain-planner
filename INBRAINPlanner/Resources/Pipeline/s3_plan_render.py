import os
CASE = os.environ.get("CASE", "0007")                 # 病例号
SIGN = -1 if os.environ.get("SIDE", "R") == "L" else 1  # 肿瘤在左（L）还是右（R）半球
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work"))   # 纯英文工作目录（Slicer 命令行模块不认中文路径）
SCRIPTS = os.environ.get("SCRIPTS", os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ".")
D = os.path.join(WORK, "w" + CASE) + "/"
import slicer, vtk, numpy as np, traceback, ScreenCapture
SCRIPT = os.path.join(SCRIPTS, "slicer_placement_score.py")
def log(*a): print("LOG", *a, flush=True)
try:
    t1c = slicer.util.loadVolume(D + CASE + "_T1c_bias.nii.gz")
    brain = slicer.util.loadLabelVolume(D + CASE + "_brain_segmentation.nii.gz")
    tumor = slicer.util.loadLabelVolume(D + CASE + "_tumor_segmentation.nii.gz")
    for name, col in [("CST", (0.15, 0.35, 1.0)), ("AF", (0.1, 0.75, 0.25))]:
        md = slicer.util.loadModel(D + CASE + f"_tract_{name}.vtk"); md.SetName("tract_" + name)
        dn = md.GetDisplayNode(); dn.SetColor(*col); dn.SetScalarVisibility(False); dn.SetLineWidth(2)

    # 肿瘤 + 脑
    seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "tumor")
    slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(tumor, seg)
    seg.CreateClosedSurfaceRepresentation()
    S = seg.GetSegmentation()
    for i in range(S.GetNumberOfSegments()):
        sg = S.GetNthSegment(i); nm = sg.GetName()
        sg.SetColor(*{"1": (0.9, 0.9, 0.2), "2": (0.55, 0.7, 1.0), "4": (0.85, 0.1, 0.1)}.get(nm[-1], (1, 1, 1)))
        seg.GetDisplayNode().SetSegmentOpacity3D(S.GetNthSegmentID(i), 0.12 if nm.endswith("2") else 0.9)
    bseg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "brain")
    slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(brain, bseg)
    bseg.CreateClosedSurfaceRepresentation(); bseg.GetDisplayNode().SetOpacity3D(0.10); bseg.GetDisplayNode().SetVisibility2D(False)
    bseg.GetSegmentation().GetNthSegment(0).SetColor(0.85, 0.78, 0.72)

    lm = slicer.app.layoutManager(); cap = ScreenCapture.ScreenCaptureLogic()
    lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
    vn = lm.threeDWidget(0).mrmlViewNode()
    vn.SetBackgroundColor(1, 1, 1); vn.SetBackgroundColor2(1, 1, 1); vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
    v3 = lm.threeDWidget(0).threeDView()
    bc = np.argwhere(slicer.util.arrayFromVolume(brain) > 0).mean(0)[::-1]
    mb = vtk.vtkMatrix4x4(); brain.GetIJKToRASMatrix(mb); bcen = np.array(mb.MultiplyPoint(list(bc) + [1])[:3])

    def shoot(entry, fname, dist=260):
        n = entry - bcen; n /= np.linalg.norm(n)
        cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(vn)
        cam.SetFocalPoint(*bcen); cam.SetPosition(*(bcen + n*dist*1.6)); cam.SetViewUp(0, 0, 1)
        cam.ResetClippingRange(); slicer.app.processEvents()
        cap.captureImageFromView(v3, D + fname)

    def lateral(fname, dist=260):
        cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(vn)
        n = np.array([SIGN*1.0, 0.0, 0.45]); n /= np.linalg.norm(n)
        cam.SetFocalPoint(*bcen); cam.SetPosition(*(bcen + n*dist*1.6)); cam.SetViewUp(0, 0, 1)
        cam.ResetClippingRange(); slicer.app.processEvents(); cap.captureImageFromView(v3, D + fname)
    def show(prefixes, on):
        for nd in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if nd.GetName().startswith(tuple(prefixes)): nd.GetDisplayNode().SetVisibility(on)

    results = {}
    for tag, nx, ny, pitch, small in [("3x7", 3, 7, 4.0, True)] + ([("1x4", 1, 4, 10.0, False)] if os.environ.get("RUN_1X4") == "1" else []):
        # 上一个器件的计划从场景里删掉，每个 mrb 只含一种器件
        for nd in list(slicer.util.getNodesByClass("vtkMRMLModelNode")):
            if "_Plan_" in nd.GetName(): slicer.mrmlScene.RemoveNode(nd)
        src = open(SCRIPT, encoding="utf-8").read()
        src = (src.replace("NX, NY = 3, 7", f"NX, NY = {nx}, {ny}").replace("PITCH = 4.0 ", f"PITCH = {pitch} ")
                  .replace("SMALL = True ", f"SMALL = {small} ").replace("TRACT_W = {\"CST\": 1.0, \"AF\": 0.5}", "TRACT_W = {\"CST\": 1.0, \"AF\": 1.0}" if SIGN < 0 else "TRACT_W = {\"CST\": 1.0, \"AF\": 0.5}").replace("OUT = None", f'OUT = "{D}placement_scores_{tag}.csv"'))
        log("=== scoring", tag); g_ = {"__name__": "x"}; exec(src, g_)
        results[tag] = g_["TIME"]; entry = g_["entry"]; WIN = g_["AWAKE_WINDOW"]
        log(tag, "placements", results[tag]["placements"])
        for nd in list(slicer.util.getNodesByClass("vtkMRMLModelNode")):
            if nd.GetName().startswith("Plan_"):
                nd.SetName(tag + "_" + nd.GetName())
                if tag == "1x4": nd.GetDisplayNode().SetColor(1, 0.2, 1)
        if tag == "3x7":
            # 可开颅区域图：只显示脑、肿瘤、纤维束、入口评分
            show(["Targets_", "Window_edge", "3x7_Plan_"], False); show(["EntryMap_"], True)
            lateral(CASE + "_可开颅区域_入口评分.png")
            show(["EntryMap_"], False); show(["Targets_", "Window_edge"], True)
            shoot(entry, CASE + "_目标区_红刺激_蓝记录.png")
            show(["3x7_Plan_"], True)
        shoot(entry, CASE + f"_计划_{tag}_双色目标+开颅窗口.png")
        slicer.util.saveScene(D + CASE + f"_{tag}_规划场景.mrb")
        log("saved scene", tag)
    import csv
    with open(D + "time_compare.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["方案", "放置次数", "语言刺激位点", "运动刺激位点", "清醒期用时min", "麻醉期额外min", "全部定位用时min", "占清醒窗口", "估计漏掉"])
        def row(lab, t, key, lang):
            v = t["scen"][key]
            w.writerow([lab, t["placements"] if not key.startswith("STD") else 2, lang, t["motor_sites"] if not key.startswith("STD") else
                        (t["counts"]["probe_grid_motor"] if key == "STD" else (t["counts"]["probe_opt_motor"] if key == "STD_opt" else 0)),
                        f"{v['awake']:.1f}", f"{v['asleep']:.1f}", f"{v['total']:.1f}", f"{v['awake']/WIN:.0%}", f"{v['missed']:.1f}"])
        t = results["3x7"]; P_ = t["counts"]; Pm = g_["PARAMS"]
        row("INBRAIN 主方案（阵列多点刺激+多点记录）", t, "MAIN", f"{t['scen']['MAIN']['stim']:.1f}")
        row("商用条带方案（条带记录+探针1cm刺激）", t, "STD", P_["probe_grid_lang"])
        row("商用条带方案·文献典型病例（13位点）", t, "STD_lit", 13.1)
    log("RESULT", results); log("render done")
except Exception:
    traceback.print_exc()
slicer.app.quit()
