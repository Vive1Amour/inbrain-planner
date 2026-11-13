import os
CASE = os.environ.get("CASE", "0007")                 # case ID
SIGN = -1 if os.environ.get("SIDE", "R") == "L" else 1  # tumour in the left (L) or right (R) hemisphere
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work"))   # ASCII-only work folder (Slicer CLI modules reject non-ASCII paths)
SCRIPTS = os.environ.get("SCRIPTS", os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ".")
D = os.path.join(WORK, "w" + CASE) + "/"
import slicer, vtk, numpy as np, os, traceback
def log(*a):
    print("LOG", *a, flush=True)
try:
    import SimpleITK as sitk
    arr = sitk.GetArrayFromImage(sitk.ReadImage(D + CASE + "_DWI.nii.gz"))   # t,z,y,x
    log("4D shape", arr.shape, arr.dtype)
    ref = slicer.util.loadVolume(D + CASE + "_DWI.nii.gz", {"name": "ref"})
    dwi = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLDiffusionWeightedVolumeNode", "DWI")
    dwi.CopyOrientation(ref)
    slicer.util.updateVolumeFromArray(dwi, np.ascontiguousarray(np.moveaxis(arr, 0, -1)).astype(np.float32))
    m = vtk.vtkMatrix4x4(); ref.GetIJKToRASMatrix(m); A = slicer.util.arrayFromVTKMatrix(m)[:3, :3]
    R = A / np.linalg.norm(A, axis=0)
    bv = np.loadtxt(D + CASE + "_DWI.bvec"); bv = bv if bv.shape[0] == 3 else bv.T
    bval = np.loadtxt(D + CASE + "_DWI.bval")
    if np.linalg.det(A) > 0: bv[0] *= -1          # FSL convention
    g = (R @ bv).T
    flip = open(D + "flip.txt").read().strip() if os.path.exists(D + "flip.txt") else os.environ.get("FLIP", "z")
    if flip in "xyz" and flip: g[:, "xyz".index(flip)] *= -1     # gradient flip axis found by s0_flip.py
    log("gradient flip", flip)
    ga = vtk.vtkDoubleArray(); ga.SetNumberOfComponents(3)
    for q in g: ga.InsertNextTuple3(*q)
    ba = vtk.vtkDoubleArray()
    for q in bval: ba.InsertNextValue(float(q))
    dwi.SetDiffusionGradients(ga); dwi.SetBValues(ba)
    I = vtk.vtkMatrix4x4(); dwi.SetMeasurementFrameMatrix(I)
    dwi.CreateDefaultDisplayNodes()
    slicer.mrmlScene.RemoveNode(ref)
    log("det", round(float(np.linalg.det(A)), 3), "nonzero b", int((bval > 50).sum()))
    log("dwi class", dwi.GetClassName(), dwi.GetImageData().GetDimensions() if dwi.GetImageData() else None)
    t1c = slicer.util.loadVolume(D + CASE + "_T1c_bias.nii.gz")
    # tensor
    cli = slicer.cli.createNode(slicer.modules.dwitodtiestimation)
    names = [cli.GetParameterName(g, p) for g in range(cli.GetNumberOfParameterGroups()) for p in range(cli.GetNumberOfParametersInGroup(g))]
    log("dwitodti params", names)
    dti = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLDiffusionTensorVolumeNode", "DTI")
    base = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Baseline")
    p = {"inputVolume": dwi.GetID(), "outputTensor": dti.GetID(), "outputBaseline": base.GetID()}
    r = slicer.cli.runSync(slicer.modules.dwitodtiestimation, None, p)
    log("dti status", r.GetStatusString())
    fa = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "FA")
    r = slicer.cli.runSync(slicer.modules.diffusiontensorscalarmeasurements, None,
                           {"inputVolume": dti.GetID(), "outputScalar": fa.GetID(), "operation": "FractionalAnisotropy"})
    log("fa status", r.GetStatusString(), "FA max", float(slicer.util.arrayFromVolume(fa).max()))
    # register Baseline -> T1c (rigid)
    import os
    if os.path.exists(D + CASE + '_DWI_to_T1c.h5'):
        for n_, f_ in [(dti, CASE + '_DTI.nrrd'), (base, CASE + '_Baseline.nrrd'), (fa, CASE + '_FA.nrrd')]: slicer.util.saveNode(n_, D + f_)
        log('saved without re-registration')
    else:
      import Elastix
      el = Elastix.ElastixLogic()
      preset = [q for q in el.getRegistrationPresets() if q.getID() == "default-rigid"][0]
      tf = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", "DWI_to_T1c")
      el.registerVolumes(t1c, base, parameterFilenames=preset.getParameterFiles(), outputTransformNode=tf)
      log("elastix done")
      for n, f in [(dti, CASE + "_DTI.nrrd"), (base, CASE + "_Baseline.nrrd"), (fa, CASE + "_FA.nrrd"), (tf, CASE + "_DWI_to_T1c.h5")]:
          slicer.util.saveNode(n, D + f); log("saved", f)
except Exception:
    traceback.print_exc()
slicer.app.quit()
