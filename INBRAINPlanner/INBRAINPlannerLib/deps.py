# 依赖扩展检查与自动安装 / dependency extensions: check and auto-install
# 追踪纤维束用 SlicerDMRI，配准用 SlicerElastix。缺哪个就通过 Slicer 的扩展管理器后台下载安装，装完需重启。
import qt, slicer
from INBRAINPlannerLib.i18n import L

# 扩展名 → 它提供的模块名（slicer.modules.<name> 存在就说明已加载）
REQUIRED = (("SlicerDMRI", "tractographylabelmapseeding"), ("SlicerElastix", "elastix"))
_done = {"asked": False}


def missing_extensions():
    """还没加载的依赖扩展名列表"""
    return [ext for ext, mod in REQUIRED if not hasattr(slicer.modules, mod)]


def _headless():
    try: return bool(slicer.app.commandOptions().noMainWindow) or bool(slicer.app.testingEnabled())
    except Exception: return False


def ensure_dependencies(interactive=True):
    """缺依赖时自动下载安装（需联网）。返回缺失的扩展名列表；每个 Slicer 会话只提示一次。"""
    miss = missing_extensions()
    if not miss or _done["asked"] or _headless(): return miss
    _done["asked"] = True
    try:
        em = slicer.app.extensionsManagerModel()
    except Exception:
        em = None
    todo, restart = [], []
    for ext in miss:
        try:
            installed = bool(em and em.isExtensionInstalled(ext))
        except Exception:
            installed = False
        (restart if installed else todo).append(ext)
    failed = []
    for ext in todo:
        try:
            # 第二个参数：连带安装它自己的依赖；第三个：不阻塞界面，后台下载
            ok = em.downloadAndInstallExtensionByName(ext, True, False) if em else False
            if ok is False: failed.append(ext)
        except Exception:
            failed.append(ext)
    if interactive:
        lines = []
        started = [e for e in todo if e not in failed]
        if started:
            lines.append(L("正在后台下载并安装：%s。完成后请重启 Slicer。", "Downloading and installing in the background: %s. Restart Slicer when it finishes.") % ", ".join(started))
        if restart:
            lines.append(L("已安装但尚未加载：%s。请重启 Slicer。", "Installed but not loaded yet: %s. Please restart Slicer.") % ", ".join(restart))
        if failed:
            lines.append(L("无法自动安装：%s。请检查网络，或在 Extensions Manager 里手动安装后重启。", "Could not install automatically: %s. Check the network, or install from the Extensions Manager and restart.") % ", ".join(failed))
        title = L("INBRAIN Planner 需要的扩展", "Extensions required by INBRAIN Planner")
        try:
            qt.QTimer.singleShot(0, lambda: slicer.util.infoDisplay("\n\n".join(lines), windowTitle=title))
        except Exception:
            print("INBRAIN Planner:", " ".join(lines))
    return miss
