# 在 Slicer 里处理一个病例：（可选）预处理 → 载入 → 按任务参数生成方案 → 把指标写成一行 JSON。
# 由 inbrain_batch.py 调用，不单独使用。环境变量：
#   CASE_DIR   病例文件夹（UCSF-PDGM-XXXX_nifti）
#   JOB_JSON   任务参数：{"tag": "...", "widgets": {参数键: 值}, "extra": {规划脚本变量: 值}, "preprocess": true/false}
#   OUT_JSONL  结果追加写入的文件
import os, sys, json, time, subprocess, traceback
import slicer, qt

CASE_DIR = os.environ["CASE_DIR"]; JOB = json.loads(os.environ.get("JOB_JSON", "{}")); OUT = os.environ["OUT_JSONL"]
row = dict(case_dir=CASE_DIR, tag=JOB.get("tag", "default"), ok=False, error="")
errors = []
slicer.util.errorDisplay = lambda m, *a, **k: errors.append(str(m))      # 批处理时不弹窗，记下错误
t0 = time.time()
try:
    slicer.util.selectModule("INBRAINPlanner"); w = slicer.modules.inbrainplanner.widgetRepresentation().self()
    w._testing = True                       # 不往结果文件夹同步大文件；指标只写 JSON
    w.caseDir.currentPath = CASE_DIR
    case, work, D = w.case_paths(); row["case"] = case
    # ---- 预处理（缓存里已有纤维束就跳过）----
    have_tracts = all(os.path.exists(os.path.join(D, f"{case}_tract_{t}.vtk")) for t in ("CST", "AF"))
    if JOB.get("preprocess", True) and not have_tracts:
        Dp, missing = w.logic.prepare(CASE_DIR, work, case)
        if missing: raise RuntimeError("missing files: " + ", ".join(missing))
        side = w.side_value(D, case)
        if JOB.get("flip"): open(os.path.join(D, "flip.txt"), "w").write(JOB["flip"])
        env = dict(os.environ, CASE=case, SIDE=side, WORK=work, SCRIPTS=w.logic.SCRIPTS if hasattr(w.logic, "SCRIPTS") else "")
        from INBRAINPlannerLib.config import SCRIPTS, P_TRACT
        env["SCRIPTS"] = SCRIPTS
        for k, *_ in P_TRACT: env[k] = str(w.val(k))
        steps = ([] if os.path.exists(os.path.join(D, "flip.txt")) else ["s0_flip.py"]) + ["s1_dti.py", "s2_tract.py"]
        for sc in steps:
            r = subprocess.run([slicer.app.applicationFilePath(), "--no-splash", "--no-main-window", "--python-script", os.path.join(SCRIPTS, sc)],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=3*3600)
            if r.returncode != 0: raise RuntimeError(f"{sc} exit {r.returncode}: " + r.stdout[-400:])
        row["t_pre"] = round(time.time() - t0, 1)
    # ---- 载入 + 参数 + 生成方案 ----
    w.onLoad()
    for k, v in JOB.get("widgets", {}).items():
        if k in w.w: w.w[k].value = v
    extra = JOB.get("extra", {})
    if "STIM_MODEL" in extra: w.stimModel.checked = bool(extra["STIM_MODEL"])
    if "WIN_FIT" in extra: w.winFit.checked = bool(extra["WIN_FIT"])
    if "AD_STRIP" in extra: w.adStrip.checked = bool(extra["AD_STRIP"])
    _orig = w.overrides
    w.overrides = lambda D_, c_: dict(_orig(D_, c_), **{k: v for k, v in extra.items() if k not in ("STIM_MODEL", "WIN_FIT", "AD_STRIP")})
    t1 = time.time(); w.onRun(); row["t_plan"] = round(time.time() - t1, 1)
    G = w.G
    if G is None: raise RuntimeError("plan failed: " + " | ".join(errors[-2:]))
    B = G["BND"]; sc = G["TIME"]["scen"]; cost = {k: tot for k, lab, t, d, tot in w.cost_rows()}
    row.update(ok=True, side=G.get("SIDE", ""), n_seg=B["n_seg"], n_req=B["n_req"], n_arr=B["n_arr"], full=B["full"], edge=B["edge"],
               sep=B.get("sep"), strip_sep=B.get("strip_sep"), margin_cm2=B.get("margin_cm2"), pruned=G.get("PRUNED"), nce_grow=(G.get("NCE_GROW_INFO") or {}).get("params"), ntms_n=G.get("NTMS_N"), nce_total=(B.get("nce") or {}).get("total"), nce_res_inb=(B.get("nce") or {}).get("res_inb"), nce_res_std=(B.get("nce") or {}).get("res_std"), healthy=G.get("HEALTHY_INFO"), placements=len(G["PLAN"]), strip_placements=B.get("strip_placements"), strip_full=B.get("strip_full"),
               why=B.get("why", {}), zones=B.get("zones"), samples_inb=B.get("radial_inb"), samples_strip=B.get("radial_strip"),
               awake_inb=sc["MAIN"]["awake"], asleep_inb=sc["MAIN"]["asleep"], total_inb=sc["MAIN"]["total"],
               awake_std=sc["STD"]["awake"], asleep_std=sc["STD"]["asleep"], total_std=sc["STD"]["total"],
               cost_inb=cost.get("MAIN"), cost_std=cost.get("STD"), stim_inb=sc["MAIN"].get("stim"), stim_std=sc["STD"].get("stim"),
               win_area=G["WIN_CHECK"]["area_cm2"], win_mid=G["WIN_CHECK"]["mid_mm"], proj_in=G["WIN_CHECK"].get("proj_in"),
               expose=G["WIN_CHECK"].get("expose"), r_mono=G.get("R_MONO"), vein_viol=int(G.get("VEIN_VIOL", 0)),
               max_strain=float(G.get("MAX_STRAIN_PLAN", 0)), fit_info=G.get("WIN_FIT_INFO"),
               n_angles=float(sum(len(G["angles_for"](c)) for c in G["centers"]) / max(len(G["centers"]), 1)) if "angles_for" in G else None,
               n_centers=len(G.get("centers", [])))
except Exception as e:
    row["error"] = (str(e) + " | " + " | ".join(errors[-2:]))[:600]; traceback.print_exc()
row["t_total"] = round(time.time() - t0, 1)
with open(OUT, "a", encoding="utf-8") as fh: fh.write(json.dumps(row, ensure_ascii=False, default=float) + "\n")
print("LOG done", row.get("case"), row["ok"], row["error"][:120], flush=True)
slicer.app.quit()
