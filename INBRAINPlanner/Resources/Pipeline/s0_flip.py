import os
CASE = os.environ.get("CASE", "0007")                 # case ID
SIGN = -1 if os.environ.get("SIDE", "R") == "L" else 1  # tumour in the left (L) or right (R) hemisphere
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work"))   # ASCII-only work folder (Slicer CLI modules reject non-ASCII paths)
SCRIPTS = os.environ.get("SCRIPTS", os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ".")
D = os.path.join(WORK, "w" + CASE) + "/"
import slicer, vtk, numpy as np, traceback
import SimpleITK as sitk
def log(*a): print("LOG", *a, flush=True)
try:
    arr = sitk.GetArrayFromImage(sitk.ReadImage(D + CASE + "_DWI.nii.gz"))
    ref = slicer.util.loadVolume(D + CASE + "_DWI.nii.gz", {"name": "ref"})
    m = vtk.vtkMatrix4x4(); ref.GetIJKToRASMatrix(m); A = slicer.util.arrayFromVTKMatrix(m)[:3, :3]
    R = A / np.linalg.norm(A, axis=0)
    bv0 = np.loadtxt(D + CASE + "_DWI.bvec"); bval = np.loadtxt(D + CASE + "_DWI.bval")
    if np.linalg.det(A) > 0: bv0[0] *= -1
    data = np.ascontiguousarray(np.moveaxis(arr, 0, -1)).astype(np.float32)
    # seeds: high-FA voxels (found with the unflipped result first)
    res = {}
    for flip in ["none", "x", "y", "z"]:
        g = (R @ bv0).T.copy()
        if flip != "none": g[:, "xyz".index(flip)] *= -1
        dwi = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLDiffusionWeightedVolumeNode", "DWI_" + flip)
        dwi.CopyOrientation(ref); slicer.util.updateVolumeFromArray(dwi, data)
        ga = vtk.vtkDoubleArray(); ga.SetNumberOfComponents(3)
        for q in g: ga.InsertNextTuple3(*q)
        ba = vtk.vtkDoubleArray()
        for q in bval: ba.InsertNextValue(float(q))
        dwi.SetDiffusionGradients(ga); dwi.SetBValues(ba); dwi.SetMeasurementFrameMatrix(vtk.vtkMatrix4x4())
        dti = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLDiffusionTensorVolumeNode", "DTI_" + flip)
        base = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "B_" + flip)
        slicer.cli.runSync(slicer.modules.dwitodtiestimation, None, {"inputVolume": dwi.GetID(), "outputTensor": dti.GetID(), "outputBaseline": base.GetID()})
        fa = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "FA_" + flip)
        slicer.cli.runSync(slicer.modules.diffusiontensorscalarmeasurements, None, {"inputVolume": dti.GetID(), "outputScalar": fa.GetID(), "operation": "FractionalAnisotropy"})
        F = slicer.util.arrayFromVolume(fa); Bv = slicer.util.arrayFromVolume(base)
        L = ((F > 0.4) & (Bv > 0.2 * np.percentile(Bv, 99))).astype(np.uint8)
        lab = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "L_" + flip)
        lab.CopyOrientation(base); slicer.util.updateVolumeFromArray(lab, L)
        fb = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLFiberBundleNode", "fb_" + flip)
        slicer.cli.runSync(slicer.modules.tractographylabelmapseeding, None, {"InputVolume": dti.GetID(), "InputROI": lab.GetID(), "OutputFibers": fb.GetID(),
            "StoppingValue": 0.15, "ClTh": 0.2, "MinimumLength": 10, "SeedSpacing": 4})
        pd = fb.GetPolyData(); P = vtk.util.numpy_support.vtk_to_numpy(pd.GetPoints().GetData())
        lines = pd.GetLines(); lines.InitTraversal(); ids = vtk.vtkIdList(); lens = []
        while lines.GetNextCell(ids):
            q = P[[ids.GetId(i) for i in range(ids.GetNumberOfIds())]]
            lens.append(np.linalg.norm(np.diff(q, axis=0), axis=1).sum())
        lens = np.array(lens)
        res[flip] = (len(lens), lens.mean() if len(lens) else 0, np.percentile(lens, 90) if len(lens) else 0)
        log("flip", flip, "fibers", res[flip][0], "mean len", round(res[flip][1], 1), "p90", round(res[flip][2], 1))
        for n in [dwi, dti, base, fa, lab, fb]: slicer.mrmlScene.RemoveNode(n)
    best = max(res, key=lambda k: res[k][1]); log("BEST", best)
    open(D + "flip.txt", "w").write(best)
except Exception:
    traceback.print_exc()
slicer.app.quit()
