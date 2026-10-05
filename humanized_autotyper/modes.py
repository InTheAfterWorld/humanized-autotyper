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
import os
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