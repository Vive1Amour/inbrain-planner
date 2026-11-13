# Time model: depends only on "counts" (language/motor sites per placement, probe grid sites) and time parameters
# Shared by slicer_placement_score.py and s5_sensitivity.py; change formulas only here
import numpy as np

def _flow(lk, mk, nP, P, ov, st_m, motor_aw):
    """Workflow shared by arrays and strips: asleep CCEP (+ optional passive recording) screen; awake, revisit only placements with suspicious contacts and stimulate to confirm; ov = extra time per stimulated site"""
    st_l = P["T_LANG"] + ov; Fc = P["F_CCEP"]
    if P.get("PASSIVE_ASLEEP"):
        # passive mapping moved to the asleep phase (auditory-task high gamma under general anaesthesia, 2021 Front Neurol case; Swift 2018 sensitivity 95% / specificity 59%):
        # each placement gets CCEP + passive task recording asleep; a contact is suspicious only if both are positive; awake, revisit only placements with suspicious contacts and stimulate to confirm (incl. expressive language)
        pf = max((Fc - P["P_TRUE"]*P["CCEP_SENS"])/max(1 - P["P_TRUE"], 1e-9), 0.0)          # CCEP false-positive rate at non-language sites
        f = P["P_TRUE"]*P["CCEP_SENS"]*P["SENS"] + (1 - P["P_TRUE"])*pf*(1 - P["SPEC"])
        E2 = float(np.sum(1 - (1 - f)**lk[lk > 0]))
        stim_m = lk.sum()*f
        _n = int((lk > 0).sum()); asl2 = _n*(P["T_PLACE"] + P["T_CCEP"]) + min(_n, P.get("PASSIVE_N", 1))*P["T_PASSIVE"]   # passive recording: only the first PASSIVE_N placements
        aw_m = E2*P["T_PLACE"] - (P["T_PLACE"] if (P["ASLEEP_FIRST"] and E2 >= 1) else 0) + stim_m*st_l + motor_aw
        return dict(awake=max(aw_m, 0.0), asleep=asl2, total=asl2 + max(aw_m, 0.0) + (nP - int((lk > 0).sum()))*P["T_PLACE"] + (0 if P["MOTOR_AWAKE"] else mk.sum()*st_m),
                           missed=lk.sum()*P["P_TRUE"]*(1 - P["CCEP_SENS"]*P["SENS"]), stim=stim_m, regions=float(E2))
    else:
        E_aw = float(np.sum(1 - (1 - Fc)**lk[lk > 0])); asl = int((lk > 0).sum())*(P["T_PLACE"] + P["T_CCEP"])
        p2 = min(P["P_TRUE"]*P["CCEP_SENS"]/Fc, 1.0); flag2 = p2*P["SENS"] + (1 - p2)*(1 - P["SPEC"])
        stim_m = lk.sum()*Fc*flag2
        aw_m = E_aw*(P["T_PLACE"] + P["T_PASSIVE"]) - (P["T_PLACE"] if (P["ASLEEP_FIRST"] and E_aw >= 1) else 0) + stim_m*st_l + motor_aw
        return dict(awake=aw_m, asleep=asl, total=asl + aw_m + (nP - int((lk > 0).sum()))*P["T_PLACE"] + (0 if P["MOTOR_AWAKE"] else mk.sum()*st_m),
                           missed=lk.sum()*P["P_TRUE"]*(1 - P["CCEP_SENS"]*P["SENS"]), stim=stim_m, regions=float(E_aw))

def scenario_times(c, P):
    """c = COUNTS, P = parameter dict; returns awake / extra asleep / total time (min) for each scenario"""
    lk, mk = np.array(c["lang_k"]), np.array(c["motor_k"]); nP = c["placements"]
    st_l, st_m = P["T_LANG"] + P["OV_ARRAY"], P["T_MOTOR"] + P["OV_ARRAY"]
    motor_aw = mk.sum()*st_m if P["MOTOR_AWAKE"] else 0.0
    aw_pl = int((lk > 0).sum() if not P["MOTOR_AWAKE"] else ((lk + mk) > 0).sum())
    free = P["T_PLACE"] if (P["ASLEEP_FIRST"] and aw_pl > 0) else 0.0   # first placement done asleep, not repeated after waking
    out = {}
    # A point-by-point stimulation
    out["A"] = dict(awake=aw_pl*P["T_PLACE"] - free + lk.sum()*st_l + motor_aw,
                    total=nP*P["T_PLACE"] + lk.sum()*st_l + mk.sum()*st_m, asleep=0.0, missed=0.0)
    # B awake: record first, then stimulate
    flag = P["P_TRUE"]*P["SENS"] + (1 - P["P_TRUE"])*(1 - P["SPEC"])
    out["B"] = dict(awake=aw_pl*(P["T_PLACE"] + P["T_PASSIVE"]) - free + flag*lk.sum()*st_l + motor_aw,
                    total=nP*P["T_PLACE"] + aw_pl*P["T_PASSIVE"] + flag*lk.sum()*st_l + mk.sum()*st_m,
                    asleep=0.0, missed=lk.sum()*P["P_TRUE"]*(1 - P["SENS"]))
    # C asleep CCEP screen (stimulate anterior contacts, record posterior ones to test arcuate connectivity); awake, stimulate CCEP-positive contacts only
    Fc = P["F_CCEP"]
    E_aw = float(np.sum(1 - (1 - Fc)**lk[lk > 0]))                     # expected placements to revisit awake
    asl = int((lk > 0).sum())*(P["T_PLACE"] + P["T_CCEP"])
    out["C"] = dict(awake=E_aw*P["T_PLACE"] - (P["T_PLACE"] if (P["ASLEEP_FIRST"] and E_aw >= 1) else 0) + Fc*lk.sum()*st_l + motor_aw,
                    asleep=asl, total=asl + E_aw*P["T_PLACE"] + Fc*lk.sum()*st_l + (nP - int((lk > 0).sum()))*P["T_PLACE"] + mk.sum()*st_m,
                    missed=lk.sum()*P["P_TRUE"]*(1 - P["CCEP_SENS"]))
    # MAIN INBRAIN workflow: electronic switching between array contacts (OV_ARRAY)
    out["MAIN"] = _flow(lk, mk, nP, P, P["OV_ARRAY"], st_m, motor_aw)
    # STD conventional workflow (same logic): 1×N commercial strips on the same boundary, same asleep CCEP / passive recording; fewer contacts, so more moves;
    # awake, the surgeon stimulates each suspicious site with a hand-held probe (OV_PROBE per site to move the probe and tag), the strip moved nearby to monitor after-discharges
    if "strip_lang_k" in c:
        slk, smk = np.array(c["strip_lang_k"]), np.array(c["strip_motor_k"])
        s_st_m = P["T_MOTOR"] + P["OV_PROBE"]
        s_motor_aw = smk.sum()*s_st_m if P["MOTOR_AWAKE"] else 0.0
        out["STD"] = _flow(slk, smk, c["strip_placements"], P, P["OV_PROBE"], s_st_m, s_motor_aw)
        # CCEP: the array stimulates and records in one placement; a 1×N strip needs a second strip (or a second position) to record
        _x = int((slk > 0).sum())*P.get("STRIP_CCEP_EXTRA", 1)*(P["T_PLACE"] + P["T_CCEP"])
        out["STD"] = dict(out["STD"], asleep=out["STD"]["asleep"] + _x, total=out["STD"]["total"] + _x)
        if P.get("AD_STRIP", True):
            # After-discharge monitoring: probe stimulation needs a separate ECoG strip next to it (reference material);
            # placed once asleep and moved with every new awake region. INBRAIN records around its own stimulating contacts, so no extra strip
            ad_aw = out["STD"]["regions"]*P["T_PLACE"]
            out["STD"] = dict(out["STD"], awake=out["STD"]["awake"] + ad_aw, asleep=out["STD"]["asleep"] + P["T_PLACE"],
                              total=out["STD"]["total"] + ad_aw + P["T_PLACE"], ad_strip=1)
    # usual practice: probe point by point; strips only record and are placed asleep
    pl, pm = c["probe_grid_lang"], c["probe_grid_motor"]; sp_l, sp_m = P["T_LANG"] + P["OV_PROBE"], P["T_MOTOR"] + P["OV_PROBE"]
    out["STD_probe"] = dict(awake=pl*sp_l + (pm*sp_m if P["MOTOR_AWAKE"] else 0), asleep=0.0,
                      total=pl*sp_l + pm*sp_m + P["STRIP_PLACE_STD"]*P["T_PLACE"], missed=0.0)
    ol, om = c["probe_opt_lang"], c["probe_opt_motor"]
    out["STD_opt"] = dict(awake=ol*sp_l + (om*sp_m if P["MOTOR_AWAKE"] else 0), asleep=0.0,
                          total=ol*sp_l + om*sp_m + P["STRIP_PLACE_STD"]*P["T_PLACE"], missed=0.0)
    # literature case: Sanai 2008 (NEJM, 250 patients) 3281 cortical sites / 250 ≈ 13.1 per patient, 94% negative;
    # each site costs language-site time + probe overhead; strips only record and are placed asleep
    ls = P.get("LIT_SITES", 13.1)
    out["STD_lit"] = dict(awake=ls*sp_l, asleep=0.0, total=ls*sp_l + P["STRIP_PLACE_STD"]*P["T_PLACE"], missed=0.0)
    # Fixed parts of the awake phase (same for both workflows, calibrated to the literature: awake phase ~98 min, testing 73±26 min):
    # wake-up until cooperative + baseline language test + monitoring while resecting near each eloquent boundary segment
    fix = P.get("T_WAKE", 0) + P.get("T_BASE", 0) + P.get("T_MON", 0)*c.get("n_mon", 0)
    for k, v in out.items():
        if v["awake"] > 0: out[k] = dict(v, awake=v["awake"] + fix, total=v["total"] + fix, awake_fixed=fix)
    return out

