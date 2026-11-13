import os
CASE = os.environ.get("CASE", "0007")                 # case ID
SIGN = -1 if os.environ.get("SIDE", "R") == "L" else 1  # tumour in the left (L) or right (R) hemisphere
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work"))   # ASCII-only work folder (Slicer CLI modules reject non-ASCII paths)
SCRIPTS = os.environ.get("SCRIPTS", os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ".")
D = os.path.join(WORK, "w" + CASE) + "/"
import slicer, vtk, numpy as np, traceback
def log(*a): print("LOG", *a, flush=True)
try:
    dti = slicer.util.loadVolume(D + CASE + "_DTI.nrrd")
    fa = slicer.util.loadVolume(D + CASE + "_FA.nrrd")
    base = slicer.util.loadVolume(D + CASE + "_Baseline.nrrd")
    tf = slicer.util.loadTransform(D + CASE + "_DWI_to_T1c.h5")
    T = slicer.util.arrayFromVolume(dti)          # k,j,i,3,3
    F = slicer.util.arrayFromVolume(fa)
    B = slicer.util.arrayFromVolume(base)
    mf = vtk.vtkMatrix4x4(); dti.GetMeasurementFrameMatrix(mf); MF = slicer.util.arrayFromVTKMatrix(mf)[:3, :3]
    m = vtk.vtkMatrix4x4(); base.GetIJKToRASMatrix(m); M = slicer.util.arrayFromVTKMatrix(m)
    from scipy import ndimage
    brain = B > 0.2 * np.percentile(B, 99)
    brain = ndimage.binary_fill_holes(ndimage.binary_opening(brain, iterations=2))
    lab_, n_ = ndimage.label(brain); brain = lab_ == (np.bincount(lab_.ravel())[1:].argmax() + 1)
    log('brain voxels', int(brain.sum()))
    idx = np.argwhere(brain & (F > 0.25))                   # k,j,i
    ras = (M @ np.c_[idx[:, ::-1], np.ones(len(idx))].T)[:3].T
    bidx = np.argwhere(brain); bras = (M @ np.c_[bidx[:, ::-1][::50], np.ones(len(bidx[::50]))].T)[:3].T
    mid, zc = np.median(bras[:, 0]), np.median(bras[:, 2])
    log("midline x", round(mid, 1), "zc", round(zc, 1), "FA>0.25 voxels", len(idx))
    Tv = T[idx[:, 0], idx[:, 1], idx[:, 2]]
    w, v = np.linalg.eigh(Tv); e1 = v[:, :, 2] @ MF.T     # principal eigenvector in RAS
    e1 = np.abs(e1); fv = F[idx[:, 0], idx[:, 1], idx[:, 2]]
    dx = SIGN*(ras[:, 0] - mid); z = ras[:, 2] - zc
    sel = {
        "CST": (fv > float(os.environ.get("CST_SEED_FA", 0.35))) & (e1[:, 2] > 0.85) & (dx > 8) & (dx < 30) & (z > -15) & (z < 20),
        "AF":  (fv > float(os.environ.get("AF_SEED_FA", 0.25))) & (e1[:, 1] > 0.70) & (dx > 22) & (dx < 48) & (z > -5) & (z < 30),
    }
    import os
    ONLY = os.environ.get("ONLY")
    for name, s in sel.items():
        if ONLY and name != ONLY: continue
        log(name, "seed voxels", int(s.sum()))
        L = np.zeros(F.shape, np.uint8); k = idx[s]; L[k[:, 0], k[:, 1], k[:, 2]] = 1
        lab = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "seed_" + name)
        lab.CopyOrientation(base); slicer.util.updateVolumeFromArray(lab, L)
        fb = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLFiberBundleNode", "fb_" + name)
        r = slicer.cli.runSync(slicer.modules.tractographylabelmapseeding, None, {
            "InputVolume": dti.GetID(), "InputROI": lab.GetID(), "OutputFibers": fb.GetID(),
            "StoppingValue": float(os.environ.get("CST_STOP_FA", 0.15)) if name == "CST" else float(os.environ.get("AF_STOP_FA", 0.08)), "ClTh": 0.2 if name == "CST" else 0.08, "MinimumLength": 40 if name == "CST" else 25, "SeedSpacing": 1 if name == "CST" else 0.5})
        pd = fb.GetPolyData(); log(name, "status", r.GetStatusString(), "raw fibers", pd.GetNumberOfLines() if pd else 0)
        P = vtk.util.numpy_support.vtk_to_numpy(pd.GetPoints().GetData())
        keep = vtk.vtkCellArray(); lines = pd.GetLines(); lines.InitTraversal(); ids = vtk.vtkIdList(); n = 0
        while lines.GetNextCell(ids):
            pid = [ids.GetId(i) for i in range(ids.GetNumberOfIds())]; q = P[pid]
            qx = SIGN*(q[:, 0] - mid); qz = q[:, 2] - zc
            if name == "CST":
                ok = qz.min() < -25 and qz.max() > 30 and qx.mean() > 0
            else:
                ok = np.ptp(q[:, 1]) > 30 and qx.mean() > 15 and np.ptp(q[:, 1]) > np.ptp(q[:, 2])
            if ok: keep.InsertNextCell(ids); n += 1
        out = vtk.vtkPolyData(); out.SetPoints(pd.GetPoints()); out.SetLines(keep)
        cl = vtk.vtkCleanPolyData(); cl.SetInputData(out); cl.Update()
        md = slicer.modules.models.logic().AddModel(cl.GetOutput()); md.SetName("tract_" + name)
        md.SetAndObserveTransformNodeID(tf.GetID()); md.HardenTransform()
        slicer.util.saveNode(md, D + CASE + f"_tract_{name}.vtk")
        log(name, "kept fibers", n)
        if name == "AF":
            ys=[]; lines.InitTraversal()
            while lines.GetNextCell(ids):
                q=P[[ids.GetId(i) for i in range(ids.GetNumberOfIds())]]; ys.append((np.ptp(q[:,1]), np.ptp(q[:,2]), (q[:,0]-mid).mean()))
            ys=np.array(ys); log("AF y-ext pct", np.percentile(ys[:,0],[50,90,99]).round(1), "z-ext pct", np.percentile(ys[:,1],[50,90]).round(1), "lat pct", np.percentile(ys[:,2],[10,50,90]).round(1))
except Exception:
    traceback.print_exc()
slicer.app.quit()
