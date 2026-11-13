# Step 1b: resample FA from DWI space onto the T1c grid with the Elastix displacement field; saves .npy for the registration check figure (s1c_regcheck.py)
# Run after s1 (tensor + Elastix registration). BRAINSResample does not accept DisplacementFieldTransform, so SimpleITK bundled with Slicer is used
import os
CASE = os.environ.get("CASE", "0007")
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work")); D = os.path.join(WORK, "w" + CASE) + "/"
import numpy as np, SimpleITK as sitk, traceback
def log(*a): print("LOG", *a, flush=True)
try:
    t1 = sitk.ReadImage(D + CASE + "_T1c_bias.nii.gz")
    fa = sitk.ReadImage(D + CASE + "_FA.nrrd")
    tfp = D + CASE + "_DWI_to_T1c.h5"
    if os.path.exists(tfp):
        tf = sitk.ReadTransform(tfp)                     # registration transform: T1c space -> DWI space
        res = sitk.Resample(fa, t1, tf, sitk.sitkLinear, 0.0, sitk.sitkFloat32)
        log("resampled with", tf.GetName())
    else:
        res = sitk.Resample(fa, t1); log("no registration file, resampling onto the T1c grid only")
    A = sitk.GetArrayFromImage(res)
    np.save(D + CASE + "_FA_T1c.npy", A.astype(np.float32))
    log("saved FA npy", A.shape, "max", round(float(A.max()), 3))
except Exception:
    traceback.print_exc()

import slicer as _s
_s.app.quit()
