# 不依赖界面的逻辑：准备工作目录、检查输入、载入、颅骨、图谱配准、跑规划、脑移位 / GUI-independent logic
import os, re, io, json, shutil, contextlib, glob
import qt, vtk, slicer
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleLogic
from INBRAINPlannerLib.i18n import *
from INBRAINPlannerLib.config import *

class INBRAINPlannerLogic(ScriptedLoadableModuleLogic):
    """不依赖界面的部分：准备工作目录、判断侧别、跑规划。"""

    @staticmethod
    def case_id(folder):
        m = re.search(r"(\d{3,4})_nifti", os.path.basename(os.path.normpath(folder)))
        return m.group(1) if m else os.path.basename(os.path.normpath(folder))

    @staticmethod
    def find(folder, suffix):
        g = sorted(glob.glob(os.path.join(folder, "*" + suffix)))
        return g[0] if g else None

    def find_up(self, folder, suffix):
        """在病例文件夹、上级、上上级和本项目的 UCSF-PDGM_Dataset/ 里找（UCSF-PDGM 的 bval 放在数据集根目录）"""
        f = os.path.normpath(folder)
        for d in [f, os.path.dirname(f), os.path.dirname(os.path.dirname(f)), os.path.normpath(os.path.join(HERE, "..", "..", "..", "UCSF-PDGM_Dataset"))]:
            r = self.find(d, suffix)
            if r: return r
        return None

    def prepare(self, folder, work, case):
        """把需要的文件复制并改名到纯英文工作目录。返回 (工作目录, 缺的文件列表)"""
        D = os.path.join(work, "w" + case); os.makedirs(D, exist_ok=True)
        parent = os.path.dirname(os.path.normpath(folder))
        need = {
            f"{case}_DWI.nii.gz": self.find(folder, "_DTI_eddy_noreg.nii.gz"),
            f"{case}_DWI.bval": self.find_up(folder, ".bval"),
            f"{case}_DWI.bvec": self.find(folder, "eddy_rotated_bvecs") or self.find(folder, ".bvec") or self.find(parent, "_DTI.bvec"),
            f"{case}_T1c_bias.nii.gz": self.find(folder, "_T1c_bias.nii.gz") or self.find(folder, "_T1c.nii.gz"),
            f"{case}_FLAIR_bias.nii.gz": self.find(folder, "_FLAIR_bias.nii.gz") or self.find(folder, "_FLAIR.nii.gz"),
            f"{case}_tumor_segmentation.nii.gz": self.find(folder, "_tumor_segmentation.nii.gz"),
            f"{case}_brain_segmentation.nii.gz": self.find(folder, "_brain_segmentation.nii.gz"),
        }
        self.notes = []
        if not need[f"{case}_DWI.bval"] and need[f"{case}_DWI.nii.gz"]:
            # UCSF-PDGM 全数据集共用一份 bval：1 个 b=0 + 55 个 b=2000。找不到时按标准值生成
            import SimpleITK as sitk
            n = sitk.ReadImage(need[f"{case}_DWI.nii.gz"]).GetSize()[3] if len(sitk.ReadImage(need[f"{case}_DWI.nii.gz"]).GetSize()) == 4 else 56
            fn = os.path.join(D, f"{case}_DWI.bval")
            open(fn, "w").write(" ".join(["0"] + ["2000"]*(n - 1)) + "\n")
            need[f"{case}_DWI.bval"] = fn
            self.notes.append(L(f"没找到 bval 文件，按 UCSF-PDGM 标准生成：1 个 b=0 + {n-1} 个 b=2000",
                                f"No bval file found; generated the UCSF-PDGM standard: 1 b=0 + {n-1} b=2000"))
        swi = self.find(folder, "_SWI_bias.nii.gz") or self.find(folder, "_SWI.nii.gz")     # 可选：表面静脉避让
        if swi and not os.path.exists(os.path.join(D, f"{case}_SWI_bias.nii.gz")): shutil.copy(swi, os.path.join(D, f"{case}_SWI_bias.nii.gz"))
        missing = []
        for dst, src in need.items():
            if not src: missing.append(dst); continue
            if not os.path.exists(os.path.join(D, dst)): shutil.copy(src, os.path.join(D, dst))
        return D, missing

    @staticmethod
    def check_inputs(D, case):
        """载入前检查输入：返回 [(级别, 说明)]，级别 bad = 不能继续，warn = 能跑但结果可能不可靠。
        插件按 UCSF-PDGM / BraTS 格式写：已去颅骨、各序列在同一空间、肿瘤标签 1 坏死 / 2 水肿 / 4 或 3 强化"""
        import SimpleITK as sitk, numpy as np
        out = []
        def rd(suffix):
            fn = os.path.join(D, f"{case}_{suffix}")
            return sitk.ReadImage(fn) if os.path.exists(fn) else None
        t1, tu, br = rd("T1c_bias.nii.gz"), rd("tumor_segmentation.nii.gz"), rd("brain_segmentation.nii.gz")
        if t1 is None or tu is None or br is None:
            return [("bad", L("缺 T1c、肿瘤分割或脑分割", "T1c, tumour or brain segmentation missing"))]
        if t1.GetDimension() != 3: out.append(("bad", L("T1c 不是三维图像", "T1c is not a 3D image")))
        sp = np.array(t1.GetSpacing())
        if sp.max() > 1.5: out.append(("warn", L(f"T1c 体素 {sp.round(2).tolist()} mm，层厚 > 1.5 mm 时脑表面和距离会粗糙", f"T1c voxels {sp.round(2).tolist()} mm; above 1.5 mm the surface and distances get coarse")))
        for nm_, im in [(L("肿瘤分割", "Tumour segmentation"), tu), (L("脑分割", "Brain segmentation"), br)]:
            same = im.GetSize() == t1.GetSize() and np.allclose(im.GetOrigin(), t1.GetOrigin(), atol=1.0) and np.allclose(im.GetDirection(), t1.GetDirection(), atol=1e-3)
            if not same: out.append(("warn", nm_ + L("和 T1c 的网格不一致（尺寸、原点或方向不同），请确认已配准到 T1c", " is on a different grid from T1c (size, origin or direction); make sure it is registered to T1c")))
        lab = sitk.GetArrayFromImage(tu); u = set(int(x) for x in np.unique(lab)) - {0}
        if not u: out.append(("bad", L("肿瘤分割是空的", "Tumour segmentation is empty")))
        elif not (u & {1, 3, 4}):
            out.append(("bad", L(f"肿瘤分割里只有标签 {sorted(u)}，没有核心（1 坏死 / 4 或 3 强化）。请按 BraTS 格式标注", f"Tumour labels {sorted(u)} contain no core (1 necrosis / 4 or 3 enhancing); please use BraTS labels")))
        elif u - {1, 2, 3, 4}:
            out.append(("warn", L(f"肿瘤分割里有非 BraTS 标签 {sorted(u - {1, 2, 3, 4})}，这些体素只算作病灶", f"Non-BraTS labels {sorted(u - {1, 2, 3, 4})} are treated as lesion only")))
        if 2 not in u: out.append(("warn", L("没有水肿/FLAIR 标签 2：记录目标、触点分区和 FLAIR 边界会不完整", "No oedema/FLAIR label 2: recording targets, zoning and the FLAIR boundary will be incomplete")))
        b = sitk.GetArrayFromImage(br)
        if not (b > 0).any(): out.append(("bad", L("脑分割是空的", "Brain segmentation is empty")))
        elif (b > 0).mean() > 0.6: out.append(("warn", L("脑分割占了大半个图像，可能没去颅骨或分割的是整个头", "Brain mask covers most of the image; the skull may not have been removed")))
        return out

    @staticmethod
    def detect_side(D, case):
        """肿瘤核心质心在脑中线哪一侧（SimpleITK 用 LPS：x 大 = 病人左）"""
        import SimpleITK as sitk, numpy as np
        def centroid(fn, sel):
            im = sitk.ReadImage(fn); a = sitk.GetArrayFromImage(im); idx = np.argwhere(sel(a))[:, ::-1].astype(float)
            c = idx.mean(0); return np.array(im.TransformContinuousIndexToPhysicalPoint(c.tolist()))
        t = centroid(os.path.join(D, f"{case}_tumor_segmentation.nii.gz"), lambda a: (a == 1) | (a == 4) | (a == 3))
        b = centroid(os.path.join(D, f"{case}_brain_segmentation.nii.gz"), lambda a: a > 0)
        INBRAINPlannerLogic.side_dx = float(abs(t[0] - b[0]))          # 离中线多远：太近说明可能是中线/双侧肿瘤
        return "L" if t[0] > b[0] else "R"

    def load(self, D, case, cb=None):
        """把 T1c、分割、纤维束载入场景；cb(0–1, 说明) 报进度"""
        cb = cb or (lambda *a: None)
        cb(0.05, "T1c"); t1c = slicer.util.loadVolume(os.path.join(D, f"{case}_T1c_bias.nii.gz"))
        cb(0.20, L("脑分割", "Brain segmentation")); brain = slicer.util.loadLabelVolume(os.path.join(D, f"{case}_brain_segmentation.nii.gz"))
        cb(0.30, L("肿瘤分割", "Tumour segmentation")); tumor = slicer.util.loadLabelVolume(os.path.join(D, f"{case}_tumor_segmentation.nii.gz"))
        cb(0.40, L("肿瘤三维表面", "Tumour 3D surface"))
        seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "tumor")
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(tumor, seg)
        seg.CreateClosedSurfaceRepresentation(); S = seg.GetSegmentation()
        for i in range(S.GetNumberOfSegments()):
            sg = S.GetNthSegment(i); nm = sg.GetName()
            sg.SetColor(*{"1": (0.9, 0.9, 0.2), "2": (0.80, 0.75, 0.95), "3": (0.50, 0.06, 0.12), "4": (0.50, 0.06, 0.12)}.get(nm[-1], (1, 1, 1)))
            seg.GetDisplayNode().SetSegmentOpacity3D(S.GetNthSegmentID(i), 0.12 if nm.endswith("2") else 0.9)
        cb(0.60, L("脑三维表面", "Brain 3D surface"))
        bseg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "brain")
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(brain, bseg)
        bseg.CreateClosedSurfaceRepresentation(); bseg.GetDisplayNode().SetOpacity3D(0.5); bseg.GetDisplayNode().SetVisibility2D(False)
        bseg.GetSegmentation().GetNthSegment(0).SetColor(0.85, 0.78, 0.72)
        swi_fn = os.path.join(D, f"{case}_SWI_bias.nii.gz")
        if not os.path.exists(swi_fn) and getattr(self, "case_folder", None):
            src = self.find(self.case_folder, "_SWI_bias.nii.gz") or self.find(self.case_folder, "_SWI.nii.gz")
            if src: shutil.copy(src, swi_fn)
        if os.path.exists(swi_fn):
            cb(0.80, "SWI"); slicer.util.loadVolume(swi_fn, {"show": False})
        tracts = []; cb(0.85, L("纤维束", "Tracts"))
        for name, col in [("CST", (0.0, 0.72, 0.72)), ("AF", (0.85, 0.30, 0.75))]:
            fn = os.path.join(D, f"{case}_tract_{name}.vtk")
            if os.path.exists(fn):
                md = slicer.util.loadModel(fn); md.SetName("tract_" + name)
                try:
                    n0, nr = self.clip_tract(md, brain)
                    if nr: print(f"tract {name}: clipped {nr}/{n0} points outside the brain mask")
                except Exception as e: print("tract clip:", e)
                dn = md.GetDisplayNode(); dn.SetColor(*col); dn.SetScalarVisibility(False); dn.SetLineWidth(2); tracts.append(name)
        slicer.util.setSliceViewerLayers(background=t1c, label=tumor); cb(1.0, L("完成", "Done"))
        return tracts

    @staticmethod
    def clip_tract(md, brain, margin=1.0, min_pts=5):
        """Clip a tract to the brain mask (grown by margin mm): tracking stops on FA only and registration is imperfect,
        so a few streamlines poke out of the brain surface. Lines are cut at points outside the mask; pieces shorter
        than min_pts points are dropped. Returns (points before, points removed)"""
        import numpy as np
        from scipy import ndimage
        from vtk.util import numpy_support as nps
        pd = md.GetPolyData()
        if pd is None or pd.GetNumberOfPoints() == 0: return 0, 0
        B = slicer.util.arrayFromVolume(brain) > 0
        dist = ndimage.distance_transform_edt(~B, sampling=np.array(brain.GetSpacing())[::-1])
        m = vtk.vtkMatrix4x4(); brain.GetRASToIJKMatrix(m); R2I = slicer.util.arrayFromVTKMatrix(m)
        P = nps.vtk_to_numpy(pd.GetPoints().GetData())
        ijk = np.rint((R2I @ np.c_[P, np.ones(len(P))].T)[:3].T).astype(int)
        inb = np.all((ijk >= 0) & (ijk < np.array(B.shape[::-1])), axis=1)
        ok = np.zeros(len(P), bool); ijk = np.clip(ijk, 0, np.array(B.shape[::-1]) - 1)
        ok[inb] = dist[ijk[inb, 2], ijk[inb, 1], ijk[inb, 0]] <= margin
        if ok.all(): return len(P), 0
        lines = vtk.vtkCellArray(); ids = vtk.vtkIdList(); kept = 0
        pd.GetLines().InitTraversal()
        while pd.GetLines().GetNextCell(ids):
            run = []
            for k in range(ids.GetNumberOfIds()):
                pid = ids.GetId(k)
                if ok[pid]: run.append(pid); continue
                if len(run) >= min_pts:
                    lines.InsertNextCell(len(run)); [lines.InsertCellPoint(q) for q in run]; kept += len(run)
                run = []
            if len(run) >= min_pts:
                lines.InsertNextCell(len(run)); [lines.InsertCellPoint(q) for q in run]; kept += len(run)
        out = vtk.vtkPolyData(); out.SetPoints(pd.GetPoints()); out.SetLines(lines)
        cl = vtk.vtkCleanPolyData(); cl.SetInputData(out); cl.Update()
        md.SetAndObservePolyData(cl.GetOutput())
        return len(P), len(P) - kept

    # ---------------- 颅骨：有就用，没有就模拟；开颅后挖出骨窗 ----------------
    def build_skull(self, D, case, source, skull_file, s_in, s_thick, ct_hu, cb=None):
        """source：0 自动，1 用颅骨文件（CT 或颅骨分割），2 从 MRI 提取，3 模拟。返回说明文字"""
        import SimpleITK as sitk, numpy as np
        from scipy import ndimage
        cb = cb or (lambda *a: None); PAD = 24
        cb(0.05, L("读入影像", "Reading images"))
        t1 = sitk.ReadImage(os.path.join(D, f"{case}_T1c_bias.nii.gz"), sitk.sitkFloat32)
        br = sitk.ReadImage(os.path.join(D, f"{case}_brain_segmentation.nii.gz"))
        t1p = sitk.ConstantPad(t1, [PAD]*3, [PAD]*3, 0); brp = sitk.ConstantPad(br, [PAD]*3, [PAD]*3, 0)
        A = sitk.GetArrayFromImage(t1p); B = sitk.GetArrayFromImage(brp) > 0
        sp = np.array(t1p.GetSpacing())[::-1]; med = float(np.median(A[B]))
        cb(0.20, L("脑包络面", "Brain envelope"))
        r = 6; zz, yy, xx = np.ogrid[-r:r+1, -r:r+1, -r:r+1]
        env = ndimage.binary_fill_holes(ndimage.binary_closing(B, xx*xx + yy*yy + zz*zz <= r*r))
        dout = ndimage.distance_transform_edt(~env, sampling=sp)
        skull, how = None, ""
        if source in (0, 1) and skull_file and os.path.exists(skull_file):
            cb(0.45, L("读入颅骨文件", "Reading skull file"))
            img = sitk.ReadImage(skull_file, sitk.sitkFloat32)
            a = sitk.GetArrayFromImage(sitk.Resample(img, t1p, sitk.Transform(), sitk.sitkLinear, -2000.0))
            if a.max() > 500: skull = a > ct_hu; how = L(f"来自 CT（> {ct_hu:.0f} HU）", f"from CT (> {ct_hu:.0f} HU)")
            else: skull = a > 0.5; how = L("来自颅骨分割文件", "from skull segmentation file")
        elif source == 1:
            raise RuntimeError(L("选了“用颅骨文件”，但没有指定文件", "“Use skull file” selected but no file given"))
        if skull is None and source in (0, 2):
            outside = (dout > 8) & (dout < 25)
            has = float((A[outside] > 0.1*med).mean()) if outside.any() else 0.0
            if has > 0.2:      # 影像在脑外还有信号：没去颅骨，从 MRI 里提取（T1 上颅骨是暗带）
                cb(0.45, L("从 MRI 提取颅骨", "Extracting skull from MRI"))
                head = ndimage.binary_fill_holes(A > 0.12*med); lab, n = ndimage.label(head)
                if n: head = lab == (np.bincount(lab.ravel())[1:].argmax() + 1)
                sk = head & (dout > 1.5) & (dout < 15) & (A < 0.35*med)
                sk = ndimage.binary_opening(sk, iterations=1); lab, n = ndimage.label(sk)
                if n and sk.sum() > 5000:
                    skull = lab == (np.bincount(lab.ravel())[1:].argmax() + 1); how = L("从 MRI 提取（近似）", "extracted from MRI (approximate)")
            elif source == 2:
                raise RuntimeError(L("这组 MRI 已经去过颅骨，提取不到；请改用“模拟”或提供 CT", "This MRI is skull-stripped; use “Simulate” or provide a CT"))
        if skull is None:
            cb(0.45, L("模拟颅骨", "Simulating skull"))
            dsm = ndimage.gaussian_filter(dout, 1.5)
            skull = (dsm > s_in) & (dsm <= s_in + s_thick)
            how = L(f"模拟：脑表面外 {s_in:g}–{s_in + s_thick:g} mm（数据集去过颅骨）",
                    f"simulated: {s_in:g}–{s_in + s_thick:g} mm outside the brain (dataset is skull-stripped)")
        self.skull = dict(arr=skull, ref=t1p, bcen=self.ras_of(t1p, np.argwhere(B)[::50]).mean(0), how=how)
        cb(0.70, L("生成颅骨表面", "Building skull surface"))
        self.show_skull(skull, None)
        cb(1.0, L("完成", "Done")); return how

    @staticmethod
    def ras_of(img, kji):
        """sitk 图像的体素下标 (k,j,i) → RAS 坐标"""
        import numpy as np
        D_ = np.array(img.GetDirection()).reshape(3, 3); O = np.array(img.GetOrigin()); S = np.array(img.GetSpacing())
        lps = O + (kji[:, ::-1]*S) @ D_.T
        return lps*np.array([-1, -1, 1])

    def seg_from(self, arr, name, smooth=0.6):
        import SimpleITK as sitk, sitkUtils
        old = slicer.util.getFirstNodeByName(name)
        if old: slicer.mrmlScene.RemoveNode(old)
        if not arr.any(): return None
        im = sitk.GetImageFromArray(arr.astype("uint8")); im.CopyInformation(self.skull["ref"])
        lv = sitkUtils.PushVolumeToSlicer(im, None, name + "_lab", "vtkMRMLLabelMapVolumeNode")
        sg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", name)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(lv, sg)
        sg.GetSegmentation().SetConversionParameter("Smoothing factor", str(smooth))
        sg.CreateClosedSurfaceRepresentation(); slicer.mrmlScene.RemoveNode(lv)
        sg.GetDisplayNode().SetVisibility2D(False); return sg

    def show_skull(self, skull, flap):
        self.seg_from(skull, "颅骨_开窗")
        if flap is not None: self.seg_from(flap, "骨瓣")
        else:
            old = slicer.util.getFirstNodeByName("骨瓣")
            if old: slicer.mrmlScene.RemoveNode(old)

    def cut_skull(self, entry, win_sdf, nrm):
        """按规划的骨窗形状（win_sdf：到骨窗边缘的有符号距离）沿入口外法向挖掉骨瓣"""
        import numpy as np
        sk = self.skull["arr"]; idx = np.argwhere(sk); ras = self.ras_of(self.skull["ref"], idx)
        along = (ras - np.asarray(entry)) @ np.asarray(nrm)
        hole = (win_sdf(ras) < 0) & (along > -15)
        cut = sk.copy(); flap = np.zeros_like(sk); k = idx[hole]
        cut[k[:, 0], k[:, 1], k[:, 2]] = False; flap[k[:, 0], k[:, 1], k[:, 2]] = True
        self.show_skull(cut, flap)

    # ---------------- 脑区图谱：模板配准到病例（遮掉肿瘤核心），皮层点就近取脑区标签 ----------------
    def register_atlas(self, D, case, space, cb=None):
        import numpy as np
        from scipy import ndimage
        from scipy.spatial import cKDTree
        cb = cb or (lambda *a: None); at = ELOQ.get("atlas", {})
        files = {k: os.path.join(space, at.get(k, "")) for k in ["template", "cortical", "subcortical"]}
        for k, fn in files.items():
            if not os.path.exists(fn): raise RuntimeError(L(f"找不到图谱文件：{fn}", f"Atlas file not found: {fn}"))
        t1c = slicer.util.getFirstNodeByName(f"{case}_T1c_bias")
        if t1c is None: raise RuntimeError(L("先载入场景", "Load the scene first"))
        for nm in ["atlas_template", "atlas_cortical", "atlas_sub", "atlas_mask", "atlas_to_patient"]:
            nd = slicer.util.getFirstNodeByName(nm)
            if nd: slicer.mrmlScene.RemoveNode(nd)
        cb(0.05, "载入模板|Loading template")
        tpl = slicer.util.loadVolume(files["template"], {"show": False}); tpl.SetName("atlas_template")
        cort = slicer.util.loadLabelVolume(files["cortical"], {"show": False}); cort.SetName("atlas_cortical")
        sub = slicer.util.loadLabelVolume(files["subcortical"], {"show": False}); sub.SetName("atlas_sub")
        brain = ndimage.binary_dilation((slicer.util.arrayFromVolume(sub) > 0) | (slicer.util.arrayFromVolume(cort) > 0), iterations=2)
        a = slicer.util.arrayFromVolume(tpl); a[~brain] = 0; slicer.util.arrayFromVolumeModified(tpl)
        cb(0.15, "掩膜|Mask")
        bseg = [n for n in slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode") if n.GetName().endswith("brain_segmentation")]
        tseg = [n for n in slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode") if n.GetName().endswith("tumor_segmentation")]
        mask = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "atlas_mask")
        slicer.modules.volumes.logic().CreateLabelVolumeFromVolume(slicer.mrmlScene, mask, t1c)
        m = (slicer.util.arrayFromVolume(bseg[0]) > 0) if bseg else (slicer.util.arrayFromVolume(t1c) > 0)
        if tseg: m &= ~ndimage.binary_dilation(np.isin(np.rint(slicer.util.arrayFromVolume(tseg[0])), [1, 3, 4]), iterations=5)
        slicer.util.updateVolumeFromArray(mask, m.astype(np.uint8))
        cb(0.25, "刚体 + 仿射配准（约 1–2 分钟）|Rigid + affine registration (about 1–2 min)")
        tf = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "atlas_to_patient")
        prm = dict(fixedVolume=t1c.GetID(), movingVolume=tpl.GetID(), linearTransform=tf.GetID(),
                   initializeTransformMode="useMomentsAlign", useRigid=True, useAffine=True, costMetric="MMI",
                   samplingPercentage=0.02, maskProcessingMode="ROI", fixedBinaryVolume=mask.GetID())
        r = slicer.cli.runSync(slicer.modules.brainsfit, None, prm)
        if r.GetStatus() & r.ErrorsMask: raise RuntimeError(L("模板配准失败：", "Template registration failed: ") + str(r.GetErrorText())[:300])
        slicer.mrmlScene.RemoveNode(r)
        cb(0.85, "脑区标签|Region labels")
        m0 = vtk.vtkMatrix4x4(); cort.GetIJKToRASMatrix(m0); ijk2tpl = slicer.util.arrayFromVTKMatrix(m0)
        cort.SetAndObserveTransformNodeID(tf.GetID()); cort.HardenTransform()
        m1 = vtk.vtkMatrix4x4(); cort.GetIJKToRASMatrix(m1); ijk2pat = slicer.util.arrayFromVTKMatrix(m1)
        lab = slicer.util.arrayFromVolume(cort); kji = np.argwhere(lab > 0)
        ijk = np.c_[kji[:, ::-1], np.ones(len(kji))]
        self.atlas = dict(tree=cKDTree((ijk @ ijk2pat.T)[:, :3]), labels=lab[lab > 0].astype(int),
                          pat2tpl=ijk2tpl @ np.linalg.inv(ijk2pat))
        for nd in (tpl, sub, mask): slicer.mrmlScene.RemoveNode(nd)
        if cort.GetDisplayNode(): cort.GetDisplayNode().SetVisibility(False)
        cb(1.0, "完成|Done")

    def atlas_labels(self, P, maxd=8.0):
        """每个点（病例 RAS）最近的皮层图谱标签，8 mm 内没有就是 0"""
        import numpy as np
        d, i = self.atlas["tree"].query(np.asarray(P, float).reshape(-1, 3), distance_upper_bound=maxd)
        out = np.zeros(len(d), int); ok = np.isfinite(d); out[ok] = self.atlas["labels"][i[ok]]
        return out

    def atlas_mix(self, P, rad=4.0):
        """邻域脑区构成：每个触点取半径 rad mm 内的图谱体素，按比例合计（Blenkmann 2017 的做法），边界触点不会被硬分到一侧"""
        import numpy as np
        cnt = {}
        for h in self.atlas["tree"].query_ball_point(np.asarray(P, float).reshape(-1, 3), rad):
            if not h: continue
            u, c = np.unique(self.atlas["labels"][h], return_counts=True)
            for l, n in zip(u, c / c.sum()): cnt[int(l)] = cnt.get(int(l), 0.0) + float(n)
        tot = sum(cnt.values()) or 1.0
        return sorted(((l, v/tot) for l, v in cnt.items()), key=lambda x: -x[1])

    def _exec_plan(self, overrides, cb):
        src = open(os.path.join(SCRIPTS, "slicer_placement_score.py"), encoding="utf-8").read()
        g = {"__name__": "inbrain_plan", "__file__": os.path.join(SCRIPTS, "slicer_placement_score.py"), "OVERRIDES": dict(overrides, PROGRESS=cb)}
        os.environ["SCRIPTS"] = SCRIPTS
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(compile(src, "slicer_placement_score.py", "exec"), g)
        return g, buf.getvalue()

    def plan(self, D, case, overrides, cb=None):
        """跑规划核心；返回 (全局变量字典, 控制台输出)。
        WIN_FIT 打开时“先评分再定骨窗”：设定的骨窗当作最大可开范围，先在里面评分选放置；
        然后按选中的阵列把骨窗挪到它们中间、逐步缩小（半径每次 93%），每次重跑规划，
        只要判定的边界段不比第一遍少、放置次数不比第一遍多就继续缩，最后用最小的那个。"""
        fit = overrides.get("WIN_FIT", True)
        sub = (lambda a, b: (lambda fr, tx: cb(a + (b - a)*fr, tx))) if cb else (lambda a, b: None)
        g, out = self._exec_plan(overrides, sub(0.0, 0.4) if fit else cb)
        # ---- Window shape and angle from the tumour projection (non-round windows): long axis along the projection's main direction,
        #      aspect from the projection; rounded rectangle when the projection fills its box, otherwise oval; area kept (growth and
        #      fitting adjust it later); entry moved to the projection centre. Kept only if separable segments do not drop
        if overrides.get("AUTO_SHAPE", True) and g.get("PLAN") and g.get("WIN_SHAPE") != "circle":
            try: g, out = self.auto_shape(g, out, overrides)
            except Exception as e: out += f"\nauto shape: {e}"
            if g.get("AUTO_SHAPE_INFO", {}).get("params"): overrides = dict(overrides, ENTRY_NAME="_WinShapeEntry", **g["AUTO_SHAPE_INFO"]["params"])
        # ---- Target-driven window growth: if the estimated FLAIR residual of the INBRAIN workflow is above target (5 cm3), keep the entry and
        #      enlarge the window step by step; stop at the target, when one more step gains less than NCE_STEP_MIN mL, or at WIN_R_LIMIT
        nce = lambda gg: (((gg.get("BND") or {}).get("nce") or {}).get("res_inb"))
        if overrides.get("NCE_TARGET", True) and g.get("PLAN") and nce(g) is not None and nce(g) > g.get("NCE_THR", 5.0):
            lim = float(overrides.get("WIN_R_LIMIT", 50.0)); stepmin = float(overrides.get("NCE_STEP_MIN", 2.0)); cur = {}
            glog = [L(f"FLAIR 残留估计 {nce(g):.1f} mL > 目标 {g.get('NCE_THR', 5.0):g}：试着扩大骨窗（上限半径 {lim:g} mm）",
                      f"FLAIR residual {nce(g):.1f} mL > target {g.get('NCE_THR', 5.0):g}: enlarging the window (radius limit {lim:g} mm)")]
            for k in range(4):
                if g["WIN_SHAPE"] == "circle":
                    R = float(cur.get("WINDOW_R", overrides.get("WINDOW_R", g.get("WINDOW_R", 35.0)))) + 5.0
                    if R > lim + 1e-6: break
                    nw = dict(WINDOW_R=R)
                else:
                    Lw, Ww = float(cur.get("WIN_LEN", overrides.get("WIN_LEN", g.get("WIN_LEN", 80.0)))), float(cur.get("WIN_WID", overrides.get("WIN_WID", g.get("WIN_WID", 60.0))))
                    if max(Lw, Ww)*1.15/2 > lim + 1e-6: break
                    nw = dict(WIN_LEN=Lw*1.15, WIN_WID=Ww*1.15)
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "_WinGrowEntry")
                node.AddControlPointWorld(vtk.vtkVector3d(*g["entry"])); node.GetDisplayNode().SetVisibility(False)
                try: g2, out2 = self._exec_plan(dict(overrides, ENTRY_NAME="_WinGrowEntry", **dict(cur, **nw)), None)
                finally: slicer.mrmlScene.RemoveNode(node)
                r1, r2 = nce(g), nce(g2)
                ok = r2 is not None and r2 < r1 - stepmin
                c1, c2 = g["WIN_CHECK"], g2["WIN_CHECK"]
                bad = [k for k in ("contra", "base", "post") if c2.get(k) and not c1.get(k)]
                if c2.get("mid_mm", 99) < float(overrides.get("MIDLINE_EX", 12.0)) and c2.get("mid_mm", 99) < c1.get("mid_mm", 99) - 0.5: bad.append("mid")
                if bad:   # 扩大后骨窗边缘碰到禁区（对侧、颅底、横窦一带、中线旁）就不扩
                    ok = False; r2 = r2 if r2 is not None else float("nan")
                    glog.append(L("  再扩会碰到禁区（" + "、".join({"contra": "对侧", "base": "颅底", "post": "后下部/横窦", "mid": "中线旁"}[k] for k in bad) + "），停止",
                                  "  enlarging would reach an excluded zone (" + ", ".join(bad) + "), stop")); break
                glog.append(L(f"  {g2['WIN_CHECK']['area_cm2']:.0f} cm²：残留 {r2:.1f} mL，{'采用' if ok else '减少不到 ' + format(stepmin, 'g') + ' mL，停止'}",
                              f"  {g2['WIN_CHECK']['area_cm2']:.0f} cm²: residual {r2:.1f} mL, {'kept' if ok else 'gain below ' + format(stepmin, 'g') + ' mL, stop'}"))
                if not ok: break
                g, out = g2, out2; cur.update(nw)
                if r2 <= g.get("NCE_THR", 5.0): break
            g["NCE_GROW_INFO"] = dict(log=glog, params=cur)
            overrides = dict(overrides, ENTRY_NAME="_WinGrowEntry2", **cur) if cur else overrides
            if cur:
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "_WinGrowEntry2")
                node.AddControlPointWorld(vtk.vtkVector3d(*g["entry"])); node.GetDisplayNode().SetVisibility(False)
            out = out + "\n" + "\n".join(glog)
        if not fit or not g.get("PLAN"):
            for _n in ("_WinGrowEntry2", "_WinShapeEntry"):
                if slicer.mrmlScene.GetFirstNodeByName(_n): slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(_n))
            return g, out
        f0, a0 = g["BND"]["full"], g["WIN_CHECK"]["area_cm2"]; best, best_out = g, out
        log = [L(f"先评分再定骨窗（定制骨窗：以肿瘤为中心，投影外留 EXPOSE_MIN，按阵列收紧）：第 1 遍 {a0:.0f} cm²，判定段 {f0}", f"Score-then-fit window: pass 1 {a0:.0f} cm², {f0} segments decided")]
        try: nw = self.fit_window(best)                   # 先试：刚好容下第一遍的放置
        except Exception as e: nw = None; log.append(f"fit: {e}")
        for k in range(8):
            if nw is None:
                try: nw = self.fit_window(best, contacts=False, scale=0.93)   # 再试：以选中阵列为中心缩到 93%（面积约小 13%）
                except Exception as e: log.append(f"fit: {e}"); break
            if nw is None: break
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "_WinFitEntry")
            node.AddControlPointWorld(vtk.vtkVector3d(*nw.pop("entry"))); node.GetDisplayNode().SetVisibility(False)
            try: g2, out2 = self._exec_plan(dict(overrides, ENTRY_NAME="_WinFitEntry", **nw), sub(0.4 + 0.075*k, 0.475 + 0.075*k))
            finally: slicer.mrmlScene.RemoveNode(node)
            f2, a2 = g2["BND"]["full"], g2["WIN_CHECK"]["area_cm2"]
            ok = f2 >= f0 and len(g2["PLAN"]) <= len(g["PLAN"]) and a2 <= best["WIN_CHECK"]["area_cm2"] + (0.5 if k == 0 else -0.5)
            if nce(best) is not None and (nce(g2) or 0) > nce(best) + 0.5: ok = False      # 缩窗不能让 FLAIR 残留变多   # 第一次可以只转长轴不缩小，之后必须变小
            log.append(L(f"  试 {a2:.0f} cm²：判定段 {f2}，放置 {len(g2['PLAN'])} 次，{'采用' if ok else '不采用，停止'}", f"  tried {a2:.0f} cm²: {f2} segments, {len(g2['PLAN'])} placements, {'kept' if ok else 'rejected, stop'}"))
            if not ok: break
            best, best_out, nw = g2, out2, None
        for _n in ("_WinGrowEntry2", "_WinShapeEntry"):
            if slicer.mrmlScene.GetFirstNodeByName(_n): slicer.mrmlScene.RemoveNode(slicer.mrmlScene.GetFirstNodeByName(_n))
        for _k in ("NCE_GROW_INFO", "AUTO_SHAPE_INFO"):
            if _k in g and best is not g: best[_k] = g[_k]
        if best is not g:
            best["WIN_FIT_INFO"] = dict(area0=a0, area=best["WIN_CHECK"]["area_cm2"], full0=f0, full=best["BND"]["full"], n0=len(g["PLAN"]), n=len(best["PLAN"]))
        return best, best_out + "\n" + "\n".join(log)

    def auto_shape(self, g, out, overrides):
        import numpy as np
        SP, U, V, ent = g["SP"], g["WIN_U"], g["WIN_V"], np.asarray(g["entry"])
        uv = lambda P: np.c_[(np.asarray(P) - ent) @ U, (np.asarray(P) - ent) @ V]
        proj = np.where((g["DW"] <= 0) & g["VISIBLE"])[0]
        if len(proj) < 20: return g, out
        Q = uv(SP[proj]); mu = Q.mean(0)
        w, vec = np.linalg.eigh(np.cov((Q - mu).T)); ax = vec[:, -1]
        rot = float(np.arctan2(ax[1], ax[0])); rot = (rot + np.pi/2) % np.pi - np.pi/2
        c, s_ = np.cos(rot), np.sin(rot); R = np.c_[(Q - mu)[:, 0]*c + (Q - mu)[:, 1]*s_, -(Q - mu)[:, 0]*s_ + (Q - mu)[:, 1]*c]
        ext = R.max(0) - R.min(0); asp = float(np.clip(ext[0]/max(ext[1], 1e-6), 1.0, 2.0))
        try:
            from scipy.spatial import ConvexHull
            fill = ConvexHull(R).volume/max(ext[0]*ext[1], 1e-6)
        except Exception: fill = 0.7
        shape = "rect" if (fill > 0.85 and asp >= 1.2) else "ellipse"
        A0 = g["WIN_CHECK"]["area_cm2"]*100.0                          # mm², keep the area first
        k = 4/np.pi if shape == "ellipse" else 1.0
        Lw, Ww = np.sqrt(A0*k*asp), np.sqrt(A0*k/asp)
        em = 2*float(g.get("EXPOSE_MIN", 10.0)); Lw, Ww = max(Lw, ext[0] + em, 40.0), max(Ww, ext[1] + em, 40.0)
        ang = (g["WIN_ANGLE"] + np.degrees(rot) + 90) % 180 - 90; ang = float(round(ang/5)*5)
        vis = np.where(g["VISIBLE"])[0]; q = uv(SP[vis]); e = SP[vis[np.argmin(np.hypot(q[:, 0] - mu[0], q[:, 1] - mu[1]))]]
        prm = dict(WIN_SHAPE=shape, WIN_LEN=float(np.ceil(Lw)), WIN_WID=float(np.ceil(Ww)), WIN_ANGLE=ang)
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "_WinShapeEntry")
        node.AddControlPointWorld(vtk.vtkVector3d(*e)); node.GetDisplayNode().SetVisibility(False)
        g2, out2 = self._exec_plan(dict(overrides, ENTRY_NAME="_WinShapeEntry", **prm), None)
        s1, s2 = (g.get("BND") or {}).get("sep", 0), (g2.get("BND") or {}).get("sep", 0)
        nm = {"ellipse": L("卵圆", "oval"), "rect": L("圆角矩形", "rounded rectangle")}[shape]
        ok = bool(g2.get("PLAN")) and s2 >= s1
        msg = L(f"按肿瘤投影定骨窗：{nm} {prm['WIN_LEN']/10:.1f} × {prm['WIN_WID']/10:.1f} cm，长轴 {ang:g}°（投影长宽比 {asp:.1f}，填充率 {fill:.2f}）；可分离段 {s1} → {s2}，{'采用' if ok else '不采用'}",
                f"Window from tumour projection: {nm} {prm['WIN_LEN']/10:.1f} × {prm['WIN_WID']/10:.1f} cm, long axis {ang:g}° (aspect {asp:.1f}, fill {fill:.2f}); separable {s1} → {s2}, {'kept' if ok else 'rejected'}")
        if not ok:
            slicer.mrmlScene.RemoveNode(node); g["AUTO_SHAPE_INFO"] = dict(log=[msg]); return g, out + "\n" + msg
        g2["AUTO_SHAPE_INFO"] = dict(log=[msg], params=prm); return g2, out2 + "\n" + msg

    @staticmethod
    def fit_window(g, contacts=True, scale=None, step=2.0, r_min=15.0):
        """在第一遍的骨窗平面里找最小骨窗（按文献的定制骨窗原则）：
        - 肿瘤在皮层的投影全在骨窗里，外面至少留 EXPOSE_MIN（小骨窗定义 ≤ 1 cm，Carrabba 2022）；
        - 骨窗以肿瘤为中心，椭圆/矩形的长轴对齐肿瘤投影的长轴（Sughrue 2016 岛叶锁孔入路）；
        - 选中阵列的触点可以伸到边缘下 SLIDE，每片阵列中心离边缘至少 5 mm（contacts=False 时只看中心）；
        - 尽量小，但够用（Reisch 2013）。scale 给出时尺寸按当前骨窗缩小，但不小于上面要求的最小值。
        返回新入口、尺寸（和长轴方向）的覆盖参数；比当前骨窗小不了时返回 None"""
        import numpy as np
        SP, U, V, ent = g["SP"], g["WIN_U"], g["WIN_V"], g["entry"]; SL = g["SLIDE"]; shape = g["WIN_SHAPE"]
        uv = lambda P: np.c_[(np.asarray(P) - ent) @ U, (np.asarray(P) - ent) @ V]
        proj = np.where((g["DW"] <= 0) & g["VISIBLE"])[0]          # 肿瘤沿视线方向在皮层上的投影
        Q = uv(SP[proj]) if len(proj) else np.zeros((0, 2))
        rot = 0.0
        if shape != "circle" and len(Q) > 10:                     # 长轴对齐肿瘤投影的主方向
            w, vec = np.linalg.eigh(np.cov((Q - Q.mean(0)).T)); ax = vec[:, -1]
            rot = float(np.arctan2(ax[1], ax[0]))
            if rot > np.pi/2: rot -= np.pi
            if rot < -np.pi/2: rot += np.pi
        c, s_ = np.cos(rot), np.sin(rot); R2 = lambda X: np.c_[X[:, 0]*c + X[:, 1]*s_, -X[:, 0]*s_ + X[:, 1]*c]
        need, needA, arr, arrA = [], [], [], []                  # need = 肿瘤约束（决定最小尺寸），arr = 阵列约束
        if len(Q): need.append(R2(Q)); needA.append(np.full(len(Q), -float(g.get("EXPOSE_MIN", 10.0))))
        need.append(R2(uv(g["core_c"][None]))); needA.append(np.full(1, -10.0))
        for p in g["PLAN"]:
            L_ = p["r"]["L"]; c_ = np.vstack([L_, p["r"]["S"]]) if len(p["r"]["S"]) else L_
            if contacts: arr.append(R2(uv(c_))); arrA.append(np.full(len(c_), SL))
            arr.append(R2(uv(L_.mean(0, keepdims=True)))); arrA.append(np.full(1, -5.0))
        N, NA = np.vstack(need), np.concatenate(needA); P, A = np.vstack(need + arr), np.concatenate(needA + arrA)
        if shape == "circle": a0 = b0 = 1.0
        else: a0, b0 = g["WIN_LEN"]/2, g["WIN_WID"]/2
        m = min(a0, b0)
        def k_of(X, AL, cu, cv):                              # 放下这些点需要的尺寸倍数（圆：就是半径）
            du, dv = X[:, 0] - cu, X[:, 1] - cv
            if shape == "circle": return float((np.hypot(du, dv) - AL).max())
            if shape == "ellipse": d = (np.sqrt((du/a0)**2 + (dv/b0)**2) - 1)*m + m
            else: d = np.maximum(np.abs(du)/a0, np.abs(dv)/b0)*m
            return float((d - AL).max())/m
        R0 = g["WIN_RMAX"] + 20; best = None
        for cu in np.arange(-R0, R0 + 1e-6, step):
            for cv in np.arange(-R0, R0 + 1e-6, step):
                k = k_of(P, A, cu, cv)
                if best is None or k < best[0] - 1e-9: best = (k, cu, cv)
        k, cu, cv = best
        cur = g["WINDOW_R"] if shape == "circle" else 1.0
        kmin = max(k_of(N, NA, cu, cv), (r_min if shape == "circle" else r_min/m))
        if scale is not None: k = max(cur*scale, kmin)
        else: k = max(k, kmin)
        if k >= cur - (1.0 if shape == "circle" else 0.02) and abs(rot) < 0.05: return None
        k = min(k, cur)
        cw = np.array([cu*c - cv*s_, cu*s_ + cv*c])               # 旋回原平面坐标
        vis = np.where(g["VISIBLE"])[0]; q = uv(SP[vis])
        e = SP[vis[np.argmin(np.hypot(q[:, 0] - cw[0], q[:, 1] - cw[1]))]]
        nw = dict(entry=tuple(float(x) for x in e))
        if shape == "circle": nw["WINDOW_R"] = float(np.ceil(k))
        else:
            nw.update(WIN_LEN=float(np.ceil(2*k*a0)), WIN_WID=float(np.ceil(2*k*b0)))
            ang = g["WIN_ANGLE"] + np.degrees(rot); ang = (ang + 90) % 180 - 90
            nw["WIN_ANGLE"] = float(round(ang / 5) * 5)
        return nw

    @staticmethod
    def coverage(G, SP=None, Lc=None, Sc=None):
        """放置计划实际达到的覆盖：每条束刺激（加权前的点数比例）、记录。SP/Lc/Sc 给出时用移位后的坐标"""
        import numpy as np
        from scipy.spatial import cKDTree
        SP = G["SP"] if SP is None else SP
        plan = G["PLAN"]
        if Lc is None:
            Lc = np.vstack([p["r"]["L"] for p in plan]) if plan else np.zeros((0, 3))
            Sc = np.vstack([p["r"]["S"] for p in plan if len(p["r"]["S"])] or [np.zeros((0, 3))])
        S_idx, R_idx, src = G["S_idx"], G["R_idx"], G["stim_src"]
        def hit(idx, pts, rad):
            if len(idx) == 0 or len(pts) == 0: return set()
            d, _ = cKDTree(pts).query(SP[idx]); return set(np.asarray(idx)[d <= rad])
        cs = hit(S_idx, Lc, G["STIM_REACH"]); cr = hit(R_idx, Lc, G["REC_REACH_L"]) | hit(R_idx, Sc, G["REC_REACH_S"])
        # 分母和规划器一致：骨窗内且有放置能够到的目标
        out = {k: min(sum(1 for i in cs if src[i] == k) / G["cntK"][k], 1.0) for k in G["KEYS"]}
        out["rec"] = min(len(cr) / G["totRr"], 1.0)
        return out

    def shift_sim(self, G, sink, tan):
        """简化脑移位：皮层按位移场移动（骨窗中心最大，到可伸出范围边缘减到 0）。
        电极触点按术前规划的空间位置放，落到移位后皮层上最近的点；目标点跟着组织走。返回 [(名字, 覆盖字典)]"""
        import numpy as np
        from scipy.spatial import cKDTree
        SP, entry = G["SP"], np.asarray(G["entry"], float)
        n = entry - SP.mean(0); n /= np.linalg.norm(n)
        ref = np.array([0, 0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0, 0])
        e1 = np.cross(n, ref); e1 /= np.linalg.norm(e1); e2 = np.cross(n, e1)
        R = G["R_EQ"] + G["SLIDE"]
        fall = np.clip(1 - (np.linalg.norm(SP - entry, axis=1) / R)**2, 0, None)[:, None]
        plan = G["PLAN"]
        L0 = np.vstack([p["r"]["L"] for p in plan]); S0 = np.vstack([p["r"]["S"] for p in plan if len(p["r"]["S"])] or [np.zeros((0, 3))])
        rows = [(L("术前（不移位）", "Pre-op (no shift)"), self.coverage(G))]
        dirs = [(L("只下沉", "Sinking only"), np.zeros(3))]
        for k in range(8):
            a = np.radians(45*k); d = np.cos(a)*e1 + np.sin(a)*e2
            dirs.append((L(f"下沉 + 侧向 {k*45}°", f"Sink + lateral {k*45}°"), d))
        for name, d in dirs:
            SP2 = SP + fall*(-sink*n + tan*d)
            t = cKDTree(SP2)
            Lc = SP2[t.query(L0)[1]]; Sc = SP2[t.query(S0)[1]] if len(S0) else S0
            rows.append((name, self.coverage(G, SP2, Lc, Sc)))
        return rows
