#!/usr/bin/env python3
"""INBRAIN Planner 批处理：选病例 → 批量预处理和规划 → 参数校准 → 汇总。

用 ~/.venvs/ds/bin/python 运行（不需要 Slicer 的 Python）；每个病例单独启动一个 Slicer 进程调用插件。

  # 1. 从 metadata 选 GBM（WHO 4 级、胶质母细胞瘤），去掉 _FU 随访扫描，随机抽 50 例
  python inbrain_batch.py select --data /path/to/UCSF-PDGM --n 50 --out cases.txt
  # 2. 默认参数跑一遍（含预处理；缓存在 ~/.inbrain_planner/w<病例>，已有纤维束的跳过预处理）
  python inbrain_batch.py run --cases cases.txt --out runs.jsonl --jobs 2
  #    改参数：--set PITCH=3 --extra ANGLE_MODE=tangent  （--set 是界面参数，--extra 是规划脚本变量）
  # 3. 参数校准：网格里每组参数在所有病例上跑一遍（只规划，不重复预处理）
  python inbrain_batch.py calibrate --cases cases.txt --grid grid.json --out calib.jsonl --jobs 2
  # 4. 汇总：每组参数一行，中位数 / 四分位 / 失败率，并和目标区间比较
  python inbrain_batch.py summarize calib.jsonl --out calib_summary.csv
  # 5. 切除程度验证：按 GTR / STR 分层选病例，跑完后比较插件指标能否区分医生实际全切和次全切
  python inbrain_batch.py select --data /path/to/UCSF-PDGM --eor GTR:25,STR:25 --out cases_eor.txt
  python inbrain_batch.py eor runs_eor.jsonl --data /path/to/UCSF-PDGM --out eor_summary.csv
"""
import argparse, csv, itertools, json, os, random, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SLICER = os.environ.get("SLICER", "/Applications/Slicer.app/Contents/MacOS/Slicer")
CASE_SCRIPT = os.path.join(HERE, "slicer_batch_case.py")

# 校准目标：指标名 → (下限, 上限, 说明)。中位数落在区间内为达标
TARGETS = {
    "awake_inb": (40, 110, "清醒期 min（文献：测试 73 ± 26，平均约 98）"),
    "win_area": (25, 80, "骨窗面积 cm²（常见骨瓣 25–80）"),
    "r_mono": (2, 5, "单极激活半径 mm（宏电极经验范围）"),
    "decided_frac": (0.6, 1.0, "完整判定 / 阵列可达段"),
    "placements": (3, 15, "放置次数"),
    "asleep_inb": (20, 45, "麻醉期额外 min（麻醉下 ECoG/CCEP 常见 20–40）"),
    "total_inb": (80, 150, "定位相关全部 min（不含开关颅）"),
}


def parse_kv(items):
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        try: v = json.loads(v)
        except Exception: pass
        out[k] = v
    return out


def cmd_select(a):
    meta = os.path.join(a.data, "UCSF-PDGM-metadata_v5.csv")
    gbm = set()
    with open(meta, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("WHO CNS Grade", "")).strip() == "4" and "glioblastoma" in r.get("Final pathologic diagnosis (WHO 2021)", "").lower():
                gbm.add(int(re.findall(r"\d+", r["ID"])[-1]))
    dirs = []
    for d in sorted(os.listdir(a.data)):
        m = re.fullmatch(r"UCSF-PDGM-(\d+)_nifti", d)          # 不含 _FUxxxd 随访
        if m and int(m.group(1)) in gbm: dirs.append(os.path.join(a.data, d))
    random.Random(a.seed).shuffle(dirs)
    pick = dirs[:a.n] if a.n else dirs
    if a.eor:   # 按切除程度分层，例如 GTR:25,STR:25；已预处理过的病例优先（省时间）
        eor = read_eor(a.data); cache = os.path.expanduser("~/.inbrain_planner")
        cached = lambda d: os.path.exists(os.path.join(cache, "w" + case_id(d), case_id(d) + "_tract_AF.vtk"))
        pick = []
        for part in a.eor.split(","):
            g, n = part.split(":"); grp = [d for d in dirs if eor.get(case_id(d)) == g]
            grp.sort(key=lambda d: not cached(d)); pick += grp[:int(n)]
            print(f"{g}: 选 {min(int(n), len(grp))} 例，其中已预处理 {sum(cached(d) for d in grp[:int(n)])} 例")
    open(a.out, "w").write("\n".join(pick) + "\n")
    print(f"GBM 非随访 {len(dirs)} 例，选 {len(pick)} 例 → {a.out}")


def case_id(d): return re.findall(r"(\d+)_nifti", os.path.basename(d.rstrip("/")))[0].zfill(4)


def read_eor(data):
    out = {}
    with open(os.path.join(data, "UCSF-PDGM-metadata_v5.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh): out[re.findall(r"\d+", r["ID"])[-1].zfill(4)] = dict(eor=r.get("EOR", ""), os=r.get("OS", ""), dead=r.get("1-dead 0-alive", ""), age=r.get("Age at MRI", ""))
    return {k: v["eor"] for k, v in out.items()} if True else out


def auc_mw(x, y):
    """AUC = P(STR 组的值 > GTR 组的值)，并给 Mann-Whitney U 的正态近似双侧 p"""
    import math
    x, y = [v for v in x if v is not None], [v for v in y if v is not None]
    if not x or not y: return None, None
    r = sorted([(v, 0) for v in x] + [(v, 1) for v in y]); ranks = [0.0]*len(r); i = 0
    while i < len(r):
        j = i
        while j + 1 < len(r) and r[j + 1][0] == r[i][0]: j += 1
        for k in range(i, j + 1): ranks[k] = (i + j)/2 + 1
        i = j + 1
    R1 = sum(rk for rk, (v, g) in zip(ranks, r) if g == 0); n1, n2 = len(x), len(y)
    U1 = R1 - n1*(n1 + 1)/2; auc = U1/(n1*n2)
    z = (U1 - n1*n2/2)/math.sqrt(n1*n2*(n1 + n2 + 1)/12); p = math.erfc(abs(z)/math.sqrt(2))
    return auc, p


def cmd_eor(a):
    """按 PDGM 的切除程度（GTR / STR）比较插件指标：中位数、AUC（STR 更高的概率）、p 值"""
    eor = read_eor(a.data); rows = []
    for fn in a.files:
        for l in open(fn, encoding="utf-8"):
            r = json.loads(l)
            if r.get("ok") and (not a.tag or r["tag"] == a.tag): rows.append(r)
    best = {}
    for r in rows: best[r["case"]] = r            # 同一病例取最后一次
    M = {"n_req": ("靠功能区的段数", lambda r: r["n_req"]),
         "frac_req": ("靠功能区段比例", lambda r: r["n_req"]/max(r["n_seg"], 1)),
         "unsep_std": ("传统流程未分离段数", lambda r: r["n_req"] - (r.get("strip_sep") or 0)),
         "unsep_std_frac": ("传统流程未分离比例", lambda r: (r["n_req"] - (r.get("strip_sep") or 0))/max(r["n_req"], 1)),
         "unsep_inb": ("INBRAIN 未分离段数", lambda r: r["n_req"] - (r.get("sep") or 0)),
         "unreach_frac": ("骨窗外需定位段比例", lambda r: (r["n_req"] - r["n_arr"])/max(r["n_req"], 1)),
         "nce_total": ("FLAIR 总量 mL", lambda r: r.get("nce_total")),
         "nce_res_std": ("FLAIR 残留·传统 mL", lambda r: r.get("nce_res_std")),
         "nce_res_inb": ("FLAIR 残留·INBRAIN mL", lambda r: r.get("nce_res_inb"))}
    G = {g: [r for c, r in best.items() if eor.get(c) == g] for g in ("GTR", "STR")}
    out = []
    for k, (nm, fn_) in M.items():
        v = {g: [fn_(r) for r in rs] for g, rs in G.items()}
        auc, p = auc_mw(v["GTR"], v["STR"])
        out.append(dict(metric=k, name=nm, n_gtr=len(v["GTR"]), n_str=len(v["STR"]), med_gtr=q(v["GTR"], .5), med_str=q(v["STR"], .5),
                        auc_str_higher=None if auc is None else round(1 - auc, 3), p=None if p is None else round(p, 4)))
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print(f"GTR {len(G['GTR'])} 例，STR {len(G['STR'])} 例（AUC = STR 组更高的概率；0.5 = 区分不了）")
    for o in out:
        f = lambda x: "—" if x is None else f"{x:.2f}"
        print(f"  {o['name']:<18} GTR {f(o['med_gtr']):>7}  STR {f(o['med_str']):>7}  AUC {f(o['auc_str_higher'])}  p {f(o['p'])}")
    print(f"→ {a.out}")


def run_one(case_dir, job, out):
    env = dict(os.environ, CASE_DIR=case_dir, JOB_JSON=json.dumps(job), OUT_JSONL=out)
    t = time.time()
    r = subprocess.run([SLICER, "--no-splash", "--python-script", CASE_SCRIPT], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = [l for l in r.stdout.splitlines() if l.startswith("LOG done")]
    print(f"[{time.strftime('%H:%M:%S')}] {os.path.basename(case_dir)} {job.get('tag')} {time.time() - t:.0f}s {tail[-1] if tail else 'no result (exit %d)' % r.returncode}", flush=True)


def done_set(out):
    s = set()
    if os.path.exists(out):
        for l in open(out, encoding="utf-8"):
            try: r = json.loads(l); s.add((r["case_dir"], r["tag"]))
            except Exception: pass
    return s


def run_jobs(cases, jobs, out, n_par):
    done = done_set(out)
    todo = [(c, j) for j in jobs for c in cases if (c, j["tag"]) not in done]
    print(f"{len(todo)} 个任务（跳过已完成 {len(cases)*len(jobs) - len(todo)}），并行 {n_par}")
    # 同一病例的第一个任务先跑（含预处理），避免两个进程同时预处理同一病例
    first = {}
    for c, j in todo: first.setdefault(c, (c, j))
    rest = [t for t in todo if t not in first.values()]
    with ThreadPoolExecutor(n_par) as ex:
        list(ex.map(lambda t: run_one(t[0], t[1], out), first.values()))
    with ThreadPoolExecutor(n_par) as ex:
        list(ex.map(lambda t: run_one(t[0], t[1], out), rest))


def read_cases(p): return [l.strip() for l in open(p) if l.strip()]


def cmd_run(a):
    job = dict(tag=a.tag, widgets=parse_kv(a.set), extra=parse_kv(a.extra), preprocess=not a.no_pre)
    if a.flip: job["flip"] = a.flip
    run_jobs(read_cases(a.cases), [job], a.out, a.jobs)


def cmd_calibrate(a):
    g = json.load(open(a.grid))
    keys = list(g.get("widgets", {})) + list(g.get("extra", {}))
    vals = list(g.get("widgets", {}).values()) + list(g.get("extra", {}).values())
    jobs = []
    for combo in itertools.product(*vals):
        d = dict(zip(keys, combo))
        jobs.append(dict(tag=" ".join(f"{k}={v}" for k, v in d.items()),
                         widgets={k: d[k] for k in g.get("widgets", {})}, extra={k: d[k] for k in g.get("extra", {})}, preprocess=True))
    print(f"{len(jobs)} 组参数 × {len(read_cases(a.cases))} 例")
    run_jobs(read_cases(a.cases), jobs, a.out, a.jobs)


def q(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs: return None
    k = (len(xs) - 1)*p; f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f])*(k - f)


def cmd_summarize(a):
    rows = [json.loads(l) for l in open(a.file, encoding="utf-8") if l.strip()]
    by = {}
    for r in rows: by.setdefault(r["tag"], []).append(r)
    metrics = ["sep", "strip_sep", "margin_cm2", "nce_total", "nce_res_inb", "nce_res_std", "t_pre", "t_total", "full", "n_req", "n_arr", "strip_full", "placements", "strip_placements", "awake_inb", "awake_std", "asleep_inb", "asleep_std", "total_inb", "total_std",
               "cost_inb", "cost_std", "win_area", "r_mono", "samples_inb", "t_plan"]
    out = []
    for tag, rs in by.items():
        ok = [r for r in rs if r.get("ok")]
        for r in ok:
            r["decided_frac"] = r["full"]/r["n_arr"] if r.get("n_arr") else None
            r["gain_full"] = r["full"] - (r.get("strip_full") or 0)
            r["gain_awake"] = (r.get("awake_std") or 0) - r["awake_inb"]
        line = dict(tag=tag, n=len(rs), ok=len(ok), fail_rate=round(1 - len(ok)/max(len(rs), 1), 3))
        for m in metrics + ["decided_frac", "gain_full", "gain_awake"]:
            v = [r.get(m) for r in ok]
            line[m + "_med"] = None if q(v, .5) is None else round(q(v, .5), 2)
            line[m + "_iqr"] = None if q(v, .25) is None else f"{q(v, .25):.1f}–{q(v, .75):.1f}"
        hits = 0
        for m, (lo, hi, _) in TARGETS.items():
            med = line.get(m + "_med")
            ok_ = med is not None and lo <= med <= hi; hits += ok_
            line["target_" + m] = "ok" if ok_ else "out"
        line["targets_met"] = f"{hits}/{len(TARGETS)}"
        out.append(line)
    out.sort(key=lambda l: (-int(l["targets_met"].split("/")[0]), -(l.get("gain_full_med") or 0), l.get("placements_med") or 99))
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    for l in out[:10]:
        print(f"{l['targets_met']}  ok {l['ok']}/{l['n']}  判定 {l['full_med']}/{l['n_arr_med']}  条带 {l['strip_full_med']}  放置 {l['placements_med']}  清醒 {l['awake_inb_med']}  {l['tag']}")
    fails = [r for r in rows if not r.get("ok")]
    if fails:
        print(f"\n失败 {len(fails)} 例（前 10）："); [print(" ", os.path.basename(r['case_dir']), r['error'][:120]) for r in fails[:10]]
    print(f"→ {a.out}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("select"); x.add_argument("--data", required=True); x.add_argument("--n", type=int, default=50); x.add_argument("--seed", type=int, default=0); x.add_argument("--out", default="cases.txt"); x.add_argument("--eor", help="按切除程度分层，例如 GTR:25,STR:25"); x.set_defaults(f=cmd_select)
    x = s.add_parser("run"); x.add_argument("--cases", required=True); x.add_argument("--out", default="runs.jsonl"); x.add_argument("--jobs", type=int, default=2)
    x.add_argument("--tag", default="default"); x.add_argument("--set", nargs="*"); x.add_argument("--extra", nargs="*"); x.add_argument("--no-pre", action="store_true"); x.add_argument("--flip"); x.set_defaults(f=cmd_run)
    x = s.add_parser("calibrate"); x.add_argument("--cases", required=True); x.add_argument("--grid", required=True); x.add_argument("--out", default="calib.jsonl"); x.add_argument("--jobs", type=int, default=2); x.set_defaults(f=cmd_calibrate)
    x = s.add_parser("summarize"); x.add_argument("file"); x.add_argument("--out", default="summary.csv"); x.set_defaults(f=cmd_summarize)
    x = s.add_parser("eor"); x.add_argument("files", nargs="+"); x.add_argument("--data", required=True); x.add_argument("--tag"); x.add_argument("--out", default="eor_summary.csv"); x.set_defaults(f=cmd_eor)
    a = p.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
