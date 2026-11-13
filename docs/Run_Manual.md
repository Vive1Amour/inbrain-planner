# Electrode array placement planning: run manual (command line)

Generates all result figures from the preoperative MRI of one UCSF-PDGM case: tracts → feasible craniotomy region and window → resection boundary segments → array placement plan (per-segment decisions) → strips with the same workflow → time and cost → sensitivity analysis. Case 0007 is used as the example.

Note: the planning core `slicer_placement_score.py` and `time_model.py` are v0.3 (per-segment boundary decisions); the s4 bar chart, s5 sensitivity and s6 same-task scripts still use the v0.2 coverage model and their figures are only a historical reference. Use the plugin for v0.3 results (**Generate report** writes all tables).

GUI version: the 3D Slicer plugin in `INBRAINPlanner/`, with every parameter adjustable in the interface; see `User_Guide.md`. This manual covers the command-line version.

## 1. Environment

- 3D Slicer 5.12.4 stable (on Apple Silicon use the Intel build under Rosetta). Extensions: SlicerDMRI (DWI, tensor, FA, tracking), SlicerElastix (registration), SlicerDcm2nii (dependency of SlicerDMRI), optional LanguagePacks.
- Python 3 with Pillow, matplotlib, numpy, openpyxl (set `PY` to the interpreter; default `~/.venvs/ds/bin/python`).
- ASCII-only work folder: scripts compute in `$WORK/w<case>/` (the plugin uses `~/.inbrain_planner`) (change with `WORK`); results are copied to the `OUT` folder.
- Dataset folder: `run_case.sh` looks for the case folders and `UCSF-PDGM_DTI.bval` in `DATA` (default: `UCSF-PDGM_Dataset`, three levels up; set `DATA=/path/to/dataset` to override).

## 2. One-command run

```bash
cd INBRAIN_Planner/INBRAINPlanner/Resources/Pipeline
```

```bash
DATA=/path/to/dataset bash run_case.sh 0007 R
```

The second argument is the tumour side: `R` right, `L` left (on axial T1c, image left = patient right). The whole run takes about 20–30 minutes; a new case adds about 10 minutes for the flip check.

When only planning parameters change, skip tensor and tracts and rerun from s3:

```bash
export CASE=0007 SIDE=R WORK=~/.inbrain_planner SCRIPTS=$PWD OUT=/path/to/output/UCSF-PDGM-0007_Slicer
/Applications/Slicer.app/Contents/MacOS/Slicer --no-splash --python-script s3_plan_render.py
/Applications/Slicer.app/Contents/MacOS/Slicer --no-splash --python-script s3b_render_real.py
~/.venvs/ds/bin/python -I s4_legend.py && ~/.venvs/ds/bin/python -I s5_sensitivity.py && ~/.venvs/ds/bin/python -I s6_same_task.py && ~/.venvs/ds/bin/python -I s7_pack.py
```

## 3. Scripts and outputs

All scripts are in `INBRAINPlanner/Resources/Pipeline/`:

| Step | Script | What it does | Output |
|---|---|---|---|
| s0 | `s0_flip.py` | Tracks once each with no flip / flip x / y / z; the longest mean fibre gives the correct gradient direction | `flip.txt` |
| s1 | `s1_dti.py` | Builds the DWI node → tensor (WLS), FA → rigid registration of the baseline to T1c | `DTI.nrrd`, `FA.nrrd`, `DWI_to_T1c.h5` |
| s2 | `s2_tract.py` | Seeds chosen automatically from the principal direction, tracks CST and AF, filters by shape, transforms to T1c space | `tract_CST.vtk`, `tract_AF.vtk` |
| s1b | `s1b_fa_to_t1c.py` | Resamples FA onto the T1c grid with the Elastix displacement field (SimpleITK; BRAINSResample does not accept displacement fields) | `<case>_FA_T1c.npy` |
| s1c | `s1c_regcheck.py` | Axial registration check: T1c + FA 50% + tumour labels + tracts (drawn with Pillow, not a Slicer screenshot) | registration check PNG |
| s3 | `s3_plan_render.py` | Runs `slicer_placement_score.py` for planning, takes screenshots, saves the scene | targets, plan and feasible-region figures, `.mrb` scene |
| s3b | `s3b_render_real.py` | Realistic 3D: gyral cortex, simulated skull with bone window, landmarks A–E | craniotomy site, surgical view, internal structures |
| s4 | `s4_legend.py` | Adds legends and key numbers to screenshots; bar chart against the planner goal | figures with legends |
| s5 | `s5_sensitivity.py` | One-way tornado plot + two-way break-even plots | sensitivity figure |
| s6 | `s6_same_task.py` | Same-task comparison (calibrated to the literature) | main comparison figure (main presentation figure) |
| s7 | `s7_pack.py` | Merges tables into one Excel file and one Markdown file with links; figures to `图/`, scenes to `场景/` | `<case>_结果汇总.xlsx/.md` (results summary) |

`slicer_placement_score.py` is the planning core; `time_model.py` holds the time formulas (shared by the planning script and the sensitivity analysis). Output file names of s1c–s7 are in Chinese, as in the Chinese edition.

## 4. What to check at each step

- **s0**: the axis in `flip.txt`; z for 0007 (mean fibre 37.6 mm vs 34.3 mm unflipped).
- **s1/s1b/s1c**: the axial registration check figure (s1b resamples FA to the T1c grid, s1c draws it, s4 adds the legend): brain outline, lateral ventricles and corpus callosum should align.
- **s2**: in 3D the CST runs vertically and the AF anterior–posterior; 0007 has 61 CST and 591 AF streamlines. If a count is 0 or the direction is wrong, check s0 first, then relax seed or filter conditions.

| Tract | Seed condition | Tracking parameters | Shape filter |
|---|---|---|---|
| CST | FA > 0.35, principal direction vertical (\|z\| > 0.85), 8–30 mm from the midline, −15 to +20 mm around brain centre height | Stopping FA 0.15, min length 40 mm | From below the brainstem (< centre −25 mm) to the vertex (> +30 mm) |
| AF/SLF | FA > 0.25, principal direction anterior–posterior (\|y\| > 0.7), 22–48 mm from the midline, −5 to +30 mm around brain centre height | Stopping FA 0.08, ClTh 0.08, min length 25 mm, seed spacing 0.5 | Anterior–posterior extent > 30 mm and larger than vertical extent, mean more than 15 mm from the midline |

- **s3**: the top 5 entry points and target counts in the window printed to the console; if the entry is unreasonable, place an `Entry` point in the scene and rerun.
- **s3b**: position of the bone window relative to landmarks A forehead, B vertex, C occiput, D temple, E above the ear in the craniotomy figure.

## 5. Planning parameters (top of `slicer_placement_score.py`)

**Feasible craniotomy region and entry**

| Rule | Parameter |
|---|---|
| Tumour side only | automatic |
| No opening within 12 mm of the midline, penalty at 12–20 mm | `MIDLINE_EX`, `MIDLINE_CAUTION` |
| No opening on skull-base surfaces (outward normal z < −0.35) | `BASE_NZ` |
| No opening posterior-inferiorly (lowest 30% in height and most posterior 35%) | in code |
| Low-lateral penalty (lowest 35% in height) | `LOW_Z` |
| Entry score weights: targets 1.0, corridor length 0.7, crossing tracts 1.0, entry on functional cortex 0.5, low 0.3, near midline 0.2 | `W_E` |
| Window radius 35 mm, arrays can slide 15 mm under the bone edge | `WINDOW_R`, `SLIDE` |

Cortical envelope: brain mask closed with 6 mm + hole filling.

**Resection boundary segments (v0.3)**

- Boundary: `BND_SRC` = `core` (enhancing-core edge, default) or `flair`. Each cortical point looks `BND_DEPTH` 40 mm inward along its normal; the closest lateral distance to the tumour is `DD`; points with `0 < DD ≤ 2 mm` form the boundary line.
- Segments: farthest-point sampling along the boundary, one every `SEG_LEN` 10 mm.
- Segments needing mapping: tract-entry cortex within `RISK_D` 15 mm of the segment centre; risk = `TRACT_W` (CST 1; AF 0.5 on the right, 1 on the left, set from `SIDE`) × atlas factor.
- Decision: near the segment centre one contact with `DD ≤ EDGE_TOL` 3 mm (on the boundary) and one with `|DD − SUPRA| ≤ 3` (`SUPRA` 8 mm, outside) → fully decided; the first only → edge confirmed.
- The red/blue targets (`TRACT_NEAR`, `STIM_EDGE`, `RING`, …) are still computed but only drawn as reference patches; they do not drive selection.

**Device and placement**

| Device | Large contacts (stimulate + record) | Small contacts (record only) | Pitch | Coverage radius |
|---|---|---|---|---|
| INBRAIN (assumed from the website image) | 3 × 7 | 2 × 6 | 4 mm | large 5 mm, small 3 mm |

- One placement: centre projected onto the envelope → aligned to the normal → rotated 0–150° in 30° steps → contacts projected onto the surface. Valid if fit error ≤ 3 mm (`MAX_FIT`), whole array within window + slide range (`SLIDE`), contact-spacing strain ≤ 20% (`MAX_STRAIN`), at most 10% of large contacts over the core.
- Veins: contacts closer than `VEIN_SAFE` 3 mm to an SWI surface vein are penalised by how close they are, weight `W_VEIN_ARR` 0.2.
- Selection: greedy; each step picks the array maximising new fully decided segment risk + 0.5 × new edge-only risk − vein penalty, until nothing is gained; with `MAX_ARRAYS` > 0 exactly that many.
- Conventional strip: 1×N strip with `STRIP_N` 4 contacts, `STRIP_PITCH` 10 mm, same decision rule and greedy selection (`SPLAN`).
- Contact zones: by distance to the FLAIR border, lesion / close < 15 mm / far 15–30 mm / healthy > 30 mm (looked at within `ZONE_DEPTH` 10 mm).
- Undecided segments: `SEG_WHY` gives each its reason (outside the window view / out of reach / edge only / no valid placement / no suitable orientation / veins / placement limit) and next step.
- Order: placements with AF (awake language) → with CST (MEP under anaesthesia) → record only.
- Score first, then fit the window (`WIN_FIT`, done in the plugin, not by the command-line scripts): the window moves between the chosen arrays and its radius shrinks to 93% per step with a rerun; at least `EXPOSE_MIN` 10 mm around the tumour's projection along the view axis, a check above `EXPOSE_MAX` 30 mm.

## 6. Time-model parameters (`time_model.py`)

| Parameter | Default | Meaning |
|---|---|---|
| `T_PLACE` | 2 min | Place/move one array |
| `T_LANG` / `T_MOTOR` | 1 / 0.5 min | One language / motor site |
| `OV_PROBE` / `OV_ARRAY` | 0.3 / 0.05 min | Probe overhead per site (moving the probe, tagging) / array electronic switching |
| `T_PASSIVE` | 3 min | Passive task recording per array |
| `P_TRUE`, `SENS`, `SPEC` | 0.3, 0.95, 0.59 | Share of true language sites among candidates; passive high-γ sensitivity/specificity (Swift 2018) |
| `PASSIVE_ASLEEP` | True | Passive mapping under anaesthesia (auditory-task high γ) |
| `STRIP_N`, `STRIP_PITCH` | 4, 10 mm | 1×N strip of the conventional workflow |
| `F_CCEP`, `T_CCEP`, `CCEP_SENS` | 0.4, 4 min, 0.85 | CCEP positive share; CCEP time per array; CCEP sensitivity |
| `ASLEEP_FIRST` | True | First array placed while asleep |
| `PROBE_GRID`, `STRIP_PLACE_STD` | 10 mm, 2 | Probe grid spacing; strip placements (asleep) |
| `AWAKE_WINDOW`, `LIT_SITES` | 90 min, 13.1 | Awake window; cortical sites per patient in the literature |

Scenarios (one `_flow` function for arrays and strips):

- **INBRAIN (`MAIN`)**: CCEP + passive high-γ recording on each array asleep, suspicious contacts marked; awake, only arrays with suspicious contacts are revisited and stimulated with the array itself.
- **Conventional (`STD`)**: 1×4 strips placed with the same boundary workflow (placements from `SPLAN`), the same asleep recording screen; awake, a hand-held probe stimulates the suspicious points one by one, `T_LANG + OV_PROBE` per site.
- **Usual practice (`STD_probe`)**: no screening, hand-held probe 2 points per segment.
- **Literature average case (`STD_lit`)**: 13.1 sites per patient (Sanai 2008).

Same-task comparison (s6): area = the literature typical case (13.1 cm²) and the 1 cm grid area inside this case's window; positive rate 6%; one INBRAIN array about 6.1 cm², utilisation 0.8.

## 7. Results folder

`OUT` (`UCSF-PDGM-<case>_Slicer/`):

| Location | Content |
|---|---|
| `<case>_结果汇总.md` (results summary) | Main tables, placement plan, links to figures and scenes (read this first) |
| `<case>_结果汇总.xlsx` | All tables: notes, workflow comparison, same-task comparison, one-way sensitivity, placement scores 3x7, counts 3x7 |
| `图/` (figures) | 10 figures (listed in the summary) |
| `场景/` (scenes) | `<case>_3x7_规划场景.mrb` (planning scene), `FA.nrrd`, `tract_CST.vtk`, `tract_AF.vtk` |

Raw images stay in the dataset folder `UCSF-PDGM-<case>_nifti/` and are not copied.

Viewing in Slicer: double-click the `.mrb`; in the Data module tick `3x7_Plan_1_large`… to see each placement; `EntryMap_good/mid/poor/excluded` are the entry score point clouds; `Boundary_decided` (green, fully decided), `Boundary_edge_only` (yellow), `Boundary_open` (red, undecided), `Boundary_low_risk` (grey), `Boundary_line` (white, boundary); `Targets_stim`, `Targets_rec`, `Targets_out` (reference patches), `Window_edge` (window edge), `Entry_point` (black dot), `皮层` (cortex), `颅骨_开窗` (skull with window), `方位点` (landmarks).

## 8. A new case

1. `bash run_case.sh <case> <L/R>`.
2. Check s0–s3b as in section 4.
3. If most segments needing mapping are "outside the window view" or "out of reach", the window is off or the tumour is deep/medial; place `Entry` by hand or move the window as the next steps suggest, then rerun.
