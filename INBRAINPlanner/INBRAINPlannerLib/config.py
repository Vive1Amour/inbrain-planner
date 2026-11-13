# 参数定义、器件预设、显示样式、主题和悬停说明 / parameters, device presets, display styles, theme and tooltips
import os, json, re
import qt, slicer
from INBRAINPlannerLib.i18n import *

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))     # module folder (INBRAINPlanner/)
SCRIPTS = os.path.join(HERE, "Resources", "Pipeline")                   # Slicer extension layout: runtime files live under the module Resources

# ---------------- 参数定义：(键, 标签, 默认, 最小, 最大, 步长, 小数, 说明) ----------------
P_DEVICE = [
    ("NX", "大触点列数", 3, 1, 20, 1, 0, "阵列横向大触点个数"),
    ("NY", "大触点行数", 7, 1, 30, 1, 0, "阵列纵向大触点个数"),
    ("PITCH", "触点间距 mm", 4.0, 0.5, 30, 0.5, 1, "相邻大触点中心距离"),
    ("STIM_REACH", "刺激半径 mm", 5.0, 0.5, 20, 0.5, 1, "一个大触点刺激能查到的范围（勾“刺激范围按电流算”时不用）"),
    ("STIM_I", "刺激电流 mA", 8.0, 1, 20, 0.5, 1, "Penfield 法 1 mA 起、最高 20 mA"),
    ("K_RANCK", "兴奋常数 k µA/mm²", 1292, 100, 5000, 50, 0, "激活半径 r = √(I/k)；1292 = 皮层锥体细胞"),
    ("CONTACT_D", "大触点直径 mm", 1.0, 0.025, 6, 0.1, 2, "参考资料：INBRAIN 约 1 mm"),
    ("BIPOLAR_SPREAD", "双极半径系数", 0.5, 0.1, 1, 0.05, 2, "双极刺激电流集中在两触点之间，半径按单极的这个比例"),
    ("REC_REACH_L", "大触点记录 mm", 5.0, 0.5, 20, 0.5, 1, ""),
    ("REC_REACH_S", "小触点记录 mm", 3.0, 0.5, 20, 0.5, 1, ""),
    ("MAX_FIT", "贴合误差 mm", 3.0, 0.5, 20, 0.5, 1, "触点投影到皮层前后的最大位移；超过该值视为贴合不良"),
    ("ANGLE_STEP", "旋转步长 °", 10, 5, 90, 5, 0, "每个候选位置试几个方向（0–180°）"),
]
P_TARGET = [
    ("TRACT_NEAR", "纤维束入口 mm", 10.0, 1, 30, 1, 1, "刺激区：离纤维束这么近算入口"),
    ("STIM_EDGE", "刺激距病灶 mm", 15.0, 1, 50, 1, 1, "刺激区：只看切除边缘附近"),
    ("W_CST", "CST 权重", 1.0, 0, 1, 0.1, 1, "0 = CST 附近的边界段不需要定位"),
    ("W_AF", "AF 权重", 0.5, 0, 1, 0.1, 1, "右侧病例 AF 不一定是语言优势侧；左侧建议 1"),
    ("REC_FLAIR", "离 FLAIR mm", 5.0, 0, 30, 1, 1, "记录区：FLAIR 带上方这么近"),
    ("RING", "记录圈宽 mm", 8.0, 0, 30, 1, 1, "记录区：刺激区外的环形带（用于监测后放电）"),
    ("REC_LESION", "记录距病灶 mm", 30.0, 5, 80, 1, 1, ""),
    ("CORE_MARGIN", "核心表面排除 mm", 3.0, 0, 20, 0.5, 1, "距肿瘤核心小于该距离的皮层属于计划切除范围，不作为阵列放置位置"),
]
P_CRANIO = [
    ("WINDOW_R", "骨窗半径 mm", 35.0, 10, 80, 1, 1, "约 7 cm 骨瓣"),
    ("WIN_LEN", "骨窗长 mm", 80.0, 20, 160, 1, 0, "椭圆、圆角矩形：沿长轴的全长"),
    ("WIN_WID", "骨窗宽 mm", 60.0, 20, 160, 1, 0, "椭圆、圆角矩形：垂直长轴的全宽"),
    ("WIN_ANGLE", "长轴方向 °", 0.0, -90, 90, 5, 0, "0 = 前后向，90 = 上下向，45 = 前上到后下"),
    ("WIN_CORNER", "圆角半径 mm", 10.0, 0, 40, 1, 0, "圆角矩形的四个角"),
    ("SLIDE", "骨窗下伸入 mm", 15.0, 0, 40, 1, 1, "电极片能滑到骨窗边缘下面多远"),
    ("EXPOSE_MIN", "肿瘤投影外至少 mm", 10.0, 0, 40, 1, 1, "收紧骨窗时，肿瘤皮层投影外至少留这么宽（小骨窗定义 ≤ 1 cm）"),
    ("EXPOSE_MAX", "肿瘤投影外最多 mm", 30.0, 10, 60, 1, 1, "定制骨窗一般只露出肿瘤外 2–3 cm，超过时提示"),
    ("WIN_R_LIMIT", "扩窗上限半径 mm", 50.0, 25, 80, 1, 0, "残留未达标时骨窗最多扩到这么大"),
    ("NCE_STEP_MIN", "扩窗最小收益 mL", 2.0, 0, 20, 0.5, 1, "再扩一步残留至少减少这么多才扩"),
    ("MIDLINE_EX", "中线禁区 mm", 12.0, 0, 40, 1, 1, "上矢状窦、大脑镰"),
    ("MIDLINE_CAUTION", "中线扣分 mm", 20.0, 0, 50, 1, 1, ""),
    ("BASE_NZ", "颅底阈值", -0.35, -1, 0, 0.05, 2, "皮层法向 z 低于它 = 颅底面，不开"),
    ("VEIN_SAFE", "静脉安全距离 mm", 3.0, 0, 20, 0.5, 1, "SWI 上的表面大静脉：手术通道离它小于这个距离要扣分"),
    ("W_VEIN", "近大静脉扣分权重", 0.4, 0, 5, 0.1, 1, "入口 10 mm 内有大静脉或通道经过大静脉时扣的分；0 = 不用 SWI"),
    ("W_VEIN_ARR", "阵列避静脉权重", 0.2, 0, 5, 0.1, 1, "阵列触点与 SWI 大静脉的距离小于安全距离时，按差值线性扣分（铰链惩罚）；0 = 不考虑静脉"),
    ("LOW_Z", "低位扣分", 0.35, 0, 1, 0.05, 2, "全脑高度最低这一比例的外侧皮层扣分"),
]
P_SKULL = [
    ("SKULL_IN", "颅骨距脑 mm", 4.0, 0, 20, 0.5, 1, "脑表面到颅骨内板：脑脊液 + 硬膜"),
    ("SKULL_THICK", "颅骨厚度 mm", 7.0, 2, 20, 0.5, 1, "成人颅骨约 5–10 mm"),
    ("CT_HU", "CT 骨阈值 HU", 300, 100, 1500, 50, 0, "用 CT 文件时，高于它算骨"),
]
P_OPT = [
    ("SEG_LEN", "边界分段 mm", 10, 5, 30, 1, 0, "切除边界按这个长度分段，每段需给出是否可扩大切除的结论（1 cm = 临床阴性定位间距）"),
    ("SUPRA", "扩大切除 mm", 8, 0, 20, 1, 0, "每段除边界上的测试点外，在边界外该距离处再设一个测试点；两处均为阴性时，可将该段切除范围扩大此距离"),
    ("CAND_GRID", "候选间隔 mm", 6.0, 2, 20, 1, 1, "越小越精细、越慢"),
    ("MAX_ARRAYS", "固定片数", 0, 0, 30, 1, 0, "0 = 放到没有新的边界段可判定为止；N = 只放 N 次，判定尽量多的段"),
    ("MAX_STRAIN", "最大形变 %", 20, 5, 100, 5, 0, "阵列贴到皮层后跨阵列的触点间距最多被拉伸或压缩多少"),
    ("FMRI_Z", "fMRI z 阈值", 3.1, 0, 20, 0.1, 1, "术前 fMRI（可选）"),
    ("FMRI_W", "fMRI 权重", 1.0, 0, 5, 0.1, 1, "段风险 × (1 + 权重 × 激活)"),
    ("NTMS_R", "nTMS 影响半径 mm", 10.0, 1, 30, 1, 0, "段中心离阳性点的距离"),
    ("NTMS_W_MOTOR", "nTMS 运动权重", 1.0, 0, 5, 0.1, 1, "运动点：段风险 × (1 + 权重)"),
    ("NTMS_W_LANG", "nTMS 语言权重", 0.5, 0, 5, 0.1, 1, "语言点证据较弱"),
]
P_TIME = [
    ("T_PLACE", "放置一次 min", 2.0, 0, 20, 0.1, 1, ""),
    ("T_LANG", "语言位点 min", 1.0, 0, 10, 0.1, 1, ""),
    ("T_MOTOR", "运动位点 min", 0.5, 0, 10, 0.1, 1, ""),
    ("OV_PROBE", "探针额外 min", 0.3, 0, 5, 0.05, 2, "移动探针、放置编号标签"),
    ("OV_ARRAY", "阵列切换 min", 0.05, 0, 5, 0.05, 2, ""),
    ("T_WAKE", "唤醒 min", 15.0, 0, 60, 1, 0, "停药到病人能配合测试"),
    ("T_BASE", "基线测试 min", 5.0, 0, 30, 1, 0, "刺激前的基线命名"),
    ("T_MON", "每段切除监测 min", 2.5, 0, 15, 0.5, 1, "切到骨窗内每个功能区边界段时的清醒监测"),
    ("STRIP_CCEP_EXTRA", "条带 CCEP 额外放置", 1, 0, 5, 1, 0, "刺激和记录要两条条带"),
    ("PASSIVE_N", "麻醉期被动记录片数", 1, 0, 30, 1, 0, "只在前 N 片做被动记录"),
    ("T_PASSIVE", "任务记录 min", 3.0, 0, 20, 0.5, 1, ""),
    ("P_TRUE", "真语言比例", 0.3, 0, 1, 0.05, 2, ""),
    ("SENS", "高 gamma 敏感度", 0.95, 0, 1, 0.05, 2, "被动高 γ 定位对比电刺激"),
    ("SPEC", "高 gamma 特异度", 0.59, 0, 1, 0.05, 2, "被动高 γ 定位对比电刺激"),
    ("F_CCEP", "CCEP 阳性比例", 0.4, 0, 1, 0.05, 2, ""),
    ("T_CCEP", "每片 CCEP min", 2.0, 0, 30, 0.5, 1, ""),
    ("CCEP_SENS", "CCEP 敏感度", 0.85, 0, 1, 0.05, 2, ""),
    ("AWAKE_WINDOW", "清醒窗口 min", 120.0, 10, 300, 5, 0, ""),
    ("STRIP_N", "条带触点数", 4, 2, 16, 1, 0, "传统流程用的 1×N 商用条带"),
    ("STRIP_PITCH", "条带间距 mm", 10, 2, 20, 1, 0, ""),
    ("STRIP_CD", "条带触点暴露直径 mm", 2.3, 0.5, 6, 0.1, 1, "Ad-Tech 4 mm 触点暴露 2.3 mm"),
]
P_TRACT = [
    ("CST_SEED_FA", "CST 种子 FA", 0.35, 0.05, 0.9, 0.05, 2, ""),
    ("CST_STOP_FA", "CST 停止 FA", 0.15, 0.02, 0.5, 0.01, 2, ""),
    ("AF_SEED_FA", "AF 种子 FA", 0.25, 0.05, 0.9, 0.05, 2, ""),
    ("AF_STOP_FA", "AF 停止 FA", 0.08, 0.02, 0.5, 0.01, 2, "穿过水肿带时需降低"),
]
P_COST = [
    ("OR_COST", "手术室 €/min", 12.2, 0, 500, 0.1, 1, "默认值：西班牙公立医疗价目表（阿斯图里亚斯 2023），183.51 €/15 min"),
    ("AWAKE_EXTRA", "清醒加价 €/min", 15.0, 0, 500, 1, 0, "默认值：清醒手术每例增加约 2,175 美元人员成本（时间驱动成本研究，2025），按清醒期约 130 min 折算"),
    ("PRICE_INBRAIN", "阵列单价 €", 3000, 0, 100000, 100, 0, "按实际采购价填写"),
    ("N_ARRAY", "每例片数", 1, 1, 10, 1, 0, "同一片阵列可多次重新放置"),
    ("PRICE_STRIP", "条带单价 €", 400, 0, 20000, 50, 0, "按实际采购价填写"),
    ("N_STRIP", "每例条数", 2, 0, 10, 1, 0, ""),
]
P_SHIFT = [
    ("SHIFT_SINK", "下沉 mm", 8.0, 0, 30, 0.5, 1, "开颅后皮层向内塌陷：骨窗中心最大，到可伸出范围边缘减到 0"),
    ("SHIFT_TAN", "侧向 mm", 3.0, 0, 20, 0.5, 1, "沿皮层切向偏移，试 8 个方向"),
]
# 脑移位：按切除核心体积分组（的 <20 / 20–40 / >40 ml 分组，皮层下沉文献平均约 1 cm，最大约 2.4 cm）
SHIFT_BY_VOL = [(20, 5.0), (40, 8.0), (1e9, 12.0)]   # (体积上限 ml, 下沉 mm)，按文献报道的范围取值
PRESETS = {
    "示意阵列 3×7 + 18（假设参数）": dict(NX=3, NY=7, PITCH=3.0, SMALL=True, SMALL_LAYOUT="rows", STIM_REACH=3.0, REC_REACH_L=3.0, REC_REACH_S=1.5, CONTACT_D=1.0),
    "INBRAIN 首次人体试验器件（12 大 + 48 小，排布为假设）": dict(NX=3, NY=4, PITCH=3.0, SMALL=True, SMALL_LAYOUT="stagger", SMALL_N=48, STIM_REACH=3.0, REC_REACH_L=3.0, REC_REACH_S=1.5, CONTACT_D=1.0),
    "INBRAIN 3×7 按官网照片（间距 4 mm）": dict(NX=3, NY=7, PITCH=4.0, SMALL=True, SMALL_LAYOUT="stagger", STIM_REACH=5.0, REC_REACH_L=5.0, REC_REACH_S=3.0),
    "传统条带 1×4（间距 10 mm）": dict(NX=1, NY=4, PITCH=10.0, SMALL=False, STIM_REACH=5.0, REC_REACH_L=5.0, REC_REACH_S=3.0),
    "传统条带 1×8": dict(NX=1, NY=8, PITCH=10.0, SMALL=False, STIM_REACH=5.0, REC_REACH_L=5.0, REC_REACH_S=3.0),
    "传统栅格 4×5": dict(NX=4, NY=5, PITCH=10.0, SMALL=False, STIM_REACH=5.0, REC_REACH_L=5.0, REC_REACH_S=3.0),
}

# 器件库：Resources/Settings/devices.json（有就用它覆盖上面的内置预设）
DEVICE_FILE = os.path.join(HERE, "Resources", "Settings", "devices.json")
DEVICE_NOTES = {}


def load_devices():
    try: lib = json.load(open(DEVICE_FILE, encoding="utf-8"))
    except Exception: return
    keys = ["NX", "NY", "PITCH", "SMALL", "STIM_REACH", "REC_REACH_L", "REC_REACH_S"]
    PRESETS.clear()
    for d in lib.get("devices", []):
        PRESETS[d["name_zh"]] = {k: d[k] for k in keys}
        PRESETS[d["name_zh"]]["SMALL_LAYOUT"] = d.get("SMALL_LAYOUT", "cells")
        if d.get("SMALL_N"): PRESETS[d["name_zh"]]["SMALL_N"] = int(d["SMALL_N"])
        if d.get("contact_diameter"): PRESETS[d["name_zh"]]["CONTACT_D"] = d["contact_diameter"]
        EN[d["name_zh"]] = d["name"]; DEVICE_NOTES[d["name_zh"]] = (d.get("note_zh", ""), d.get("note", ""))


load_devices()
SCEN_NAMES = [("MAIN", "INBRAIN 流程"), ("STD", "传统流程（1×4 条带）")]


# 骨窗预设：(名字, 形状序号 0 圆 / 1 椭圆 / 2 圆角矩形, 参数)
WIN_PRESETS = [("自定义（按下面的参数）", None, {}),
               ("颞顶：椭圆 80 × 60，前后向", 1, dict(WIN_LEN=80, WIN_WID=60, WIN_ANGLE=0)),
               ("额颞（翼点）：椭圆 80 × 60，斜 45°", 1, dict(WIN_LEN=80, WIN_WID=60, WIN_ANGLE=45)),
               ("顶部凸面：圆形半径 35", 0, dict(WINDOW_R=35)),
               ("额部：圆角矩形 70 × 60，前后向", 2, dict(WIN_LEN=70, WIN_WID=60, WIN_ANGLE=0, WIN_CORNER=10))]

# 网页版 3D 模板：three.js r128（cdnjs / jsdelivr，固定版本），图层可开关，脑表面透明度可调
WEB_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>body{margin:0;background:#fff;font:13px Helvetica,Arial,sans-serif}#ui{position:absolute;top:8px;left:8px;background:rgba(255,255,255,.92);padding:8px 10px;border-radius:6px;max-height:92vh;overflow:auto;box-shadow:0 1px 4px rgba(0,0,0,.2)}
#ui label{display:block;white-space:nowrap}.sw{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 4px}#info{position:absolute;bottom:8px;left:8px;background:rgba(255,255,255,.9);padding:6px 10px;border-radius:6px;max-width:60vw}
.lbl{position:absolute;font-weight:bold;color:#111;text-shadow:0 0 3px #fff;pointer-events:none}</style></head><body>
<div id="ui"><b>Layers</b><div id="ly"></div>__OPACITY__ <input id="op" type="range" min="0" max="100" value="50"></div><div id="info">__INFO__</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const D=__DATA__, C=__CENTER__; const R=new THREE.WebGLRenderer({antialias:true}); R.setSize(innerWidth,innerHeight); R.setClearColor(0xffffff); document.body.appendChild(R.domElement);
const S=new THREE.Scene(); S.add(new THREE.AmbientLight(0xffffff,.55)); const dl=new THREE.DirectionalLight(0xffffff,.7); S.add(dl);
const cam=new THREE.PerspectiveCamera(35,innerWidth/innerHeight,1,5000); cam.up.set(0,0,1); cam.position.set(C[0]+400,C[1],C[2]); const ctl=new THREE.OrbitControls(cam,R.domElement); ctl.target.set(C[0],C[1],C[2]); ctl.update();
const col=c=>new THREE.Color(c[0],c[1],c[2]); const objs=[], labels=[];
D.forEach((L,i)=>{let o;
 if(L.type=="mesh"){const g=new THREE.BufferGeometry(); g.setAttribute("position",new THREE.Float32BufferAttribute(L.v,3)); g.setIndex(L.f); g.computeVertexNormals();
   o=new THREE.Mesh(g,new THREE.MeshPhongMaterial({color:col(L.color),transparent:L.opacity<1,opacity:L.opacity,side:THREE.DoubleSide,depthWrite:L.opacity>=.99}));}
 else if(L.type=="points"){const g=new THREE.BufferGeometry(); g.setAttribute("position",new THREE.Float32BufferAttribute(L.v,3)); o=new THREE.Points(g,new THREE.PointsMaterial({color:col(L.color),size:L.size,transparent:L.opacity<1,opacity:L.opacity}));}
 else if(L.type=="lines"){o=new THREE.Group(); const m=new THREE.LineBasicMaterial({color:col(L.color)}); L.lines.forEach(p=>{const g=new THREE.BufferGeometry(); g.setAttribute("position",new THREE.Float32BufferAttribute(p,3)); o.add(new THREE.Line(g,m));});}
 else if(L.type=="label"){const d=document.createElement("div"); d.className="lbl"; d.textContent=L.text; document.body.appendChild(d); labels.push([L.p,d]); return;}
 o.visible=L.visible; S.add(o); objs.push([L,o]);
 const lab=document.createElement("label"); const cb=document.createElement("input"); cb.type="checkbox"; cb.checked=L.visible; cb.onchange=()=>o.visible=cb.checked;
 const sw=document.createElement("span"); sw.className="sw"; sw.style.background=L.color?"#"+col(L.color).getHexString():"#000"; lab.append(cb,sw,L.name); document.getElementById("ly").append(lab);});
document.getElementById("op").oninput=e=>objs.forEach(([L,o])=>{if(L.type=="mesh"&&L===D[0]){o.material.opacity=e.target.value/100;o.material.transparent=true;o.material.depthWrite=e.target.value>=99;}});
function loop(){requestAnimationFrame(loop); dl.position.copy(cam.position); R.render(S,cam); labels.forEach(([p,d])=>{const v=new THREE.Vector3(...p).project(cam); d.style.display=v.z<1?"block":"none"; d.style.left=((v.x+1)/2*innerWidth)+"px"; d.style.top=((1-v.y)/2*innerHeight)+"px";});}
addEventListener("resize",()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();R.setSize(innerWidth,innerHeight);}); loop();
</script></body></html>"""

# 3D 显示样式：(键, 中文, English, 类型, 匹配, 默认颜色, 默认透明度)
#   类型 model = 模型节点名前缀匹配；plan = 放置计划（Plan_k_large / Plan_k_small）；seg = 分割里的段（按标签号结尾）
STYLES = [
    ("stim", "刺激目标区（橙色面，仅参考）", "Stimulation target area (orange patch, reference only)", "model", ["Targets_stim"], (1.00, 0.45, 0.10), 0.5),
    ("rec", "记录目标区（蓝色面，仅参考）", "Recording target area (blue patch, reference only)", "model", ["Targets_rec"], (0.35, 0.65, 1.00), 0.35),
    ("out", "骨窗外目标区（灰色面）", "Targets outside window (grey patch)", "model", ["Targets_out"], (0.60, 0.60, 0.60), 0.3),
    ("entry", "入口点", "Entry point", "model", ["Entry_point"], (0.10, 0.10, 0.10), 1.0),
    ("window", "骨窗边缘", "Window edge", "model", ["Window_edge"], (0.25, 0.25, 0.25), 1.0),
    ("vein", "表面大静脉（SWI）", "Surface veins (SWI)", "model", ["Veins_surface"], (0.15, 0.18, 0.50), 0.85),
    ("bnd", "切除边界（绿 可分离 / 青 仅功能可判 / 黄 仅确认边界 / 红 未判定）", "Resection boundary (green separable / teal function only / yellow edge only / red undecided)", "multi", ["Boundary_"], (0.5, 0.5, 0.5), 1.0),
    ("large", "大触点", "Large contacts", "plan", ["_large"], (0.20, 0.25, 0.35), 1.0),
    ("small", "小触点", "Small contacts", "plan", ["_small"], (0.55, 0.60, 0.68), 1.0),
    ("cst", "皮质脊髓束 CST", "Corticospinal tract (CST)", "model", ["tract_CST"], (0.00, 0.72, 0.72), 1.0),
    ("af", "弓状束 AF/SLF", "Arcuate fasciculus (AF/SLF)", "model", ["tract_AF"], (0.85, 0.30, 0.75), 1.0),
    ("core", "肿瘤核心（强化 + 坏死）", "Tumour core (enhancing + necrosis)", "seg", ["tumor", "4", "1", "3"], (0.50, 0.06, 0.12), 0.85),
    ("flair", "FLAIR 浸润带", "FLAIR infiltration zone", "seg", ["tumor", "2"], (0.80, 0.75, 0.95), 0.12),
    ("brain", "脑表面", "Brain surface", "seg", ["brain", ""], (0.85, 0.78, 0.72), 0.5),
    ("skull", "颅骨（开窗后）", "Skull (with window)", "seg", ["颅骨_开窗", ""], (0.93, 0.90, 0.82), 1.0),
    ("flap", "取下的骨瓣", "Removed bone flap", "seg", ["骨瓣", ""], (0.85, 0.85, 0.85), 0.08),
    ("em_good", "入口评分：好", "Entry score: good", "model", ["EntryMap_good"], (0.10, 0.75, 0.20), 1.0),
    ("em_mid", "入口评分：中", "Entry score: medium", "model", ["EntryMap_mid"], (0.95, 0.85, 0.20), 1.0),
    ("em_poor", "入口评分：差", "Entry score: poor", "model", ["EntryMap_poor"], (1.0, 0.55, 0.10), 1.0),
    ("em_ex", "不能开颅区域", "Excluded region", "model", ["EntryMap_excluded"], (0.35, 0.35, 0.35), 0.6),
    ("order", "放置顺序编号", "Placement order labels", "markup", ["Order_labels"], (0.10, 0.10, 0.10), 1.0),
    ("path", "放置路径", "Placement path", "markup", ["Order_path"], (0.30, 0.30, 0.38), 1.0),
]
# 出厂样式可以在 Resources/Settings/styles.json 里改，不用动代码
STYLE_FILE = os.path.join(HERE, "Resources", "Settings", "styles.json")


def load_style_defaults():
    try: cfg = json.load(open(STYLE_FILE, encoding="utf-8")).get("layers", {})
    except Exception: return
    for i, st in enumerate(STYLES):
        c = cfg.get(st[0])
        if c: STYLES[i] = st[:5] + (tuple(float(x) for x in c["color"]), float(c["opacity"]))


load_style_defaults()

# 脑区图谱：每个脑区的阳性先验权重，以及按肿瘤位置给的任务建议（Resources/Settings/eloquence.json）
ELOQ_FILE = os.path.join(HERE, "Resources", "Settings", "eloquence.json")
try: ELOQ = json.load(open(ELOQ_FILE, encoding="utf-8"))
except Exception: ELOQ = {"regions": {}, "groups": {}, "atlas": {}}
ATLAS_KEY = "INBRAINPlanner/AtlasDir"


def region_name(lab):
    r = ELOQ["regions"].get(str(int(lab)))
    return (r["name_zh"] if lang() == "zh" else r["name"]) if r else ""


# 计算缓存：Slicer 命令行模块要纯英文路径，计算放这里，结果同步到“病例文件夹名_Slicer”
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".inbrain_planner")
STYLE_KEY = "INBRAINPlanner/Style4/"     # 改过默认值时换版本号，旧的个人设置不再覆盖新默认


# 预处理每个脚本日志里的里程碑（用来推进度条）
MILESTONES = {
    "s0_flip.py": ["flip none", "flip x", "flip y", "flip z", "BEST"],
    "s1_dti.py": ["gradient flip", "dti status", "fa status", "elastix done|saved without", "_DWI_to_T1c.h5|saved without"],
    "s2_tract.py": ["CST seed", "CST status", "CST kept", "AF seed", "AF status", "AF kept"],
}
STEP_NAME = {"s0_flip.py": ("梯度翻转检查", "Gradient flip check"), "s1_dti.py": ("张量、FA、配准", "Tensor, FA, registration"),
             "s2_tract.py": ("纤维束追踪", "Tractography")}


def slicer_exe():
    for c in [getattr(slicer.app, "launcherExecutableFilePath", ""), "/Applications/Slicer.app/Contents/MacOS/Slicer"]:
        if c and os.path.exists(c): return c
    return "Slicer"


THEME = """
/* INBRAIN Planner —— 只负责观感：颜色、圆角、间距、字体层级 */
QLabel { color: #26302d; }
QLabel#muted { color: #77837f; }
QLabel#valueCard { background: #f4faf7; border: 1px solid #cfe6dc; border-radius: 8px; padding: 10px 12px; }
QFrame#topBar { border: none; border-bottom: 1px solid #e6ece9; }
QPushButton { padding: 5px 10px; border: 1px solid #ccd6d2; border-radius: 6px; background: #ffffff; color: #1f2933; }
QPushButton:hover { background: #f1f7f4; border-color: #9dc4b5; }
QPushButton:pressed { background: #e5f1eb; }
QPushButton:disabled { color: #9aa5a1; background: #f6f8f7; border-color: #e4e9e7; }
QPushButton#primary { background: #1c7a61; border-color: #186b55; color: #fffffe; font-weight: 600; padding: 7px 12px; }
QPushButton#primary:hover { background: #21886c; }
QPushButton#primary:disabled { background: #a9c9bd; border-color: #a9c9bd; }
QPushButton#accent { color: #1c7a62; border-color: #a9c9bd; font-weight: 600; }
QPushButton#accent:hover { background: #eef7f2; }
QPushButton#danger { color: #b3261e; border-color: #e7c6c2; }
QPushButton#danger:hover { background: #fdf3f2; }
QPushButton#danger:disabled { color: #c9b4b1; border-color: #efe3e1; background: #fbfafa; }
QLineEdit, QComboBox { padding: 3px 6px; border: 1px solid #d6ded9; border-radius: 5px; background: #ffffff; }
/* QDoubleSpinBox 保持系统原生外观：加样式会让上下箭头消失 */
QLineEdit:focus, QComboBox:focus { border-color: #1c7a62; }
QComboBox::drop-down { border: none; width: 18px; }
QTableWidget { border: 1px solid #e0e7e3; border-radius: 6px; background: #ffffff; alternate-background-color: #f7faf8; selection-background-color: #dcefe7; selection-color: #11201b; gridline-color: transparent; }
QTableWidget::item { padding: 4px 6px; border: none; }
QHeaderView::section { background: #f1f6f3; color: #37473f; padding: 5px 6px; border: none; border-bottom: 1px solid #e0e7e3; font-weight: 600; }
QProgressBar { border: 1px solid #dfe6e2; border-radius: 5px; background: #f5f7f6; height: 10px; text-align: center; font-size: 10px; color: #37473f; }
QProgressBar::chunk { background: #1c7a61; border-radius: 4px; }
QPlainTextEdit { background: #fbfcfc; border: 1px solid #e0e7e3; border-radius: 6px; font-family: "Menlo", "Consolas", monospace; font-size: 11px; color: #2f3b37; }
QCheckBox { spacing: 6px; }
/* 分节标题条：浅灰底，和展开后的白色内容区分开 */
ctkCollapsibleButton { background: #e8edea; border: 1px solid #d7dedb; border-radius: 6px; }
ctkCollapsibleButton QWidget#sectionBody { background: #ffffff; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; }
"""

# 鼠标移到参数上显示的说明：(中文, English)。没列在这里的参数用参数表里原有的提示
PARAM_TIPS = {
    "STIM_I": ("刺激能查到多大范围按电流算：r = √(I/k) + 触点半径。参考资料里 Penfield 法从 1 mA 起、最高 20 mA；8 mA 时单极半径约 3 mm",
               "Stimulation reach from current: r = √(I/k) + contact radius. the reference material gives Penfield stimulation from 1 mA up to 20 mA; at 8 mA the monopolar radius is about 3 mm"),
    "K_RANCK": ("电流–距离关系 I = k·r² 里的兴奋常数。1292 µA/mm² 是在皮层锥体细胞上测的，文献范围约 100–4000；是微刺激的数，用到宏刺激只是近似",
                "Excitability constant in I = k·r². 1292 µA/mm² was measured on cortical pyramidal cells; reported values span about 100–4000. It comes from microstimulation, so for macro contacts it is an approximation"),
    "CONTACT_D": ("刺激触点直径，加进激活半径。参考资料：INBRAIN 大触点约 1 mm、小触点 25 µm",
                  "Diameter of the stimulating contact, added to the activation radius. Reference material: INBRAIN large contacts about 1 mm, small ones 25 µm"),
    "BIPOLAR_SPREAD": ("语言段按 Penfield 双极刺激：相邻两个触点一对，电流集中在两者之间，两个触点和它们的中点都能测，但半径只按单极的这个比例；运动段按 Taniguchi 单极",
                       "Language segments use Penfield bipolar stimulation: two neighbouring contacts form a pair and current stays between them, so both contacts and their midpoint can test tissue, with a radius this fraction of the monopolar one; motor segments use Taniguchi monopolar"),
    "STRIP_CD": ("传统流程里探针在条带触点处刺激，激活半径按这个触点大小算",
                 "In the conventional workflow the probe stimulates at strip contacts; the activation radius uses this contact size"),
    "FMRI_Z": ("fMRI 激活图的 z 阈值：低于阈值视为无激活，达到 2 倍阈值时激活权重为 1", "z threshold of the fMRI map: below it counts as no activation, twice the threshold gives full weight"),
    "FMRI_W": ("段风险 × (1 + 权重 × 激活)。激活满分但附近没有纤维束的段，也改成要定位", "Segment risk × (1 + weight × activation). A fully activated segment with no tract nearby also needs mapping"),
    "NTMS_R": ("术前 nTMS 阳性点周围多大范围内的边界段算受影响", "Boundary segments within this distance of an nTMS positive point are affected"),
    "NTMS_W_MOTOR": ("nTMS 运动阳性点：受影响段的风险 × (1 + 权重)；原来不需定位的段改为需定位。nTMS 运动定位与术中电刺激一致性好", "nTMS motor positive points: affected segment risk × (1 + weight); segments that did not need mapping now do. nTMS motor mapping agrees well with intraoperative stimulation"),
    "NTMS_W_LANG": ("nTMS 语言阳性点的权重。nTMS 语言定位与术中电刺激的一致性不稳定，默认权重较低", "Weight of nTMS language positive points. Agreement of nTMS language mapping with intraoperative stimulation is inconsistent, so the default weight is lower"),
    "NX": ("阵列横向有几列大触点（大触点能刺激也能记录）", "Number of large-contact columns across the array (large contacts can stimulate and record)"),
    "NY": ("阵列纵向有几行大触点；3×7 = 21 个大触点", "Number of large-contact rows along the array; 3×7 = 21 large contacts"),
    "PITCH": ("相邻大触点中心之间的距离；示意阵列 3 mm（假设），商用条带 10 mm", "Centre-to-centre distance of neighbouring large contacts; INBRAIN case parameters 3 mm, commercial strips 10 mm"),
    "REC_REACH_L": ("一个大触点能“听到”多远的皮层活动（被动记录的半径）", "How far a large contact can pick up cortical activity (passive recording radius)"),
    "REC_REACH_S": ("小触点只记录不刺激，记录半径比大触点小", "Small contacts only record; their recording radius is smaller than that of large contacts"),
    "TRACT_NEAR": ("皮层点与 CST/AF 纤维束的距离小于该值时，视为纤维束皮层入口（潜在功能区）", "How close a cortical point must be to the CST/AF tract to count as a tract entry (possible eloquent cortex)"),
    "REC_FLAIR": ("离 FLAIR 浸润带多近的皮层要记录（监测后放电、找浸润）", "Cortex this close to the FLAIR zone is a recording target (after-discharges, infiltration)"),
    "REC_LESION": ("距病灶该距离以内的皮层纳入记录区", "Cortex within this distance of the lesion is included in the recording area"),
    "WIN_R_LIMIT": ("FLAIR 残留估计高于 5 cm³ 时，入口不动、逐步扩大骨窗重新规划，最多扩到这个半径（50 mm ≈ 79 cm²，常见骨瓣面积上限约 80 cm²）", "When the estimated FLAIR residual is above 5 cm³ the window is enlarged around the same entry, up to this radius (50 mm ≈ 79 cm², common flap areas reach about 80 cm²)"),
    "NCE_STEP_MIN": ("每扩大一步，FLAIR 残留估计至少要减少这么多才采用；否则停止，避免为了很小的收益开更大的骨窗", "Each enlargement step must reduce the estimated FLAIR residual by at least this much, otherwise it stops; avoids a larger craniotomy for a tiny gain"),
    "EXPOSE_MIN": ("先评分再定骨窗时，骨窗边缘至少要离肿瘤在皮层上的投影这么远。“小骨窗”一般定义为不超出肿瘤最大直径（深部肿瘤按皮层投影）1 cm",
                   "When the window is fitted after scoring, its edge stays at least this far outside the tumour's projection on the cortex. A small craniotomy is usually defined as no more than 1 cm beyond the tumour's maximal diameter (cortical projection for deep tumours)"),
    "EXPOSE_MAX": ("定制骨窗一般只露出肿瘤和外面 2–3 cm 皮层。骨窗比这大时在检查里提示",
                   "Tailored craniotomies usually expose the tumour plus 2–3 cm of cortex. A larger window is flagged in the checks"),
    "WINDOW_R": ("圆形骨窗的半径；35 mm ≈ 7 cm 直径的骨瓣", "Radius of a circular bone window; 35 mm ≈ 7 cm diameter flap"),
    "WIN_CORNER": ("圆角矩形骨窗四个角的圆角半径", "Corner radius of the rounded-rectangle window"),
    "MIDLINE_EX": ("骨窗边缘与中线的最小距离（上矢状窦、大脑镰，出血风险高）", "No window edge closer than this to the midline (superior sagittal sinus, falx: bleeding risk)"),
    "MIDLINE_CAUTION": ("比禁区远、但仍在这个距离内的入口会扣分", "Entries beyond the exclusion zone but within this distance are penalised"),
    "T_PLACE": ("放置或重新放置一次电极所需时间（含位置确认和拍照）", "Time to place or move an electrode once (incl. checking position and photo)"),
    "T_LANG": ("测一个语言位点：至少 3 次不连续刺激 + 命名任务", "Time per language site: at least 3 non-consecutive stimulations with naming"),
    "T_MOTOR": ("测一个运动位点所需时间", "Time per motor site"),
    "OV_PROBE": ("手持探针每更换一个刺激位点的额外时间（移动探针、放置编号标签）", "Extra time per site with a hand-held probe (move the probe, place a number tag)"),
    "OV_ARRAY": ("阵列上换一个触点刺激的额外时间（只是电子切换）", "Extra time to switch to another contact on the array (electronic switching only)"),
    "T_WAKE": ("清醒期开始时，从停镇静药到病人能配合语言测试的时间。两种流程相同", "Time from stopping sedation until the patient can cooperate with language testing. Same for both workflows"),
    "T_BASE": ("刺激前做一轮基线命名，确认病人基础表现。两种流程相同", "One round of baseline naming before stimulation. Same for both workflows"),
    "T_MON": ("清醒状态下切除到骨窗内（阵列可达）每个需定位的边界段时，持续做语言或运动任务监测的时间。两种流程相同", "Awake task monitoring while resecting at each boundary segment that needs mapping and is reachable in the window. Same for both workflows"),
    "STRIP_CCEP_EXTRA": ("传统流程：每个麻醉期 CCEP 位置还要多放几次条带。1×N 条带刺激端和记录端需分开放置（或挪动一次）；阵列在同一次放置内刺激并记录。此项为按 CCEP 原理的假设", "Conventional: extra strip placements per asleep CCEP site, since stimulating and recording need separate strips (or a move); the array stimulates and records in one placement. Assumption based on how CCEP works"),
    "PASSIVE_N": ("麻醉期被动任务记录只在前 N 次放置做；其余放置只做 CCEP", "Asleep passive task recording only on the first N placements; the rest get CCEP only"),
    "T_PASSIVE": ("每次放置做一轮任务记录（被动高 γ 定位）所需时间", "Duration of one task recording per placement (passive high-gamma mapping)"),
    "P_TRUE": ("候选语言位点里真正有语言功能的比例（假设值）", "Fraction of candidate language sites that are truly eloquent (assumption)"),
    "F_CCEP": ("麻醉期 CCEP 筛查后仍阳性、需要醒来确认的触点比例（假设值）", "Fraction of contacts still positive after asleep CCEP screening, to confirm awake (assumption)"),
    "T_CCEP": ("每次麻醉期放置做 CCEP（单脉冲刺激看诱发电位）所需时间", "Time for CCEP (single-pulse evoked potentials) per asleep placement"),
    "CCEP_SENS": ("CCEP 能查出真语言位点的比例（假设值）", "Share of true language sites detected by CCEP (assumption)"),
    "AWAKE_WINDOW": ("病人能配合任务的清醒时间上限；文献平均约 98 min，超过约 120 min 易疲劳", "Usable awake time; literature mean about 98 min, fatigue beyond about 120 min"),
    "STRIP_PITCH": ("商用条带相邻触点的间距（如 DIXI 条带 10 mm）", "Contact spacing of the commercial strip (e.g. DIXI strips 10 mm)"),
    "CST_STOP_FA": ("FA 低于这个值时 CST 追踪停止；水肿区 FA 较低，阈值过高时追踪会中断", "CST tracking stops below this FA; oedema lowers FA, too high breaks the tract"),
    "AF_SEED_FA": ("AF 纤维追踪起点的 FA 下限", "Minimum FA to seed AF tracking"),
    "N_STRIP": ("每例使用的条带数（同一条带可多次重新放置）", "Strips used per case (one strip can be moved repeatedly)"),
    "SEG_LEN": ("切除边界按这个长度分段，每段需给出是否可扩大切除的结论（1 cm = 临床阴性定位间距）", "The resection boundary is split into segments this long; each needs a resect / keep decision (1 cm = clinical negative-mapping spacing)"),
    "SUPRA": ("边界上一个测试点 + 边界外该距离处一个测试点：两处均为阴性时，可将切除范围扩大此距离", "One test site on the boundary + one this far outside: if both are negative, the resection can be extended by this distance"),
    "W_VEIN": ("开颅入口 10 mm 内有 SWI 大静脉、或通道经过大静脉时扣的分；0 = 不用 SWI", "Penalty when an SWI vein lies within 10 mm of the entry or the corridor passes it; 0 = ignore SWI"),
}

# 勾选框、下拉框的说明：控件属性名 → (中文, English)
WIDGET_TIPS = {
    "side": ("肿瘤在左还是右半球；自动判断按肿瘤中心离中线的方向，离中线 < 10 mm 时请手动确认", "Hemisphere of the tumour; auto uses the side of the tumour centre, confirm manually when it is < 10 mm from the midline"),
    "preset": ("器件预设：INBRAIN 3×7 阵列或商用条带；也可以导入自定义器件 JSON", "Device preset: INBRAIN 3×7 array or commercial strip; a custom device JSON can be imported"),
    "small": ("INBRAIN 大触点之间还有只记录的小触点（按官网图读出）；商用条带没有", "INBRAIN has record-only micro-contacts between large contacts (read from the official figure); commercial strips do not"),
    "entryMode": ("开颅中心怎么定：自动评分、离肿瘤核心最近、手动点选，或以肿瘤投影为中心", "How the craniotomy centre is chosen: automatic score, closest to the tumour core, manual click, or centred on the tumour projection"),
    "winPreset": ("常用骨窗尺寸和形状的快捷设置", "Shortcut for common window sizes and shapes"),
    "winShape": ("骨窗形状：圆形、椭圆或圆角矩形；椭圆和矩形可设长宽和方向", "Window shape: circle, ellipse or rounded rectangle; ellipse and rectangle take length, width and angle"),
    "skullSrc": ("颅骨来源：有 CT 或颅骨分割时使用，否则在脑表面外模拟颅骨", "Skull source: use a CT or skull segmentation if available, otherwise simulate a skull shell outside the brain"),
    "autoSkull": ("生成方案后自动画出颅骨，并按骨窗挖开", "After planning, build the skull automatically and cut out the window"),
    "bndFlair": ("默认用强化核心外缘做切除边界；勾选后改用 FLAIR 外缘（扩大切除）", "By default the enhancing-core edge is the resection boundary; tick to use the FLAIR outer edge (supramaximal)"),
    "asleepFirst": ("第一次放置在麻醉期完成，清醒期无需重新放置", "The first array is placed while asleep, so it need not be placed again after waking"),
    "motorAwake": ("运动定位放在清醒期做；不勾 = 麻醉下用 MEP（运动诱发电位）", "Do motor mapping awake; unticked = asleep with MEP (motor evoked potentials)"),
    "autoShift": ("按肿瘤体积估计开颅后脑表面下沉多少（文献：体积越大移位越大），侧向移位取下沉的 0.4 倍", "Estimate cortical sinking from tumour volume (larger tumours shift more); lateral shift = 0.4 × sinking"),
    "usePrior": ("按图谱里各脑区的阳性率给边界段加权：高阳性脑区的段优先判定", "Weight stimulation targets by the literature positive rate of their atlas region: high-yield regions first"),
    "layoutBox": ("视图布局", "View layout"),
}

# 深色模式：Slicer 用深色外观（Dark Slicer 或系统深色）时，把上面和结果卡片里的浅色逐个换成深色版本
# 同一个颜色在浅色下作用不同时故意写成相差 1 的值（如 #1c7a62 = 强调文字，#fffffe = 主按钮白字）以便分开映射
DARK_MAP = {
    "#26302d": "#e3e8e6", "#77837f": "#9aa6a2", "#f4faf7": "#1f2f29", "#cfe6dc": "#2f5446", "#e6ece9": "#3a4240",
    "#ccd6d2": "#4a5552", "#ffffff": "#2b3130", "#1f2933": "#e3e8e6", "#f1f7f4": "#34403c", "#9dc4b5": "#4f8f78",
    "#e5f1eb": "#3a4a44", "#9aa5a1": "#6b7572", "#f6f8f7": "#262b2a", "#e4e9e7": "#363d3b", "#a9c9bd": "#3d5e52",
    "#1c7a62": "#5fc9a8", "#eef7f2": "#2c3d36", "#b3261e": "#ff8a80", "#e7c6c2": "#6b3a36", "#fdf3f2": "#3a2a29",
    "#c9b4b1": "#6e5e5c", "#efe3e1": "#3e3433", "#fbfafa": "#262b2a", "#d6ded9": "#4a5552", "#e0e7e3": "#3a4240",
    "#f7faf8": "#2f3534", "#dcefe7": "#2f5446", "#11201b": "#e8f3ee", "#f1f6f3": "#323a38", "#37473f": "#c9d3cf",
    "#dfe6e2": "#3a4240", "#f5f7f6": "#262b2a", "#fbfcfc": "#1f2423", "#2f3b37": "#d0d8d5", "#e8edea": "#343b39",
    "#d7dedb": "#444c4a",
    # 结果卡片、检查面板、骨窗提示
    "#0f6b52": "#6fd3b1", "#123f33": "#bfe8da", "#6d7873": "#9aa6a2", "#66736e": "#9aa6a2", "#f8fcfa": "#24302c",
    "#1b7f3b": "#5cc97f", "#b26a00": "#ffb74d", "#b00020": "#ff6b7d", "#666666": "#a0a0a0",
}

def is_dark():
    try: return slicer.app.palette().color(qt.QPalette.Window).lightness() < 128
    except Exception: return False

def themed(text):
    """深色外观下把文本（样式表或富文本）里的浅色值换成深色版本；浅色外观原样返回"""
    if not is_dark(): return text
    import re
    return re.sub(r"#[0-9a-fA-F]{6}", lambda m: DARK_MAP.get(m.group(0).lower(), m.group(0)), text)
