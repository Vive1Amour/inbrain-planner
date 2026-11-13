# 第 1c 步：画配准检查图（轴位：T1c 背景 + FA 50% + 肿瘤标签 + 纤维束），给 s4_legend.py 加图例
# 用 ~/.venvs/ds 的 Python（numpy + Pillow），不在 Slicer 里跑；FA 由 s1b 重采样到 T1c 网格
import os, numpy as np, gzip, struct
from PIL import Image, ImageDraw

CASE = os.environ.get("CASE", "0007")
WORK = os.environ.get("WORK", os.path.expanduser("~/slicer_work")); D = os.path.join(WORK, "w" + CASE) + "/"

def read_nii(path):
    with gzip.open(path, "rb") as f:
        hdr = f.read(352)
        dim = struct.unpack("<8h", hdr[40:56])
        datatype = struct.unpack("<h", hdr[70:72])[0]
        vox_offset = int(struct.unpack("<f", hdr[108:112])[0])
        scl_slope, scl_inter = struct.unpack("<2f", hdr[112:120])
        srow = np.array(struct.unpack("<12f", hdr[280:328])).reshape(3, 4)
        shape = dim[1:1 + dim[0]]
        dt = {2: "u1", 4: "i2", 8: "i4", 16: "f4", 64: "f8", 512: "u2", 256: "i1"}[datatype]
        need = vox_offset + np.dtype(dt).itemsize * int(np.prod(shape))
        data = f.read()
        while len(data) < need:                       # 偶发短读，重来
            f.seek(0); data = f.read()
    a = np.frombuffer(data[vox_offset:vox_offset + np.dtype(dt).itemsize * int(np.prod(shape))], dtype=dt)
    a = a.reshape(shape, order="F")
    if scl_slope not in (0.0, 1.0):
        a = a.astype("f4") * scl_slope + scl_inter
    return a, srow

def read_vtk_points(path):
    data = open(path, "rb").read()
    if b"BINARY" not in data[:200]:
        raise RuntimeError("只支持二进制 vtk")
    i = data.index(b"POINTS"); j = data.index(b"\n", i) + 1
    n = int(data[i + 7:j - 1].split()[0])
    return np.frombuffer(data[j:j + n * 12], dtype=">f4").reshape(n, 3).astype(float)

T, M = read_nii(D + CASE + "_T1c_bias.nii.gz")
S, _ = read_nii(D + CASE + "_tumor_segmentation.nii.gz")
fap = D + CASE + "_FA_T1c.npy"
FA = np.load(fap).transpose(2, 1, 0) if os.path.exists(fap) else None
if FA is not None and FA.shape != T.shape:
    FA = None

core = (S == 1) | (S == 4)
k = int(np.argmax([core[:, :, q].sum() for q in range(core.shape[2])]))
t1 = T[:, :, k].astype(float)
lo, hi = np.percentile(t1[t1 > 0], [2, 99.6]) if (t1 > 0).any() else (0.0, 1.0)
g = np.clip((t1 - lo) / max(hi - lo, 1e-6), 0, 1)
rgb = np.dstack([g, g, g])
if FA is not None:
    f = np.clip(FA[:, :, k] / 0.7, 0, 1)
    head = t1 > 0.12 * np.percentile(t1[t1 > 0], 99)      # 只在头内叠 FA，避免背景噪声把画面涂灰
    f = np.where(head & (FA[:, :, k] > 0.03), f, 0.0)
    rgb = 0.55 * rgb + 0.45 * np.dstack([f, f, f])
for lab, col, al in [(2, (0.55, 0.70, 1.00), 0.35), (1, (0.90, 0.90, 0.20), 0.85), (4, (0.85, 0.10, 0.10), 0.85)]:
    mm = S[:, :, k] == lab
    if mm.any():
        for c in range(3):
            rgb[:, :, c][mm] = (1 - al) * rgb[:, :, c][mm] + al * col[c]

S_UP = 3
img = Image.fromarray((np.rot90(rgb) * 255).astype(np.uint8), "RGB").resize(
    (np.rot90(rgb).shape[1] * S_UP, np.rot90(rgb).shape[0] * S_UP), Image.LANCZOS)
dr = ImageDraw.Draw(img)
H, W = img.size[1], img.size[0]

def to_px(p):
    i = (p[0] - M[0, 3]) / M[0, 0]; j = (p[1] - M[1, 3]) / M[1, 1]; kk = (p[2] - M[2, 3]) / M[2, 2]
    # np.rot90 后：列 = i，行 = (n-1-j)
    return i * S_UP, (T.shape[1] - 1 - j) * S_UP, kk

for name, col in [("CST", (40, 90, 255)), ("AF", (25, 190, 65))]:
    p = D + CASE + f"_tract_{name}.vtk"
    if not os.path.exists(p):
        continue
    P = read_vtk_points(p)
    P = P * np.array([-1, -1, 1])                 # vtk 文件是 LPS
    IJK = np.c_[P[:, 0], P[:, 1], P[:, 2]]
    for q in IJK[::2]:
        x, y, kk = to_px(q)
        if abs(kk - k) <= 2.0 and 0 <= x < W and 0 <= y < H:
            dr.ellipse((x - 2, y - 2, x + 2, y + 2), fill=col)

out = D + CASE + "_轴位_配准检查_T1c+FA+纤维束.png"
img.save(out)
print("LOG saved", os.path.basename(out), img.size, "slice k", k)
