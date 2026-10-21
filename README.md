# Humanized Autotyper

模拟真人打字节奏的自动输入器：对数正态延迟、突发快打、疲劳漂移、内联错字与
自我纠正、回删爆发、回到前文原位重写、整段重打、长暂停与恢复仪式。

## 安装

```bash
py -m pip install -e .        # 可编辑安装（改代码立刻生效，开发用这个）
py -m pip install .           # 普通安装（拷进 site-packages，改源码不再生效）
```

安装后有三条命令：

| 命令 | 作用 |
|---|---|
| `autotyper` | 命令行输入器（默认 dry-run，加 `--live` 才真打字） |
| `autotyper-gui` | Tk 图形界面 |
| `autotyper-report` | 审计 CSV 事件日志（观测频率 vs 配置概率） |

不想让脚本进 PATH，也可以用模块方式（三者等价）：

```bash
py -m humanized_autotyper              # == autotyper
py -m humanized_autotyper.gui          # == autotyper-gui
py -m humanized_autotyper.report out.csv
```

- 运行时依赖只有 `pynput`（`pip install` 会自动装），它只在**真实输入**时才被
  import；dry-run、自检、日志审计都不需要它。
- **用户数据都在「当前工作目录」**：`source.txt`（GUI 内容页读取/保存）、
  `gui_settings.json`（滑块记忆）、`autotyper_log.csv`（默认日志路径）。
  `autotyper` 不带 `--file` 时先找 `./source.txt`，找不到才用内置演示代码。
- 图形界面需要 Python 自带 tkinter（Windows/macOS 官方安装包默认自带；
  部分 Linux 发行版要额外装 `python3-tk`）。

## 图形界面（推荐入门方式）

```bash
autotyper-gui          # 或 py -m humanized_autotyper.gui
```

四个标签页：

| 页 | 功能 |
|---|---|
| 📝 内容 | 直接编辑要输入的文字（保存到 source.txt），或从文件导入 |
| ⌨️ 节奏与错误 | 滑块调整：基础敲键间隔 / 节奏抖动 / 突发快打 / 错字率 / 连错窗口 / 疲劳 |
| ⏸️ 停顿与删改 | 滑块调整：回删爆发 / 短停顿 / 长暂停(可开关) / **长程模式**(可开关) / 跳回重写 / 整段重打 / **文件间交替打字**(可开关) |
| ▶️ 运行 | **模式**、预设人设、目标窗口标题、倒计时 |

### 模式（GUI）

「运行」页顶部选模式：

| 模式 | 内容来源 | 结束校验 |
|---|---|---|
| 单文件（任意编辑器） | 「内容」页 | 内存缓冲区与文本一致 |
| VSCode（目录多文件） | 磁盘文件（填起始文件夹 + 扩展名） | 逐文件存盘后回读磁盘比对 |

选 VSCode 模式时「内容」页会自动隐藏（内容来自磁盘），并展开**起始文件夹 /
扩展名 / 最多处理文件数**三个输入框。

- **预检**：点「开始真实输入」时先检查文件夹与 VSCode 设置，不通过会弹框，
  并附上可直接复制的 `settings.json` 片段。
- **逐文件结果**：结束后日志区列出每个文件的 `[OK] / [FAIL] / [SKIP]`，
  **失败项排在最前**；状态栏点名失败数量。
- **进度条**：VSCode 模式按「已完成文件数」推进——多文件下单文件内的字符
  进度没有意义。

「运行」页还有 **⏸ 暂停 / ▶ 继续**：「目标窗口标题」填了（只支持 Windows）之后，
前台窗口一旦切走就会**自动暂停**，切回来自动继续；也可以随时手动暂停。
状态栏实时显示当前状态与 ETA（例如「长暂停中，剩 12 分钟」/
「文件 3/10：src/a.py」）。

使用流程：**①** 「内容」页写好文字 → **②** 「运行」页设好倒计时秒数与速度
→ **③** 点「开始真实输入」→ **④** 趁倒计时把光标点进目标窗口。滑块参数会自动
记忆（gui_settings.json）。命令行高级用法见下。

> GUI 只有真实输入（没有演练模式）。想先无副作用地空跑一遍验证文本模型，用
> CLI 的默认 dry-run：`autotyper --file 你的文件`（不传 `--live`）。

## 预设人设（GUI 与 CLI 共用）

三个内置人设定义在 `presets.py`，两端行为完全一致：

| 预设 | 特点 |
|---|---|
| 标准 | config 默认参数 |
| 高效型程序员 | 中位间隔~80ms、错字率0.5%、节奏稳 |
| 手生普通人 | 中位间隔~180ms、错字率2.5%、忽快忽慢易连错 |

- CLI：`autotyper --preset 手生普通人 --live --window Notepad`
  （`--preset list` 查看全部；预设只覆盖行为参数，`--speed`/窗口等不受影响）
- GUI：「运行」页下拉框选择即自动换算到滑块

### 新增自定义预设

在 `presets.py` 的 `PRESETS` 里加一项即可，两个界面自动出现：

```python
PRESETS["夜班摸鱼"] = {
    "delay_mu": 0.25,        # Config 真实单位：秒 / 概率小数
    "p_typo": 0.02,
    ...
}
```

## 文件结构

```
pyproject.toml     # 打包配置：元数据、依赖、console scripts
README.md
source.txt         # 默认输入内容（也可用 --file 指定其他文件）
humanized_autotyper/       # 包本体
├── __init__.py    # 版本号（pyproject 从这里动态取）
├── __main__.py    # python -m humanized_autotyper
├── config.py      # 全部可调参数（概率、分布参数）
├── presets.py     # 预设人设（GUI 与 CLI 共用）
├── keymap.py      # Shift 符号表 + 邻键表 + 控制字符预检
├── buffer.py      # 虚拟文本缓冲区（唯一真相源，禁止读屏）
├── delays.py      # 延迟采样器（lognormal + 修正因子 + burst/疲劳/预热）
├── typos.py       # 错误生成器（adjacent/double/transposition/random）
├── executor.py    # pynput 键盘层 + dry-run + F10 终止 + CSV 日志
├── machine.py     # 状态机（TYPING/BACKSPACE_BURST/PAUSE_SHORT/
│                  #          PAUSE_LONG/EDIT_PREVIOUS/REWRITE_CHUNK）
├── main.py        # CLI 入口（autotyper）：倒计时、窗口校验、调度循环
├── gui.py         # 图形界面（autotyper-gui）
├── report.py      # 事件日志审计：按运行分段 + 用该次真实 config 做 obs vs cfg
├── modes.py       # 模式抽象：单文件 / VSCode（枚举、preflight、回读校验）
├── sanity_check.py # 全链路 dry-run 自检 + 单元验证
└── validate.py    # 多种子批量验证 + kill 开关路径测试
```

包内模块之间用相对导入（`from .config import Config`），因此要整体安装后使用；
单独 `py humanized_autotyper/main.py` 这样直接跑文件是不行的，用命令或 `-m`。

## 快速开始

```bash
autotyper --preset list                    # 看预设

# dry-run 冒烟（无副作用，导出事件日志）
autotyper --file mysource.py --seed 1 --log out.csv

# 审计实际频率是否命中配置概率
autotyper-report out.csv

# 实机输入（见下方安全清单！）
autotyper --live --window Notepad --file mysource.py

# 三条自检入口
py -m humanized_autotyper.sanity_check     # 应输出 ALL SANITY CHECKS PASSED
py -m humanized_autotyper.validate         # 批量种子验证 + kill 开关测试
autotyper-gui --selftest                   # 无界面 GUI 自检
```

`autotyper` 参数：

| 参数 | 说明 |
|---|---|
| `--file` | 要输入的源文本（UTF-8）。缺省时读当前目录 `source.txt`，都没有才用内置演示代码 |
| `--live` | 发送真实击键（默认 dry-run） |
| `--speed X` | 整体速度倍率：>1 加速 / <1 减速（只缩放墙钟时间，不改变人类节奏形状） |
| `--seed` | 固定随机种子（复现行为） |
| `--window "标题子串"` | 前台窗口校验，不匹配则拒绝启动（强烈建议加） |
| `--log FILE` | CSV 事件日志路径（默认 `autotyper_log.csv`，**追加**写） |
| `--fresh` | 启动时清空日志文件，而不是追加进去 |
| `--verbose` | 逐事件打印到控制台 |
| `--long-horizon` | 长程模式：工作 60–120 分钟后休息 5–30 分钟（替代 Pareto 长暂停） |
| `--mode NAME` | 打字模式：`notepad`（默认，单文件）/ `vscode`（目录多文件）。`--mode list` 看全部 |
| `--src-dir DIR` | vscode 模式：要处理的文件目录 |
| `--ext LIST` | vscode 模式：逗号分隔的扩展名白名单 |
| `--max-files N` | vscode 模式：只处理前 N 个文件（0 = 全部） |

## 模式（modes）

`AutoTyper` 的主循环不认识"文档"，只消费 `Target` 列表。模式负责回答三件事：
写哪些内容（`iter_targets`）、怎么定位到编辑器（`before_type`）、
写完怎么确认（`after_type` + `verify_trustworthy`）。

| 模式 | 适用 | 校验方式 |
|---|---|---|
| `notepad` | 任意编辑器 / 记事本，单份文本 | 内存缓冲区自比（`final_matches_source`） |
| `vscode` | VSCode，目录下多个文件 | **存盘后回读磁盘逐字符比对** |

### VSCode 模式

```bash
# 1) 先看需要改哪些配置（dry-run 最稳）
autotyper --mode vscode --src-dir ./src --ext .py --dry-run

# 2) 确认 VSCode 已按提示关掉自动行为，再实机跑
autotyper --mode vscode --src-dir ./src --ext .py --live --window "Visual Studio Code"
```

**启动前必须先满足**（preflight 会逐项检查，不满足直接拒绝启动）：

```jsonc
{
  "editor.autoIndent": "none",          // 否则自动缩进，缓冲区与文档错位
  "editor.autoClosingBrackets": "never", // 否则自动补括号
  "editor.autoClosingQuotes": "never",
  "editor.autoSurround": "never",
  "editor.quickSuggestions": false,      // 否则建议框会吃掉 Enter
  "editor.acceptSuggestionOnEnter": "off",
  "editor.formatOnSave": false,          // 否则存盘重排，回读比对必不符
  "editor.formatOnType": false,
  "editor.detectIndentation": false      // 否则按内容猜 tab/space
}
```

不满足时命令会打印可直接复制的配置片段。

> ⚠️ **与单文件模式的根本差异**：VSCode 会自动改写输入，且每个文件都会重置
> 缓冲区，所以**内存缓冲区不再等于文档**。因此该模式下 `final_matches_source`
> 会报 `None`，正确性只认 `per_file` 里逐文件回读磁盘的结果。
> **F10 中断可能留下半截文件**，请在 git 仓库内运行。

每个文件的动作序列是：`Ctrl+P` → 输入路径 → `Enter` → **`Ctrl+A` + `Delete`
清空文档** → 打字 → `Ctrl+S` 存盘 → 回读磁盘比对。

清空那一步不可省：Quick Open 只是**切换**标签页，文档里还留着上次的内容，
而每个文件的缓冲区是从空的起步的——不清空就会把新文本插到旧内容中间。

#### 文件间交替打字（多文件轮转）

默认（`file_switch_chars = 0`）是**顺序执行**：一个文件彻底打完再切下一个。
在「⏸️ 停顿与删改」页勾选「文件间交替打字」并设定每文件字符数后，调度变成
**轮转推进**：每个文件连续打 N 个字符 → 存盘 → 随机停顿 0.5~2 秒 → 切到下一个
未完成的文件，轮转一圈后回来接着打，直到全部完成——像真人同时在改几个文件。

- 重访某个文件时**不再清空文档**：改为 `Ctrl+P` 打开后直接 `Ctrl+End` 压到
  文末接着打（缓冲区与管道跨轮常驻，两边始终对齐）。
- 切走前只做一次 `Ctrl+S`（`save_only`，不回读校验）；完整校验仍在该文件
  **打完**那一轮由 `after_type` 负责。
- F10 中断同样可能留下多个半截文件（每个都已存盘），仍建议在 git 仓库内运行。
- 该开关只在 VSCode（多文件）模式下生效；单文件模式忽略它。

**逐文件结论是三态的**：

| 标记 | 含义 |
|---|---|
| `[OK  ]` | 存盘后回读磁盘与期望一致 |
| `[FAIL]` | 不一致，`detail` 给出第一处差异的行列 |
| `[SKIP]` | **未校验**——dry-run 下一根键都没发，比对必然通过，是恒真式 |

所以 dry-run 只能验证「枚举、preflight、打字计划」，**不能验证文件是否写对**。
务必先 `--dry-run` 确认无阻塞，再用 `--live` 实机跑。

枚举规则：只收 `--ext` 白名单里的扩展名；跳过 `node_modules/`、`.git/`、
`__pycache__/`、`dist/`、`build/`、`.venv/` 等目录以及所有隐藏文件/目录；
路径统一正斜杠且相对 `--src-dir`（Quick Open 匹配的是工作区相对路径）。

## LIVE 模式安全清单

1. **目标窗口就位**：先打开并聚焦目标窗口（如记事本），再运行命令。
   必须传 `--window`——启动时与每个行尾都会校验前台窗口标题，不匹配就
   **暂停**（切回该窗口即自动继续），取不到窗口标题则拒绝启动。
   GUI 也有这一项（「运行」页的「目标窗口标题」），F10 兜底不变。
2. **倒计时 5 秒**：启动后立即把焦点切到目标窗口。
3. **F10 = 紧急停止**：pynput 监听线程独立置位 kill_flag，分片 sleep 保证
   最长约一个 sleep 片（短停顿 0.25s / 长停顿 2s）内响应。若停止请求正好落在
   "已删除、还没重打"之间，会先把这一小段补完再停，以免文档缺字。
4. **只在无副作用的编辑器里测**：不要对着聊天框/终端/IDE 测试，
   Edit/Rewrite 状态会移动光标、删除重写前文。
5. 首次实测先用小文本、把速度倍率调大（GUI 的「整体速度倍率」/ CLI `--speed 3`）
   跑一遍，确认字符映射（尤其符号）无误后再恢复 1.0 倍速。
6. 结果校验：结束后 `final_matches_source: True` 表示 buffer 与源文本一致；
   若为 False 说明目标应用吞了某个键（如 IME 截走了 shift 组合），查 CSV 里
   出错位置附近的 `detail` 列。

## 输出效果（默认参数下的大致画像）

- 中位敲键间隔 ~110ms（约 9 字/秒），句末/换行后有顿挫，空格带词边界微停顿
- ~5% 的字符处于 0.55× 速度的突发段（每分钟几次，6–20 字符一簇）
- 延迟不是逐字符独立的：同指连击（`e→d`）比双手交替（`a→j`）慢约 1.6 倍，
  所以每个词有自己的节奏形状；实测三种手指关系的延迟比与配置值吻合到 2% 以内
- 打字错误率约 1.4%/字符（`p_typo` 经局部速度耦合放大，实测乘数均值 ≈1.18；
  错后 10 字符内翻倍——手滑连错），
  65% 在下一个字符就被发现退格纠正
- 每 ~4 分钟左右一次 4–35 分钟的长暂停（Pareto 分布，只在词边界打断），
  醒来后有 Left×N → Right×N 的"找回位置"仪式 + 10 字符预热减速
- 行尾小概率跳回前 5–40 行原位重写单词/短句，或选中 1–3 行整段重打
- 约每 50 行一次：用方向键回扫刚写的 5–25 个字符"看一眼"，再回到文末继续
  （只移动光标、不改文本，所以不影响最终一致性）

### 长程模式（模拟长时间工作之间的休息）

默认的长暂停是 Pareto 随机分布，更像"偶尔离开几分钟"；长程模式则把行为
组织成**工作时段 → 休息 → 下一个工作时段**：

```bash
autotyper --long-horizon --file big_source.py --live --window Notepad
```

- 累计**活跃打字时间**达到 60–120 分钟后进入 `REST`，休息 5–30 分钟；
- 休息结束后清零疲劳、做一次"左 N → 右 N"的找回位置仪式，并用 10 个字符
  的预热曲线重新进入状态；
- 长程模式允许在任意字符边界开始休息（长行/压缩代码也能停下来），但不会
  在文末休息——活已经干完了；
- 普通模式的 Pareto 长暂停在长程模式下不再触发，避免"频繁长暂停"和
  "工作时段"两套节奏互相打架；
- 多文件模式下工作时段会跨文件累计，不会因为切文件而清零；
- GUI 在「⏸ 停顿与删改」页勾选「长程模式」即可，CLI 用 `--long-horizon`；
- 时长在 `config.py` 里按秒配置：`work_session_range=(3600, 7200)`、
  `break_range=(300, 1800)`，都是 human-scale 秒。默认是“工作 1–2 小时 →
  休息 5–30 分钟”；如果想让休息本身达到 1–2 小时，把 `break_range` 改成
  `(3600, 7200)` 即可，工作时段也按需调整；
- **源文本要足够长**：阈值按 human-scale 活跃时间算，`--speed` 只压缩墙钟，
  不会让 1–2 小时的工作时段变成几分钟。想快速验证可临时把两个范围调小，
  或跑自检里的 `test_long_horizon_dry_run`。

> 长程模式可以与单文件/VSCode 模式组合使用；它改变的是"什么时候休息"，
> 不改变"往哪里打字"。

## 光标移动策略（纯方向键）

所有导航/选区**只使用 ↑ ↓ ← → 四个方向键**（加 Shift 做选区），不使用
Home / End / Ctrl 组合，也不用鼠标和剪贴板：

- 跨行移动：先 `Up/Down × 行数差`（列粘滞由 buffer 镜像推算），再
  `Right/Left` 校正列差
- 同行移动：直接 `Right/Left × delta`
- 选区：`Shift+Down`（整行）/ `Shift+Right`（行内），纯方向键组合

## 调参指南（config.py）

### 改"打得有多像人"

| 旋钮 | 默认 | 效果 |
|---|---|---|
| `delay_mu` | 0.11s | 基础节奏中位数（lognormal μ），调慢打字整体放慢 |
| `delay_ln_sigma` | 0.42 | 节奏抖动；加大更像新手，减小更机械 |
| `burst_len_range` / `p_burst_enter` | (5,20) / 0.05 | 突发段长度 / 进入概率 |
| `fatigue_rate` / `fatigue_cap` | 0.005 / 1.25 | 每活跃分钟变慢 0.5%，上限 1.25× |
| `warmup_factor` / `warmup_chars` | 1.6 / 10 | ≥5s 停顿后的预热减速曲线 |

### 改"犯错多少"

| 旋钮 | 默认 | 效果 |
|---|---|---|
| `p_typo` | 0.012 | 每字符错误率 |
| `typo_weights` | adjacent 60%… | 错误类型构成（邻键/双打/换序/随机） |
| `typo_detect_probs` | (.65,.25,.10) | 错后第 0/1/2 个字符发现的比例 |
| `typo_autocorr_window` | 10 | 手滑连错的窗口长度 |

### 改"中间行为"

| 旋钮 | 默认 | 效果 |
|---|---|---|
| `p_backspace_burst` | 0.008 | 回删爆发频率（每次连删 2–12 字符） |
| `p_pause_short` / `p_pause_short_sentence` | .008 / .06 | 短停顿频率（后者用于句末字符之后） |
| `p_edit_previous` / `edit_min_gap_s` | .004 / 90s | 跳回前文重写频率 / 两次最少间隔 |
| `p_rewrite_chunk` | .006 | 整段重打频率（行尾评估） |
| `p_review` / `review_back_range` | .02 / (5,25) | 回读遍数：写完一行后偶尔用方向键回扫一眼刚写的内容（只读不改） |
| `file_switch_chars` / `switch_pause_s` | 0 / (0.5, 2.0) | 文件间交替打字：每文件打多少字符后切下一个 / 切换间的随机停顿（`0` = 关闭，顺序执行） |
| `dyad_same_finger` / `dyad_alt_hand` | 1.35 / 0.85 | 二元节奏：同指连击变慢、双手交替变快（`1.0` 可关闭） |
| `typo_speed_exponent` | 1.2 | 错误率与局部速度耦合，打得越快越容易出错（`0` 可关闭） |
| `long_pause_xmin` / `alpha` / `cap` | 240s / 1.4 / 2100s | 普通模式的长停顿时长分布 |
| `long_horizon` | False | 长程模式开关：用工作时段/休息替代 Pareto 长暂停 |
| `work_session_range` / `break_range` | (3600,7200) / (300,1800) | 长程模式的工作/休息时长范围（秒，human-scale） |

## 工作流（蓝图的调参循环）

```bash
autotyper --file big_source.py --log out.csv --fresh   # dry-run 导出（--fresh 清空旧日志）
autotyper-report out.csv                               # obs vs cfg 对照
# → 调 config.py → 重跑 → 直到各状态观测频率贴近配置值 → 再实机
```

CSV 格式：`ts,run_id,state,event,detail,delay_ms`（csv.writer 正确转义逗号）。
`autotyper-report` 给出 typo/burst/pause 观测率 vs 配置率、逐字符延迟分布；
长程模式的 `REST` 事件会单独显示为 `long-horizon rests`。

### 日志分段（重要）

日志是**追加**写的，所以同一个文件里会累积多次运行。这两批数据的速度可能差
几十倍（`--speed 300` 的冒烟跑 vs `1.0x` 的正常跑），一旦混在一起统计：

- 中位数被拉到两个真实值之间（实测 pooled 67ms，而单次真实值是 115ms）
- CV 从 0.46 涨到 1.00，看起来像"节奏不稳"，其实只是一批快样本混了进来
- 概率对照会拿**默认 `Config()`** 去比，而实际跑的是预设或 GUI 拖出来的参数

所以每次运行都会写一对标记行：`RUN,start`（带完整 config 快照）和
`RUN,end`（带 summary）。`autotyper-report` 据此把文件切分成若干段，**每段
各自对照自己那次运行的 config**：

```bash
autotyper-report out.csv            # 审计文件里所有运行
autotyper-report out.csv --list     # 只列出有哪些运行
autotyper-report out.csv --run 2    # 只审计第 2 次
```

输出里还会标出异常段：`cfg UNKNOWN`（老日志没有快照，退回默认值）、
`no RUN,end`（进程可能被强杀，样本不完整）、`content mismatch`。

实测三段（300x / 8x / 300x）的墙钟中位数是 0.4 / 13.1 / 0.3ms，差 40 倍；
report 会把每段乘回各自的 `speed_multiplier` 给出人尺度中位数
（120 / 105 / 90ms，配置值 ~110ms），三段才对得上。

> **1.0 之前的老日志**没有 `run_id` 列也没有 RUN 行，仍然能读，但会被当作
> 单次运行、config 退回默认值，并在输出里标 `unsegmented` / `cfg UNKNOWN`。
> 这种日志的数字不可信，建议用 `--fresh` 重新导一份。
>
> 向老日志**追加**时不会错位：检测到既有表头缺 `run_id` 就按 5 列写，并打印
> 一行 WARNING 提示用 `--fresh` 或换个 `--log` 路径。（否则新行的 `run_id`
> 会落到 `event` 列，整段数据静默错位。）
