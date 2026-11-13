# Changelog

## Unreleased (2026-11-09)

- New device preset “INBRAIN first-in-human device (12 large + 48 small)” (Coope 2025; layout assumed); new small-contact layouts stagger (offset as in the website photo) and dense; the photo preset now uses stagger.
- Window shape (oval / rounded rectangle), aspect and long-axis angle chosen from the tumour projection at the same area, kept only if separable segments do not drop. Case 0207: FLAIR residual 40.3 → 32.8 mL at the same 38 cm².
- Windows follow clinical practice: oval by default (long axis along the tumour projection); reports say “oval window about 8 × 6 cm, 38 cm², standard convexity flap”; area tiers (keyhole / small / standard / large / beyond usual > 80 cm² flagged red); round windows warn that exposure may be too small for mapping.
- Automatic enlargement stops at excluded zones (contralateral, midline, skull base, transverse sinus region).
- Report: figure embedded in the PDF (fixes the missing image on page 2); table headers repeat across pages; parameter snapshot with readable names, Yes/No and a meaning column.
- Target-driven window growth: with an estimated FLAIR residual above 5 cm³ the window grows around the same entry until the target, a gain below 2 mL, or the 50 mm limit; window shrinking may not increase the residual. Case 0207: window 38 → 64 cm², INBRAIN residual 40.3 → 5.1 mL (strip in the same window 30.7 mL).
- Fixed tracts poking out of the brain: on loading, tracts are clipped to the brain mask (grown by 1 mm), cut at outside points, short pieces dropped (about 2–3% of points in 0007, 4% of CST points in 0004).
- Leaner Quick start: case folder and registration controls appear only there, Cancel only during preprocessing, shorter status text.
- Single panel: “Quick start” (Plan in one click, Export all) at the top, parameter sections below, research parameters in a collapsed “Advanced (research)” group.
- Default rotation step is now 10°; new angle mode both (grid angles plus tangent and normal directions).
- Leaner panel: automatic controls and duplicate buttons hidden; time, cost, brain shift, atlas and save/load parameters moved into a collapsed “Advanced (research)” group.
- Automatic registration check: passes with ≥ 20 streamlines in both CST and AF; otherwise Quick start shows “Show overlay / ✓ Aligned / ✗ Misaligned”.
- Preoperative nTMS input: motor and language positive points weighted separately (language evidence is weaker, default weight 0.5).
- Redundant-placement pruning: after greedy selection, a placement is dropped if the others cover the same decided segments and gradients; the strip plan is pruned the same way.
- Residual non-enhancing (FLAIR) tumour estimate: FLAIR next to separable or low-risk segments counts as resectable, compared with the 5.4 mL threshold; shown in the value card, the combined data figure and batch summaries.
- Checklist compares the stimulation current with the charge safety line of one contact (k = 1.5, 0.5 ms per phase) and says how many large contacts must share it.
- New exports "Combined: views" and "Combined: data": four 3D views in one image; boundary, placements and sampling, time and cost charts in one image.
- Time model calibrated to the literature: awake phase adds wake-up, baseline test and monitoring per reachable segment; asleep passive recording only on the first N placements, CCEP 2 min per placement; conventional CCEP needs a separate recording strip.
- Boundary uses only the outer rim of the tumour projection; value card adds boundary localisation.

## 0.3.0 (2026-11-07)

- Planning goal changed from target coverage to **segment-by-segment verification of the resection boundary** (enhancing core, optional FLAIR).
- Conventional comparison: 1×N commercial strips planned with the same workflow; usual practice and literature case kept as reference rows.
- Asleep passive mapping option; high-gamma sensitivity / specificity from Swift 2018.
- Contact zoning by MRI (Díaz-Fernández 2025) and peritumoral samples per segment.
- Array vein hinge penalty, conformity strain, fixed-count mode, neighbourhood atlas labels.
- Adaptive one/two-column parameters, dark theme, bilingual tooltips for all parameters.
- Loading a new case clears the previous scene.
- Main script split into `INBRAINPlannerLib/` (i18n, config, logic); English time-model comments translated.
- Input check on Load (BraTS labels incl. BraTS 2023 enhancing = 3, empty masks, grid mismatch, coarse voxels).
- Repository follows the Slicer extension layout: runtime files under `INBRAINPlanner/Resources/` and installed by CMake; Python unit test registered with CTest.
- Stimulation/recording targets no longer drive placement; in 3D they are now translucent orange/blue surface patches for reference. New palette: green/yellow/red reserved for boundary status, dark-red tumour core, cyan CST, magenta AF, dark-blue veins, slate contacts, near-transparent bone flap. The Help & Acknowledgement header is bilingual inside the module.
- Score first, then fit the bone window (on by default): the window size is treated as the largest allowed opening; after placements are chosen the window is re-centred on the arrays and its radius shrunk to 93% per step with a rerun, kept only while no boundary segment is lost and no placement is added. Case 0004 from a 45 mm start: 64 → 34 cm² with the same result.
- Window fitting follows tailored-craniotomy rules: at least `EXPOSE_MIN` 10 mm around the tumour's projection along the view axis (Carrabba 2022), a check when more than `EXPOSE_MAX` 30 mm is exposed (Sanai 2008/2009, Southwell 2016), and the long axis of elliptical/rectangular windows aligned with the tumour projection (Sughrue 2016).
- The 3D view hides the S/I/A/P/R/L letters (which drifted away from the hidden box) and shows the orientation marker instead; View tools can turn letters and box on together.
- Undecided segments: each gets a class (not visible from the window / out of reach / edge only / array cannot fit / no suitable angle / veins / budget) and a next step; a results table (click a row to turn the 3D view there) and a report section.
- 03, User Guide and Run Manual rewritten for v0.3 with 0007 / 0004 rerun.
- Default device follows the reference material: about 40 contacts (3×7 large + 18 in-row micro), 8 mm wide, 3 mm pitch.
- Stimulation reach from current: r = √(I/k) + contact radius; Penfield bipolar (including pair midpoints) for language, Taniguchi monopolar for motor.
- After-discharge monitoring strip added to the conventional workflow (time and device cost).
- Boundary segments exported as navigation bookmarks (replacing paper tags).
- No literature citations in UI text (sources stay in the docs); device preset renamed "Illustrative 3×7 + 18 array (assumed parameters)"; "channels per placement" removed; time and cost tables show only INBRAIN and conventional, sized to their rows; all exports (figure, web 3D, report, navigation, bookmarks) go to a chosen "Export to" folder.
- "Work folder" replaced by "Output location": results go into `<case folder>_Slicer` (default: the `分析` folder next to the case), computed in the hidden cache `~/.inbrain_planner` and synced automatically; separate "Export to" removed; shorter row names in the time and cost tables, no horizontal scrolling.
- Narrower left panel: 440 px on the first entry of each Slicer session; parameters always in two compact columns (labels unwrapped, 72 px spin boxes), narrowest about 440 px in Chinese; elided combo boxes, view tools on two rows; fixed the panel only growing wider.
- UI text matches the current method: ③ renamed "Reference target areas (stimulation / recording)" with a note that they only score the entry and serve as a 3D reference; summary, report and key numbers report decided boundary segments; parameters that no longer act removed (placement score weights, probe grid, strip placements); the after-discharge strip checkbox now reaches the time model; display-style rows use short names and small swatches.
- Optional: require healthy reference contacts (adds a record-only reference array); pre-operative fMRI weighting of segment risk.

## 0.2.0

- Device library, registration check, corridor view, brain-shift analysis, brain atlas, navigation export, scene parameters, view tools, cost model, web 3D export.

## 0.1.0

- First planner: targets, craniotomy, placement scoring, set cover, time model.
