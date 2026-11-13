# 第 3b 步：更真实的 3D 图（Slicer 里跑，会弹窗口截图）
# 在 s3 存好的规划场景上加三样东西：
#   1 有脑回脑沟的皮层表面：T1c 在脑 mask 里去掉暗的脑脊液（脑沟），做表面并平滑
#   2 头皮 + 颅骨壳：T1c 头部 mask 减去脑，按开颅窗口在入口处挖一个洞（骨瓣取下后的样子）
#   3 方位人形标记（看得出前后上下）
# 出两张图：手术视角（从骨窗往里看，皮层、电极片、刺激/记录目标）、内部结构（皮层半透明，看肿瘤、纤维束、电极片）
import os
CASE = os.environ.get("CASE", "0007"); SIGN = -1 if os.environ.get("SIDE", "R") == "L" else 1
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work")); D = os.path.join(WORK, "w" + CASE) + "/"
WINDOW_R = float(os.environ.get("WINDOW_R", "35"))
SKULL_IN, SKULL_OUT = 4.0, 11.0     # 示意颅骨：脑表面外 4–11 mm
import slicer, vtk, numpy as np, traceback, ScreenCapture
import vtk.util.numpy_support
from scipy import ndimage
def log(*a): print("LOG", *a, flush=True)
try:
    for tag in [t for t in ["3x7", "1x4"] if os.path.exists(D + f"{CASE}_{t}_规划场景.mrb")]:
        slicer.mrmlScene.Clear(0)
        slicer.util.loadScene(D + f"{CASE}_{tag}_规划场景.mrb")
        for nd in list(slicer.util.getNodesByClass("vtkMRMLSegmentationNode")):
            if nd.GetName() in ("皮层", "头皮颅骨_开窗", "示意颅骨_开窗", "颅骨_开窗", "头皮_切开"): slicer.mrmlScene.RemoveNode(nd)
        t1c = [n for n in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode") if "T1c" in n.GetName()][0]
        brain = [n for n in slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode") if "brain" in n.GetName()][0]
        A = slicer.util.arrayFromVolume(t1c).astype(np.float32); B = slicer.util.arrayFromVolume(brain) > 0
        # T1c 网格四周补 24 个体素的边，让颅骨、头皮不被网格边缘截掉
        PADV = 24; A = np.pad(A, PADV); B = np.pad(B, PADV)
        big = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "grid_padded")
        mtmp = vtk.vtkMatrix4x4(); t1c.GetIJKToRASMatrix(mtmp); Mt = slicer.util.arrayFromVTKMatrix(mtmp)
        Mt[:3, 3] = (Mt @ np.r_[-PADV, -PADV, -PADV, 1])[:3]
        mnew = vtk.vtkMatrix4x4()
        for i_ in range(4):
            for j_ in range(4): mnew.SetElement(i_, j_, Mt[i_, j_])
        big.SetIJKToRASMatrix(mnew); slicer.util.updateVolumeFromArray(big, A)
        sp = np.array(t1c.GetSpacing())[::-1]
        # 1 皮层：脑 mask 内，比脑脊液亮的部分
        thr = 0.55*np.median(A[B]); cort = B & (A > thr)
        cort = ndimage.binary_opening(cort, iterations=1); lab, n = ndimage.label(cort)
        cort = lab == (np.bincount(lab.ravel())[1:].argmax() + 1); cort = ndimage.binary_fill_holes(cort)
        # 2 头皮和颅骨：UCSF-PDGM 结构像都去过颅骨；弥散 b0 虽然没去，但做了脂肪抑制、头皮发黑、还有 EPI 变形，
        #   试过只能得到零碎几片颅骨。所以按典型解剖厚度从脑包络面向外生成（示意）：
        #   脑外 0–4 mm 脑脊液和硬膜，4–11 mm 颅骨，11–17 mm 头皮
        r = 6; zz, yy, xx = np.ogrid[-r:r+1, -r:r+1, -r:r+1]
        env = ndimage.binary_fill_holes(ndimage.binary_closing(np.pad(B, r), xx*xx + yy*yy + zz*zz <= r*r))[r:-r, r:-r, r:-r]
        pad = 20
        dout = ndimage.distance_transform_edt(~np.pad(env, pad), sampling=sp)[pad:-pad, pad:-pad, pad:-pad]
        dout = ndimage.gaussian_filter(dout, 1.5)
        shell = (dout > SKULL_IN) & (dout <= SKULL_OUT)              # 颅骨
        scalp = (dout > SKULL_OUT) & (dout <= SKULL_OUT + 6)         # 头皮
        head = dout <= SKULL_OUT + 6
        log("skull: 示意，脑外", SKULL_IN, "-", SKULL_OUT, "mm")
        # 入口点、法向：从场景里的 Entry_point 模型取
        ep = slicer.util.getFirstNodeByName("Entry_point")
        entry = np.array(ep.GetPolyData().GetCenter())
        m = vtk.vtkMatrix4x4(); big.GetIJKToRASMatrix(m); M = slicer.util.arrayFromVTKMatrix(m)
        bc = np.argwhere(B).mean(0)[::-1]; bcen = (M @ np.r_[bc, 1])[:3]
        nrm = entry - bcen; nrm /= np.linalg.norm(nrm)
        # 挖骨窗：壳上离入口点在垂直于法向的平面内 < WINDOW_R、且在入口外侧的体素去掉
        idx = np.argwhere(shell); ras = (M @ np.c_[idx[:, ::-1], np.ones(len(idx))].T)[:3].T
        v = ras - entry; along = v @ nrm; radial = np.linalg.norm(v - along[:, None]*nrm, axis=1)
        hole = (radial < WINDOW_R) & (along > -8)
        shell_cut = shell.copy(); k = idx[hole]; shell_cut[k[:, 0], k[:, 1], k[:, 2]] = False
        idx2 = np.argwhere(scalp); ras2 = (M @ np.c_[idx2[:, ::-1], np.ones(len(idx2))].T)[:3].T
        v2 = ras2 - entry; al2 = v2 @ nrm; rad2 = np.linalg.norm(v2 - al2[:, None]*nrm, axis=1)
        scalp_cut = scalp.copy(); k2 = idx2[(rad2 < WINDOW_R + 12) & (al2 > -8)]; scalp_cut[k2[:, 0], k2[:, 1], k2[:, 2]] = False
        def surf(arr, name, color, op, smooth=0.5):
            lv = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", name + "_lab")
            lv.CopyOrientation(big); slicer.util.updateVolumeFromArray(lv, arr.astype(np.uint8))
            sg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", name)
            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(lv, sg)
            sg.GetSegmentation().SetConversionParameter("Smoothing factor", str(smooth))
            sg.CreateClosedSurfaceRepresentation(); slicer.mrmlScene.RemoveNode(lv)
            s0 = sg.GetSegmentation().GetNthSegment(0); s0.SetColor(*color)
            dn = sg.GetDisplayNode(); dn.SetOpacity3D(op); dn.SetVisibility2D(False); return sg
        cortex = surf(cort, "皮层", (0.93, 0.78, 0.74), 1.0, 0.3)
        skull = surf(shell_cut, "颅骨_开窗", (0.93, 0.9, 0.82), 1.0, 0.7)
        scalpS = surf(scalp_cut, "头皮_切开", (0.86, 0.66, 0.55), 0.35, 0.6); scalpS.GetDisplayNode().SetVisibility(False)
        # 方位点：A 前额 B 头顶 C 枕部 D 太阳穴 E 耳上方（D、E 在肿瘤这一侧），标在头表面外面一点
        hidx = np.argwhere(head); hras = (M @ np.c_[hidx[:, ::-1], np.ones(len(hidx))].T)[:3].T
        bidx = np.argwhere(B); bras = (M @ np.c_[bidx[:, ::-1][::20], np.ones(len(bidx[::20]))].T)[:3].T
        midx = bras[:, 0].mean(); y0, y1 = bras[:, 1].min(), bras[:, 1].max(); z0, z1 = bras[:, 2].min(), bras[:, 2].max()
        def ext(sel, key):
            p = hras[sel]; return p[np.argmax(key(p))] if len(p) else None
        near_mid = np.abs(hras[:, 0] - midx) < 4
        lm_pts = {"A": ext(near_mid & (np.abs(hras[:, 2] - (z0 + 0.6*(z1 - z0))) < 4), lambda p: p[:, 1]),
                  "B": ext(near_mid & (np.abs(hras[:, 1] - (y0 + 0.45*(y1 - y0))) < 4), lambda p: p[:, 2]),
                  "C": ext(near_mid & (np.abs(hras[:, 2] - (z0 + 0.45*(z1 - z0))) < 4), lambda p: -p[:, 1]),
                  "D": ext((np.abs(hras[:, 1] - (y0 + 0.74*(y1 - y0))) < 4) & (np.abs(hras[:, 2] - (z0 + 0.45*(z1 - z0))) < 4), lambda p: SIGN*p[:, 0]),
                  "E": ext((np.abs(hras[:, 1] - (y0 + 0.42*(y1 - y0))) < 4) & (np.abs(hras[:, 2] - (z0 + 0.28*(z1 - z0))) < 4), lambda p: SIGN*p[:, 0])}
        hc = hras.mean(0)
        old = slicer.util.getFirstNodeByName("方位点")
        if old: slicer.mrmlScene.RemoveNode(old)
        mk = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "方位点")
        for lbl, p in lm_pts.items():
            if p is None: continue
            q = p + 8*(p - hc)/np.linalg.norm(p - hc); i_ = mk.AddControlPoint(*q); mk.SetNthControlPointLabel(i_, lbl)
        dnm = mk.GetDisplayNode(); dnm.SetSelectedColor(0.1, 0.1, 0.1); dnm.SetColor(0.1, 0.1, 0.1); dnm.SetGlyphScale(3); dnm.SetTextScale(7)
        mk.SetLocked(True)
        # 原来的半透明脑模型藏起来，换成真实皮层
        for nd in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            if nd.GetName() == "brain": nd.GetDisplayNode().SetVisibility(False)
        lm = slicer.app.layoutManager(); lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
        vn = lm.threeDWidget(0).mrmlViewNode(); v3 = lm.threeDWidget(0).threeDView()
        vn.SetBackgroundColor(1, 1, 1); vn.SetBackgroundColor2(1, 1, 1); vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
        vn.SetOrientationMarkerType(slicer.vtkMRMLAbstractViewNode.OrientationMarkerTypeHuman)
        vn.SetOrientationMarkerSize(slicer.vtkMRMLAbstractViewNode.OrientationMarkerSizeMedium)
        cap = ScreenCapture.ScreenCaptureLogic()
        def shoot(direction, fname, dist=420, up=(0, 0, 1)):
            cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(vn)
            cam.SetFocalPoint(*entry); cam.SetPosition(*(entry + direction*dist)); cam.SetViewUp(*up)
            cam.ResetClippingRange(); slicer.app.processEvents(); cap.captureImageFromView(v3, D + fname); log("saved", fname)
        def show(prefixes, on):
            for nd in slicer.util.getNodesByClass("vtkMRMLModelNode"):
                if nd.GetName().startswith(tuple(prefixes)): nd.GetDisplayNode().SetVisibility(on)
        tumor = [n for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode") if n.GetName() == "tumor"]
        # 图 1 手术视角：头皮颅骨不透明、开窗，皮层不透明，只看露出的皮层上的电极片和目标
        show(["Targets_out", "EntryMap_", "Window_edge"], False); show(["Targets_stim", "Targets_rec"], True)
        for nd in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if "_Plan_" in nd.GetName(): nd.GetDisplayNode().SetVisibility(True)
        for t in tumor: t.GetDisplayNode().SetVisibility(False)
        for nd in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if nd.GetName().startswith("tract_"): nd.GetDisplayNode().SetVisibility(False)
        up = np.array([0, 0, 1.0]); up = up - (up @ nrm)*nrm; up /= np.linalg.norm(up)
        shoot(nrm, f"{CASE}_真实_手术视角_{tag}.png", dist=460, up=up)
        # 图 2 内部结构：去掉颅骨、头皮，皮层半透明，显示肿瘤、纤维束、电极片
        scalpS.GetDisplayNode().SetVisibility(False); mk.GetDisplayNode().SetVisibility(False)
        skull.GetDisplayNode().SetVisibility(False); cortex.GetDisplayNode().SetOpacity3D(0.28)
        for t in tumor: t.GetDisplayNode().SetVisibility(True)
        for nd in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if nd.GetName().startswith("tract_"): nd.GetDisplayNode().SetVisibility(True)
        show(["Targets_stim", "Targets_rec"], False)
        lat = np.array([SIGN*1.0, 0, 0.35]); lat /= np.linalg.norm(lat)
        shoot(lat, f"{CASE}_真实_内部结构_{tag}.png", dist=480)
        # 图 3（只做一次）：整个头，开窗位置
        if tag == "3x7":
            mk.GetDisplayNode().SetVisibility(True)
            skull.GetDisplayNode().SetVisibility(True); skull.GetDisplayNode().SetOpacity3D(1.0); cortex.GetDisplayNode().SetOpacity3D(1.0)
            for t in tumor: t.GetDisplayNode().SetVisibility(False)
            for nd in slicer.util.getNodesByClass("vtkMRMLModelNode"):
                if nd.GetName().startswith("tract_") or "_Plan_" in nd.GetName(): nd.GetDisplayNode().SetVisibility(False)
            shoot(lat, f"{CASE}_真实_开颅位置.png", dist=640)
        # 存场景前恢复成“手术视角”的显示状态：示意颅骨开窗、皮层不透明、电极片和目标都显示
        skull.GetDisplayNode().SetVisibility(True); skull.GetDisplayNode().SetOpacity3D(1.0); cortex.GetDisplayNode().SetOpacity3D(1.0)
        mk.GetDisplayNode().SetVisibility(True)
        for nd in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if "_Plan_" in nd.GetName() or nd.GetName().startswith(("Targets_stim", "Targets_rec", "tract_")): nd.GetDisplayNode().SetVisibility(True)
        slicer.util.saveScene(D + f"{CASE}_{tag}_规划场景.mrb"); log("scene updated", tag)
except Exception:
    traceback.print_exc()
slicer.app.quit()
