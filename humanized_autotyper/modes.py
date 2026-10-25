"""modes.py — 「模式」抽象：把目标编辑器/文档形态从状态机里拆出来。

AutoTyper 的主循环 (`machine.py::AutoTyper.run`) 本身不认识"文档"也不认识
"编辑器"——它只消费 Target 列表并对每个 Target 跑一遍既有的打字状态机。
模式负责回答三个问题：

1. **要写哪些内容** —— `iter_targets()`
2. **怎么把编辑器定位到某个 Target** —— `before_type()`
3. **写完怎么确认真的写对了** —— `after_type()`，以及
   `verify_trustworthy()` 声明「内存缓冲区是否还能代表真实文档」

`SingleFileMode` 包装 1.x 的既有行为（单文件 / 内置 demo / source.txt），
用于保证这一步重构**零功能变化**；后续 VSCode 模式只需要新增一个子类。
"""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Target:
    """一个待写入的文档。"""
    path: str                      # 展示/定位用（相对路径，正斜杠）
    content: str                   # 期望写入的完整内容
    abs_path: Optional[str] = None # 磁盘绝对路径（校验用）
    meta: Dict[str, Any] = field(default_factory=dict)


class Mode:
    """模式基类。默认实现是"单个已经拿到手的字符串"，即 1.x 行为。"""

    name = "base"
    label = "基础"
    # 多文件模式需要枚举；单文件模式由调用方直接给出内容。
    multi_target = False

    def iter_targets(self, source: Optional[str] = None,
                     **kwargs) -> List[Target]:
        raise NotImplementedError

    def preflight(self, targets: List[Target]) -> List[str]:
        """返回**阻止启动**的错误列表；空列表表示可以开跑。"""
        return []

    def editor_warnings(self) -> List[str]:
        """仅提示、不阻止启动的注意事项。"""
        return []

    def before_type(self, target: Target, typer) -> None:
        """把编辑器定位到 target（打开文件、光标归位等）。"""

    def save_only(self, target: Target, typer) -> None:
        """交替打字切走前的轻量存盘（不做完整校验）。

        顺序路径不会调用它——after_type 已负责存盘 + 回读校验。默认无动作。
        """

    def after_type(self, target: Target, typer) -> Dict[str, Any]:
        """打完之后的收尾与校验，返回可并入 summary 的字典。"""
        return {}

    def verify_trustworthy(self) -> bool:
        """内存缓冲区是否仍然等于真实文档。

        False 意味着 F10 中断时目标文档可能留下半截内容——此时
        `final_matches_source` 不能作为安全依据，必须靠回读磁盘校验。
        """
        return True


class SingleFileMode(Mode):
    """单文件模式：完整封装 1.x 的行为，供回归对照使用。"""

    name = "notepad"
    label = "单文件（记事本 / 任意编辑器）"

    def __init__(self, source: str, desc: str = "single file"):
        self.source = source
        self.desc = desc

    def iter_targets(self, source: Optional[str] = None,
                     **kwargs) -> List[Target]:
        src = self.source if source is None else source
        return [Target(path=self.desc, content=src)]


MODES = {}


def register_mode(cls):
    MODES[cls.name] = cls
    return cls


def get_mode(name: str):
    """按名字取模式**类**（不是实例）。

    刻意返回类而不是实例：各模式的构造参数不同（SingleFileMode 要 source、
    VSCodeMode 要 src_dir/ext），由调用方按需构造。找不到抛 KeyError，
    调用方负责给出友好提示。
    """
    return MODES[name]


def mode_names() -> List[str]:
    return list(MODES.keys())


# 基础模式即单文件模式，保证不选模式时的行为与 1.x 完全一致
register_mode(SingleFileMode)


def collect_targets(mode: Mode, source: Optional[str] = None,
                    **kwargs) -> List[Target]:
    """枚举目标并跑 preflight；有阻断性错误时抛 ValueError。"""
    targets = mode.iter_targets(source=source, **kwargs)
    problems = mode.preflight(targets)
    if problems:
        raise ValueError("\n".join(problems))
    return targets


# --------------------------------------------------------------- VSCode 模式

# VSCode 默认开启的这些行为会**偷偷改写输入**，让「缓冲区 = 文档」不变式失效，
# 因此本模式要求把它们关掉。值与 VSCode settings.json 里写的字面量一致。
VSCODE_REQUIRED_SETTINGS = {
    "editor.autoIndent": ("none",
                          "打字时会自动插入缩进，缓冲区与文档就此错位"),
    "editor.autoClosingBrackets": ("never", "会自动补全括号/引号"),
    "editor.autoClosingQuotes": ("never", "会自动补全引号"),
    "editor.autoSurround": ("never", "选中文本后再输入会包一层"),
    "editor.quickSuggestions": (False, "会弹建议框，下一个 Enter 可能采纳建议"),
    "editor.acceptSuggestionOnEnter": ("off", "Enter 会接受代码补全建议"),
    "editor.formatOnSave": (False, "存盘时自动格式化，回读比对必然不符"),
    "editor.formatOnType": (False, "输入过程中自动格式化"),
    "editor.detectIndentation": (False,
                                 "会按文件已有内容猜 tab/space，不同文件会不一致"),
}

DEFAULT_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".txt",
                ".json", ".yaml", ".yml")

# 这些目录永远跳过：依赖、构建产物、版本库里塞满无关文件
SKIP_DIRS = frozenset({
    "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
    "dist", "build", "out", "target", ".next", ".nuxt", ".tox", ".mypy_cache",
    ".pytest_cache", ".idea", ".vscode", "coverage", ".gradle", "vendor",
})


class VSCodeMode(Mode):
    """把一个目录下的多个文件逐个打进 VSCode。

    与 SingleFileMode 的根本差异：**内存缓冲区不再等于真实文档**。
    VSCode 会自动缩进/补全/格式化（见 VSCODE_REQUIRED_SETTINGS），而且每个
    文件都会重置缓冲区。因此本模式声明 verify_trustworthy() == False，
    正确性只能靠 after_type() 存盘后回读磁盘来确认。
    """

    name = "vscode"
    label = "VSCode（目录多文件）"
    multi_target = True

    def __init__(self, src_dir: str, exts=None, rel_prefix: str = "",
                 settings_paths=None, max_files: int = 0,
                 open_settle_s: float = 0.6, save_settle_s: float = 0.8):
        self.src_dir = src_dir
        self.exts = tuple(e if e.startswith(".") else "." + e
                          for e in (exts or DEFAULT_EXTS))
        self.rel_prefix = rel_prefix.replace("\\", "/").strip("/")
        self.settings_paths = list(settings_paths
                                  if settings_paths is not None
                                  else self._default_settings())
        # 显式传入时 settings_paths 优先（见 settings_for）
        self._explicit_settings = settings_paths is not None
        self.max_files = max_files
        # Quick Open 是**实时过滤**的：路径一敲完就得给它收敛时间，否则
        # 紧接着的 Enter 可能打开匹配到一半的那个文件。
        self.open_settle_s = open_settle_s
        self.save_settle_s = save_settle_s
        self._settings_cache: Optional[Dict[str, Any]] = None
        # 交替打字会重访同一文件：记录已打开过的路径，重访时不再清空文档，
        # 只把光标压到文末接着打（否则会把已打的一半删掉）。
        self._opened: set = set()

    @staticmethod
    def _default_settings():
        """按优先级从低到高：User -> Workspace。工作区设置覆盖用户设置，
        所以判定时后读的层级覆盖先读的。"""
        appdata = os.environ.get("APPDATA", "")
        return ([os.path.join(appdata, "Code", "User", "settings.json")]
                if appdata else []) + [".vscode/settings.json"]

    # ---------------------------------------------------------- 文件枚举
    def iter_targets(self, source: Optional[str] = None,
                     **kwargs) -> List[Target]:
        root = self.src_dir
        if os.path.isfile(root):
            return [self._make_target(os.path.dirname(root) or ".",
                                      os.path.basename(root))]
        targets: List[Target] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in SKIP_DIRS and not d.startswith("."))
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue          # 隐藏文件（.env / .hidden.py）一律跳过
                if fn.endswith(self.exts):
                    targets.append(self._make_target(dirpath, fn))
        if self.max_files and len(targets) > self.max_files:
            targets = targets[:self.max_files]
        return targets

    def _make_target(self, dirpath, filename) -> Target:
        abs_path = os.path.join(dirpath, filename)
        try:
                # utf-8-sig：源文件常带 UTF-8 BOM。若用纯 utf-8 读，BOM 会变成
                # 内容首字符 U+FEFF——它**打不出来**（KeyCode.from_char 返回
                # None，type_char 静默跳过而 buffer 照样记录），且 0xFEFF > 0x20
                # 所以 unsupported_chars 也抓不到。只能在这里剥掉。
                with open(abs_path, "r", encoding="utf-8-sig") as f:
                    content = f.read()
        except (UnicodeDecodeError, OSError) as exc:
            # 读不出来的文件不该让整轮失败：标记出来，preflight 会报
            return Target(path=self._rel(abs_path), content="",
                          abs_path=abs_path, meta={"error": repr(exc)})
        # 与 main.read_source 一致：统一换行，否则缓冲区记 \r 而编辑器收到回车
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        return Target(path=self._rel(abs_path), content=content,
                      abs_path=abs_path)

    def _rel(self, abs_path) -> str:
        """相对**起始文件夹**的路径（正斜杠）。

        必须是相对 src_dir 而不是 cwd：Quick Open 匹配的是「工作区相对路径」，
        若按 cwd 算，src_dir 在工作区之外时会得到一串 ../../../..，根本匹配不上。
        """
        base = self.src_dir
        if os.path.isfile(base):
            base = os.path.dirname(base) or "."
        try:
            rel = os.path.relpath(abs_path, base)
        except ValueError:                        # 跨盘符
            rel = os.path.basename(abs_path)
        return rel.replace("\\", "/")

    # ---------------------------------------------------------- preflight
    def settings_for(self) -> List[str]:
        """本项目要读哪些 settings.json。

        显式传入 settings_paths 时以它为准（测试用）。否则查 User 级 +
        **当前工作目录**的 .vscode/settings.json；但当 --src-dir 指向别处时，
        工作区设置应该跟着 src_dir 走——否则会误判 "未设置"。
        """
        if self._explicit_settings:
            return self.settings_paths
        local = os.path.join(self.src_dir, ".vscode", "settings.json")
        if os.path.isdir(self.src_dir) and os.path.exists(local):
            return self._default_settings()[:-1] + [local]
        return self._default_settings()

    def _read_settings(self) -> Dict[str, Any]:
        """合并所有层级的 settings.json，后读到的覆盖先读到的。"""
        if self._settings_cache is not None:
            return self._settings_cache
        merged: Dict[str, Any] = {}
        for path in self.settings_for():
            try:
                # utf-8-sig：VSCode / PowerShell 写出的 settings.json 常带 BOM，
                # 用纯 utf-8 读会直接 JSONDecodeError，误判成"配置损坏"。
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as exc:
                merged.setdefault("__errors__", []).append(f"{path}: {exc!r}")
                continue
            if isinstance(data, dict):
                merged.update(data)
        self._settings_cache = merged
        return merged

    def preflight(self, targets: List[Target]) -> List[str]:
        from .keymap import unsupported_chars

        errs: List[str] = []
        if not os.path.isdir(self.src_dir) and not os.path.isfile(self.src_dir):
            errs.append(f"起始文件夹不存在: {self.src_dir}")
            return errs
        if not targets:
            errs.append(f"在 {self.src_dir} 下没找到任何匹配 "
                        f"{'/'.join(self.exts)} 的文件")
        for t in targets:
            if t.meta.get("error"):
                errs.append(f"{t.path}: 读取失败 {t.meta['error']}")
            elif not t.content.strip():
                errs.append(f"{t.path}: 文件为空，没有可输入的内容")
            else:
                bad = unsupported_chars(t.content)
                if bad:
                    shown = ", ".join(f"{i}:{ch!r}" for i, ch in bad[:3])
                    errs.append(f"{t.path}: 含 {len(bad)} 个无法可靠键入的字符"
                                f"（{shown}）")
        settings = self._read_settings()
        for e in settings.get("__errors__", []):
            errs.append(f"settings.json 读取失败: {e}")
        for key, (want, why) in VSCODE_REQUIRED_SETTINGS.items():
            got = settings.get(key, "<未设置>")
            if got != want:
                errs.append(f"VSCode 设置 {key} 当前是 {got!r}，需要 {want!r}"
                            f"——否则{why}")
        return errs

    def editor_warnings(self) -> List[str]:
        return [
            "VSCode 模式下内存缓冲区不等于文档，F10 中断可能留下半截文件；"
            "正确性以存盘后回读磁盘为准。",
            "建议在 git 仓库内运行，出问题可回滚。",
        ]

    def verify_trustworthy(self) -> bool:
        return False

    # ------------------------------------------------------ 定位 / 存盘 / 校验
    def before_type(self, target: Target, typer) -> None:
        """Ctrl+P 打开目标文件，然后把文档清空到起始状态。

        清空这一步不可省：Quick Open 只是**切换**到已打开的标签页，光标还停在
        上次的位置、文档里也留着上次的内容。而 `AutoTyper` 每个文件都从空的
        `Buffer("")` 起步（见 machine._reset_for_target），不清空的话打出来的
        文本会插到旧内容中间，缓冲区与文档从此错位，且回读校验只会报一个
        语焉不详的"长度不同"。

        全程只依赖 Ctrl+A / Delete 两个按键，不依赖光标当前位置——这比"移动到
        文末再逐行删"可靠得多（后者在文件很大时要发上千次按键）。
        """
        ex = typer.executor
        if getattr(typer.cfg, "dry_run", True):
            return                      # dry-run 不发键，但流程照走以便审计
        if self.rel_prefix:
            # src_dir 不是工作区根目录时，Quick Open 需要带前缀
            quick_path = f"{self.rel_prefix}/{target.path}"
        else:
            quick_path = target.path
        ex.key_quick_open()
        typer._sleep(self.open_settle_s, active=False)
        for ch in quick_path:
            ex.type_char(ch)
            typer._sleep(self.open_settle_s / max(1, len(quick_path)),
                         active=False)
        # 关键：等 Quick Open 过滤收敛，否则 Enter 可能打开半匹配的文件
        typer._sleep(self.open_settle_s, active=False)
        ex._tap_special("enter")
        typer._sleep(self.open_settle_s, active=False)

        if target.path in self._opened:
            # 交替打字的重访：文档里已有一半内容，绝不能清空。把光标压到
            # 文末，接着上次的位置继续打。缓冲区此时也恢复到该文件的槽位，
            # 两边都在末尾，对齐。
            ex.key_doc_end()
            typer._sleep(self.open_settle_s / 2, active=False)
            typer.logger.log("FILE", "resumed", target.path, 0)
            return
        self._opened.add(target.path)

        # --- 清空文档（仅首次打开）---
        ex.key_select_all()
        typer._sleep(self.open_settle_s / 2, active=False)
        ex.delete_key()                  # 删掉选区；文件本就为空时是无害的空操作
        typer._sleep(self.open_settle_s / 2, active=False)
        # 光标现在位于文档开头 = 缓冲区起点，两边对齐。
        # 不做断言：此时读不到屏幕，无法证明 VSCode 真的清干净了；
        # 真正的确认在 after_type() 的存盘回读。
        typer.logger.log("FILE", "cleared", target.path, 0)

    def save_only(self, target: Target, typer) -> None:
        """交替打字切走前 Ctrl+S 存一次盘（不做回读校验）。

        与 after_type 的区别：这里内容尚未打完，回读比对必然不一致，所以
        只负责把已打的内容落盘，保证重访时磁盘与缓冲区一致。
        """
        if getattr(typer.cfg, "dry_run", True):
            return
        ex = typer.executor
        ex.key_save()
        typer._sleep(self.save_settle_s, active=False)

    def after_type(self, target: Target, typer) -> Dict[str, Any]:
        """Ctrl+S 存盘，等格式化落盘，然后回读磁盘做权威比对。

        dry-run 下**不能**做这个比对：target.content 本身就是从 abs_path 读
        出来的，中间没写过任何东西，比对必然相等——那是个恒真式，会让人误以为
        "dry-run 验证过了"。所以这里如实返回 ok=None（未校验），由调用方区分。
        """
        ex = typer.executor
        if getattr(typer.cfg, "dry_run", True):
            return {"ok": None, "verified": False,
                    "detail": "dry-run 未发键，未做磁盘校验"}
        ex.key_save()
        typer._sleep(self.save_settle_s, active=False)
        actual = self._read_back(target)
        if actual is None:
            return {"ok": False, "verified": True,
                    "detail": "存盘后读不回文件（可能路径不对）"}
        return self._diff(target.content, actual, target.path)

    def _read_back(self, target: Target) -> Optional[str]:
        if not target.abs_path:
            return None
        # 存盘是异步的（编辑器写盘有延迟），这里重试几次而不是干等一次
        for _ in range(5):
            try:
                with open(target.abs_path, "r", encoding="utf-8-sig") as f:
                    return f.read().replace("\r\n", "\n").replace("\r", "\n")
            except FileNotFoundError:
                return None
            except OSError:
                pass
            time.sleep(0.2)
        return None

    @staticmethod
    def _diff(expected: str, actual: str, path: str) -> Dict[str, Any]:
        """逐字符比对，报告第一个差异的行号——定位到行才有排查价值。"""
        if expected == actual:
            return {"ok": True, "detail": ""}
        n = min(len(expected), len(actual))
        i = 0
        while i < n and expected[i] == actual[i]:
            i += 1
        line = expected.count("\n", 0, i) + 1
        col = i - (expected.rfind("\n", 0, i) + 1) + 1
        detail = (f"{path}: 第 {line} 行第 {col} 列开始不一致 "
                  f"(期望 {expected[i]!r}，实际 {actual[i]!r})"
                  if i < n else
                  f"{path}: 长度不同（期望 {len(expected)}，实际 {len(actual)}）")
        return {"ok": False, "detail": detail, "line": line, "col": col}


register_mode(VSCodeMode)