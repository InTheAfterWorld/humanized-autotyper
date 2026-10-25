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
import shutil
import subprocess
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


def _quick_suggestions_off(value) -> bool:
    """quickSuggestions 既支持 false，也支持按语言分项的对象写法。

    VSCode 的等价写法：
        "editor.quickSuggestions": false
        "editor.quickSuggestions": {"other": "off", "comments": "off",
                                    "strings": "off"}
    省略的键会回落到默认值：comments/strings 默认关，other 默认**开**，
    所以 other 必须显式关掉；写出来的项也不允许是开启状态。
    """
    if value is False:
        return True
    if isinstance(value, dict):
        if value.get("other", True) not in (False, "off"):
            return False
        return all(v in (False, "off") for v in value.values())
    return False


def _setting_ok(key: str, got, want) -> bool:
    if key == "editor.quickSuggestions":
        return _quick_suggestions_off(got)
    return got == want

DEFAULT_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".txt",
                ".json", ".yaml", ".yml")

# 这些目录永远跳过：依赖、构建产物、版本库里塞满无关文件
SKIP_DIRS = frozenset({
    "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
    "dist", "build", "out", "target", ".next", ".nuxt", ".tox", ".mypy_cache",
    ".pytest_cache", ".idea", ".vscode", "coverage", ".gradle", "vendor",
})


def _ensure_file_exists(path: str) -> None:
    """确保目标文件在磁盘上存在，供 VS Code Quick Open 定位。

    VSCode 的 Quick Open 只能打开**已经存在于工作区**的文件：文件若从未
    创建/保存过，Quick Open 找不到它，Enter 也不会打开任何东西，后续的
    Ctrl+A/Delete 会作用在错误的文档上，整轮看起来就像“卡住”了。这里在
    真正发键前把空文件建好（父目录一并创建），让 Quick Open 能定位到它；
    真正的内容随后由打字过程写入并 Ctrl+S 落盘。
    """
    if not path or os.path.exists(path):
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # 使用 "a" 模式避免竞态窗口：若文件在 exists 检查后被其他进程创建，
    # "w" 会将其内容截断为空，而 "a" 不会破坏已有数据。
    with open(path, "a", encoding="utf-8"):
        pass



class VSCodeMode(Mode):
    """把源目录中的多个文件逐个打进目标 VS Code 工作区。

    与 SingleFileMode 的根本差异：**内存缓冲区不再等于真实文档**。
    VSCode 会自动缩进/补全/格式化（见 VSCODE_REQUIRED_SETTINGS），而且每个
    文件都会重置缓冲区。因此本模式声明 verify_trustworthy() == False，
    正确性只能靠 after_type() 存盘后回读磁盘来确认。
    """

    name = "vscode"
    label = "VSCode（目录多文件）"
    multi_target = True

    def __init__(self, src_dir: str, exts=None, rel_prefix: str = "",
                 source_dir: Optional[str] = None,
                 target_dir: Optional[str] = None,
                 workspace_root: Optional[str] = None,
                 locator: str = "auto",
                 require_cli: bool = False,
                 settings_paths=None, max_files: int = 0,
                 open_settle_s: float = 0.6, save_settle_s: float = 0.8):
        # src_dir remains as a compatibility alias for callers from 1.x.
        self.source_dir = source_dir or src_dir
        default_target = (os.path.dirname(self.source_dir)
                          if os.path.isfile(self.source_dir)
                          else self.source_dir)
        self.target_dir = target_dir or default_target
        self.src_dir = self.source_dir
        default_workspace = (os.path.dirname(self.target_dir)
                              if os.path.isfile(self.target_dir)
                              else self.target_dir)
        self.workspace_root = os.path.abspath(
            workspace_root or default_workspace)
        self.locator = locator.lower().strip()
        self.require_cli = require_cli
        if self.locator not in ("auto", "cli", "keyboard"):
            raise ValueError("locator must be one of: auto, cli, keyboard")
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
        # 枚举时跳过的空文件（没有内容可重打）。GUI/CLI 会提示，避免用户
        # 以为这些文件被漏掉了。
        self.skipped_empty: List[str] = []

    @staticmethod
    def _code_command() -> Optional[str]:
        return shutil.which("code") or shutil.which("code.cmd")

    def resolved_locator(self) -> str:
        if self.locator != "auto":
            return self.locator
        return "cli" if self._code_command() else "keyboard"

    def _prepare_workspace_settings(self) -> None:
        """Create target-only safety settings without overwriting user files."""
        if self._explicit_settings:
            return
        path = os.path.join(self.target_dir, ".vscode", "settings.json")
        if os.path.exists(path):
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({key: value for key, (value, _)
                       in VSCODE_REQUIRED_SETTINGS.items()},
                      f, ensure_ascii=False, indent=2)
            f.write("\n")

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
        root = self.source_dir
        self.skipped_empty = []
        if os.path.isdir(root):
            os.makedirs(self.target_dir, exist_ok=True)
            self._prepare_workspace_settings()
        if os.path.isfile(root) or (
                not os.path.isdir(root)
                and os.path.splitext(root)[1].lower() in self.exts):
            if not os.path.isfile(root):
                return []
            target = self._make_target(
                os.path.dirname(root) or ".", os.path.basename(root))
            if not target.meta.get("error") and not target.content.strip():
                self.skipped_empty.append(target.path)
                return []
            return [target]
        targets: List[Target] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
                and not d.lower().endswith(".egg-info"))
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue          # 隐藏文件（.env / .hidden.py）一律跳过
                if fn.endswith(self.exts):
                    target = self._make_target(dirpath, fn)
                    if not target.meta.get("error") and not target.content.strip():
                        # 空文件没有可重打的内容。把它当阻断错误会让目录里
                        # 任何一个空占位文件（test.txt、egg-info 里的空文件）
                        # 卡住整轮；记录后跳过，GUI/CLI 会给出提示。
                        self.skipped_empty.append(target.path)
                        continue
                    targets.append(target)
        if self.max_files and len(targets) > self.max_files:
            targets = targets[:self.max_files]
        return targets

    def _make_target(self, dirpath, filename) -> Target:
        source_path = os.path.join(dirpath, filename)
        source_root = self.source_dir
        if os.path.isfile(source_root):
            source_root = os.path.dirname(source_root) or "."
        rel_path = os.path.relpath(source_path, source_root)
        target_path = os.path.join(self.target_dir, rel_path)
        _ensure_file_exists(target_path)

        try:
                # utf-8-sig：源文件常带 UTF-8 BOM。若用纯 utf-8 读，BOM 会变成
                # 内容首字符 U+FEFF——它**打不出来**（KeyCode.from_char 返回
                # None，type_char 静默跳过而 buffer 照样记录），且 0xFEFF > 0x20
                # 所以 unsupported_chars 也抓不到。只能在这里剥掉。
                with open(source_path, "r", encoding="utf-8-sig") as f:
                    content = f.read()
        except (UnicodeDecodeError, OSError) as exc:
            # 读不出来的文件不该让整轮失败：标记出来，preflight 会报
            return Target(path=self._rel(target_path), content="",
                          abs_path=target_path, meta={"error": repr(exc)})
        # 与 main.read_source 一致：统一换行，否则缓冲区记 \r 而编辑器收到回车
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        return Target(path=self._rel(target_path), content=content,
                      abs_path=target_path,
                      meta={"source_path": os.path.abspath(source_path)})

    def _rel(self, abs_path) -> str:
        """相对**起始文件夹**的路径（正斜杠）。

        必须是相对 src_dir 而不是 cwd：Quick Open 匹配的是「工作区相对路径」，
        若按 cwd 算，src_dir 在工作区之外时会得到一串 ../../../..，根本匹配不上。
        """
        base = self.target_dir
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
        local = os.path.join(self.target_dir, ".vscode", "settings.json")
        if os.path.isdir(self.target_dir) and os.path.exists(local):
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
        if not os.path.isdir(self.source_dir) and not os.path.isfile(self.source_dir):
            errs.append(f"源文件夹不存在: {self.source_dir}")
            return errs
        if not os.path.isdir(self.target_dir):
            errs.append(f"目标文件夹不存在且无法准备: {self.target_dir}")
        if not os.path.isdir(self.workspace_root):
            errs.append(f"VS Code 工作区根目录不存在: {self.workspace_root}")
        else:
            for target in targets:
                if not target.abs_path:
                    continue
                try:
                    inside = (os.path.normcase(os.path.commonpath(
                        [os.path.abspath(target.abs_path),
                         self.workspace_root])) ==
                              os.path.normcase(self.workspace_root))
                except ValueError:
                    inside = False
                if not inside:
                    errs.append(f"{target.path}: 不在 VS Code 工作区根目录 "
                                f"{self.workspace_root} 内")
        if self.require_cli and self.resolved_locator() != "cli":
            errs.append("找不到 VS Code CLI 命令 code。请把 VS Code 的 bin "
                        "目录加入 PATH，或选择 keyboard 定位方式。")
        if not targets:
            errs.append(f"在 {self.source_dir} 下没找到任何匹配 "
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
            if _setting_ok(key, got, want):
                continue
            hint = ""
            if key == "editor.quickSuggestions":
                hint = ('（也可以写成 {"other": "off", "comments": "off", '
                        '"strings": "off"}）')
            errs.append(f"VSCode 设置 {key} 当前是 {got!r}，需要 {want!r}"
                        f"——否则{why}{hint}")
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
        # 文件若尚未创建，Quick Open 定位不到它会“卡住”；这里先建好空文件。
        abs_path = target.abs_path
        if abs_path is not None:
            _ensure_file_exists(abs_path)

        # 先发 Escape 确保 VS Code 处于干净状态（无残留 Quick Open、命令面板、
        # 建议框或通知弹窗），避免定位器在污染状态下操作。
        ex.key_escape()
        typer._sleep(0.1, active=False)

        # 无论首次还是重访，都重新定位到目标文件，确保 VS Code 当前活动编辑器
        # 确实是我们要操作的那个，防止焦点漂移导致后续按键作用于错误文档。
        if self.resolved_locator() == "cli" and target.abs_path:
            self._open_with_cli(target, typer)
        elif self.locator == "cli":
            raise RuntimeError(f"CLI 定位需要目标文件绝对路径: {target.path}")
        else:
            self._open_with_keyboard(target, typer)

        if target.path in self._opened:
            # 文件此前已打开过：内容可能已打了一半，绝对不能清空。
            # 只需把光标压到文末即可接着上次的进度继续输入。
            ex.key_doc_end()
            typer._sleep(self.open_settle_s / 2, active=False)
            typer.logger.log("FILE", "resumed", target.path, 0)
            return
        self._opened.add(target.path)

        # 首次打开：如果文件是由 _ensure_file_exists 刚创建的空文件，
        # 则无需执行危险的 Ctrl+A/Delete，直接开始打字即可。
        # 这降低了"打开错误文件"极端场景下的数据丢失风险。
        is_empty = False
        if abs_path and os.path.exists(abs_path):
            try:
                is_empty = os.path.getsize(abs_path) == 0
            except OSError:
                pass

        if is_empty:
            typer.logger.log("FILE", "empty_skip_clear", target.path, 0)
        else:
            ex.key_select_all()
            typer._sleep(self.open_settle_s / 2, active=False)
            ex.delete_key()
            typer._sleep(self.open_settle_s / 2, active=False)
            typer.logger.log("FILE", "cleared", target.path, 0)

    def _open_with_cli(self, target: Target, typer) -> None:
        command = self._code_command()
        if not command:
            raise RuntimeError("VS Code CLI command 'code' is not available")
        if not target.abs_path:
            raise RuntimeError(f"目标文件没有绝对路径: {target.path}")
        try:
            result = subprocess.run(
                [command, "--reuse-window", "--goto",
                 os.path.abspath(target.abs_path)],
                check=False, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"调用 VS Code CLI 失败: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"VS Code CLI 返回码 {result.returncode}"
                + (f": {detail}" if detail else ""))
        # 即使返回码为0，stderr 中的错误/警告信息也应被重视（某些场景下 CLI
        # 会输出警告但退出码仍为0，如 VS Code 正在更新或窗口未就绪）。
        stderr_text = (result.stderr or "").strip()
        if stderr_text and any(k in stderr_text.lower()
                               for k in ("error", "unable", "failed",
                                         "not found", "warning")):
            raise RuntimeError(
                f"VS Code CLI 报告潜在问题，stderr: {stderr_text}")
        # 给 VS Code 至少 1.0 秒切换标签页（过小值在冷启动、大文件或重载时不可靠）。
        settle = max(self.open_settle_s, 1.0)
        typer._sleep(settle, active=False)
        # 清除可能弹出的通知/欢迎页/对话框，确保后续操作不受阻碍。
        ex = typer.executor
        ex.key_escape()
        typer._sleep(0.2, active=False)
        typer.logger.log("FILE", "located_cli", target.path, 0)

    def _open_with_keyboard(self, target: Target, typer) -> None:
        ex = typer.executor
        # 双重 Escape：彻底清除任何残留的 Quick Open、建议框、命令面板或
        # 多层嵌套模态 UI。单层 Escape 对嵌套场景（如命令面板内打开 Quick Open）
        # 可能不足，导致残留文本与新路径拼接而打开错误文件。
        ex.key_escape()
        typer._sleep(0.1, active=False)
        ex.key_escape()
        typer._sleep(self.open_settle_s / 2, active=False)
        if self.rel_prefix:
            # src_dir 不是工作区根目录时，Quick Open 需要带前缀
            quick_path = f"{self.rel_prefix}/{target.path}"
        else:
            # 始终使用工作区相对路径。绝对路径在 Windows 上含反斜杠与盘符，
            # 与 Quick Open 的相对路径匹配逻辑不兼容，导致定位失败或匹配错误。
            quick_path = target.path
        ex.key_quick_open()
        typer._sleep(self.open_settle_s, active=False)
        for ch in quick_path:
            ex.type_char(ch)
            # 每个字符至少给 30ms：防止长路径时单字符延迟趋近于零，
            # Quick Open 过滤器跟不上输入速度而打开半匹配或错误文件。
            per_char = max(self.open_settle_s / max(1, len(quick_path)), 0.03)
            typer._sleep(per_char, active=False)
        # 关键：等 Quick Open 过滤收敛，否则 Enter 可能打开半匹配的文件
        typer._sleep(self.open_settle_s, active=False)
        ex._tap_special("enter")
        typer._sleep(self.open_settle_s, active=False)
        typer.logger.log("FILE", "located_keyboard", target.path, 0)

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
