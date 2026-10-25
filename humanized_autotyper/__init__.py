"""Humanized Autotyper —— 模拟真人打字节奏的自动输入器。

对外只暴露版本号；功能通过子模块或命令行入口使用：

    autotyper          # 命令行输入器（默认 dry-run，加 --live 才真打字）
    autotyper-gui      # Tk 图形界面
    autotyper-report   # 审计 CSV 事件日志

也可以 `python -m humanized_autotyper`（等同 `autotyper`）。
"""

__version__ = "1.3.0"
