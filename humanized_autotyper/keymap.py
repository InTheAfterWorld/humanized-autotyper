SHIFT_SYMBOLS = {
    "~": "`",
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
}

ADJACENT = {
    "q": "wa",
    "w": "qeas",
    "e": "wrsd",
    "r": "etdf",
    "t": "ryfg",
    "y": "tugh",
    "u": "yihj",
    "i": "uojk",
    "o": "ipkl",
    "p": "ol",
    "a": "qwsz",
    "s": "awedxz",
    "d": "serfcx",
    "f": "drtgv",
    "g": "ftyhb",
    "h": "gyujn",
    "j": "huikm",
    "k": "jiolm",
    "l": "kop",
    "z": "asx",
    "x": "zsdc",
    "c": "xdfv",
    "v": "cfgb",
    "b": "vghn",
    "n": "bhjm",
    "m": "njk",
    "1": "2q",
    "2": "13w",
    "3": "24e",
    "4": "35r",
    "5": "46t",
    "6": "57y",
    "7": "68u",
    "8": "79i",
    "9": "80o",
    "0": "9p",
}

# 允许出现的控制字符（换行走 Enter 键，Tab 走 Tab 键）
ALLOWED_CONTROL = ("\n", "\t")

# 标准触键指法归属：(手, 指)。用于二元节奏（同指代价）——真实打字速度
# 主要由相邻两键的手指关系决定，与"哪个键离得近"无关。
FINGER = {}
for _hand, _finger, _keys in (
    ("L", "pinky", "qaz1`"), ("L", "ring", "wsx2"), ("L", "middle", "edc3"),
    ("L", "index", "rfvtgb45"), ("R", "index", "yuhjnm67"),
    ("R", "middle", "ik,8"), ("R", "ring", "ol.9"), ("R", "pinky", "p;/0-"),
):
    for _k in _keys:
        FINGER[_k] = (_hand, _finger)


def dyad_factor(prev, cur, same_finger, alt_hand):
    """相邻两键的节奏因子：同指连击最慢（1.0 → same_finger），双手交替最快。

    返回 None 表示这对字符不参与二元节奏（非 ASCII、或键位不在指法表里），
    调用方应保持因子为 1.0。同手异指的因子是 1.0，无需显式表示。
    """
    if not prev or not cur or prev == cur:
        return None
    a, b = prev.lower(), cur.lower()
    if not (a.isascii() and b.isascii() and a.isalpha() and b.isalpha()):
        return None
    fa, fb = FINGER.get(a), FINGER.get(b)
    if fa is None or fb is None:
        return None
    if fa[0] != fb[0]:
        return alt_hand
    if fa[1] == fb[1]:
        return same_finger
    return 1.0


def unsupported_chars(text):
    """返回无法可靠键入的字符：[(下标, 字符)]。

    除 \n \t 之外的 C0/C1 控制字符（\r \x0b \x0c \x1b \x7f …）在编辑器里
    的行为各不相同（有的被忽略、有的当成换行），会让"虚拟缓冲区 = 文档"
    这一前提失效，因此启动前直接拒绝，而不是让它静默地打字打歪。
    """
    return [(i, ch) for i, ch in enumerate(text)
            if (ord(ch) < 0x20 or ord(ch) == 0x7f) and ch not in ALLOWED_CONTROL]

