import re


class Buffer:
    def __init__(self, text=""):
        self._text = text
        self.cursor = len(text)
        # _line_starts 缓存：text 的每个改动方都重建字符串对象，
        # 因此用对象身份作版本号即可精确失效（len 比较作为额外保险）。
        self._ls_text = None
        self._ls_len = -1
        self._ls_cache = None

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value

    def type_char(self, c):
        self.text = self.text[: self.cursor] + c + self.text[self.cursor :]
        self.cursor += 1

    def backspace(self):
        if self.cursor > 0:
            self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
            self.cursor -= 1

    def delete_forward(self, n):
        n = min(n, len(self.text) - self.cursor)
        removed = self.text[self.cursor : self.cursor + n]
        self.text = self.text[: self.cursor] + self.text[self.cursor + n :]
        return removed

    def move_left(self, n=1):
        self.cursor = max(0, self.cursor - n)

    def move_right(self, n=1):
        self.cursor = min(len(self.text), self.cursor + n)

    def to_line_start(self):
        self.cursor = self.line_start(self.current_line())

    def to_doc_end(self):
        self.cursor = len(self.text)

    def _line_starts(self):
        # 每次调用都全文本扫描会让逐行导航退化成 O(n^2)（_navigate_to、
        # line_col、line_start、line_end_excl_newline 都走这里），因此缓存并按
        # text 对象身份失效。调用方都是只读，共享同一列表是安全的。
        t = self._text
        n = len(t)
        if self._ls_cache is None or self._ls_text is not t or self._ls_len != n:
            starts = [0]
            idx = t.find("\n")
            while idx != -1:
                starts.append(idx + 1)
                idx = t.find("\n", idx + 1)
            self._ls_cache = starts
            self._ls_text = t
            self._ls_len = n
        return self._ls_cache

    def line_count(self):
        return len(self._line_starts())

    def current_line(self):
        return self.text.count("\n", 0, self.cursor)

    def line_start(self, li):
        return self._line_starts()[li]

    def line_end_excl_newline(self, li):
        starts = self._line_starts()
        start = starts[li]
        if li + 1 < len(starts):
            return starts[li + 1] - 1
        return len(self.text)

    def line_text(self, li):
        return self.text[self.line_start(li) : self.line_end_excl_newline(li)]

    def line_col(self):
        li = self.current_line()
        return li, self.cursor - self.line_start(li)

    def line_col_of(self, pos):
        pos = max(0, min(len(self.text), pos))
        li = self.text.count("\n", 0, pos)
        return li, pos - self.line_start(li)

    def apply_up(self, n=1):
        li, col = self.line_col()
        tl = max(0, li - n)
        start = self.line_start(tl)
        length = self.line_end_excl_newline(tl) - start
        self.cursor = start + min(col, length)

    def apply_down(self, n=1):
        li, col = self.line_col()
        starts = self._line_starts()
        tl = min(li + n, len(starts) - 1)
        start = starts[tl]
        length = self.line_end_excl_newline(tl) - start
        self.cursor = start + min(col, length)

    def complete_line_count(self):
        return self.text.count("\n")

    def words_on_line(self, li):
        line = self.line_text(li)
        base = self.line_start(li)
        out = []
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]{2,}", line):
            out.append((base + m.start(), base + m.end(), m.group()))
        return out

    def seg(self, a, b):
        return self.text[a:b]
