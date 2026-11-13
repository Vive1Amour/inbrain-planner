#!/bin/bash
# 一个病例从原始 NIfTI 跑到放置计划和带图例的图
# 用法：bash run_case.sh 0007 R      （第二个参数：肿瘤在 L 左 / R 右半球）
# 运行前关掉自己开着的 Slicer 窗口里没保存的东西；第 3 步会短暂弹出 Slicer 窗口截图，自己会关
set -uo pipefail
CASE=${1:?病例号，如 0007}; SIDE=${2:-R}
SLICER=/Applications/Slicer.app/Contents/MacOS/Slicer
PY=${PY:-$HOME/.venvs/ds/bin/python}
HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="${DATA:-$(cd "$HERE/../../../../../UCSF-PDGM_Dataset" && pwd)}"      # dataset folder (set DATA to override)
WORK=${WORK:-$HOME/slicer_work}                          # 必须是纯英文路径
W="$WORK/w$CASE"; OUT="$DATA/分析/UCSF-PDGM-${CASE}_Slicer"
N="$DATA/UCSF-PDGM-${CASE}_nifti/UCSF-PDGM-${CASE}"
mkdir -p "$W" "$OUT"
export CASE SIDE WORK SCRIPTS="$HERE" OUT

echo "== 0 准备：复制并改名到 $W"
cp -n "${N}_DTI_eddy_noreg.nii.gz" "$W/${CASE}_DWI.nii.gz"
cp -n "$DATA/UCSF-PDGM_DTI.bval" "$W/${CASE}_DWI.bval"
cp -n "${N}_DTI_eddy.eddy_rotated_bvecs" "$W/${CASE}_DWI.bvec"
for k in T1c_bias FLAIR_bias tumor_segmentation brain_segmentation; do cp -n "${N}_$k.nii.gz" "$W/${CASE}_$k.nii.gz"; done

run() {  # $1 脚本  $2 额外参数（--no-main-window 或空）
  "$SLICER" --no-splash $2 --python-script "$HERE/$1" 2>&1 \
    | grep -E "^LOG|Traceback|rror:|^  File|可开颅|入口|  [-0-9.]+ \||窗口内可达|刺激目标（|记录目标（|第 [0-9]+ 次|需要放|时间估计|对照" | grep -v "while writing"
}
if [ ! -f "$W/flip.txt" ]; then echo "== s0 梯度翻转检查（约 10 min）"; run s0_flip.py --no-main-window; fi
echo "== s1 DWI → 张量、FA、配准到 T1c（翻转轴：$(cat "$W/flip.txt" 2>/dev/null)）"; run s1_dti.py --no-main-window
echo "== s2 追踪 CST、AF";                     run s2_tract.py --no-main-window
echo "== s1b FA 重采样到 T1c 网格";  run s1b_fa_to_t1c.py --no-main-window
echo "== s1c 配准检查图（轴位 T1c+FA+肿瘤）";  "$PY" -I "$HERE/s1c_regcheck.py"
echo "== s3 打分、集合覆盖、时间估计、截图";     run s3_plan_render.py ""
echo "== s3b 真实感 3D 图（皮层、示意颅骨开窗）";  run s3b_render_real.py ""
echo "== s4 图例和对比图";                      "$PY" -I "$HERE/s4_legend.py"
echo "== s5 敏感性分析";                        "$PY" -I "$HERE/s5_sensitivity.py"
echo "== s6 同任务对比（文献校准）";            "$PY" -I "$HERE/s6_same_task.py"
echo "== 结果复制到 $OUT"
cp "$W"/placement_scores_*.csv "$W"/counts_*.json "$W"/time_compare.csv "$W"/${CASE}_tract_*.vtk "$W"/${CASE}_FA.nrrd "$W"/${CASE}_*_规划场景.mrb "$OUT"/
cat "$W/time_compare.csv"
echo "== s7 整理结果文件夹（表格并成一个 Excel，图/、场景/ 分开）"; "$PY" -I "$HERE/s7_pack.py"
