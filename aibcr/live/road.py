# -*- coding: utf-8 -*-
"""Big Road: dựng sơ đồ cầu từ chuỗi kết quả B/P/T.

Big Road chuẩn vẽ theo cột: kết quả lặp lại thì xếp xuống dưới, đổi cửa thì mở cột
mới bên phải. Khi một cột đã đủ 6 hàng mà vẫn còn kết quả lặp, ô tiếp theo đi sang
phải cùng hàng (đuôi rồng) thay vì tràn cột — đây là quy ước của Big Road thật.

Hoà (T) không tạo ô mới: giống bàn thật, mỗi tay hoà là một vạch xanh trên ô của vệt
đang chạy (``ties`` của ô đó tăng lên). Hoà đứng trước tay quyết định đầu tiên được
giữ riêng ở đầu sơ đồ (``leading_ties``).

Chỉ là cách trình bày lại ``history`` đã đọc được; không suy đoán thêm kết quả.
"""

DECISIONS = ("P", "B")
SIDES = ("P", "B", "T")
ROWS = 6
MAX_CELLS = 400


def _clean(history):
    return [ch for ch in str(history or "") if ch in SIDES][-MAX_CELLS:]


def big_road(history, rows=ROWS):
    """Trả ``{"columns": [[{"side","row","ties"}, ...], ...], "cells": n}``.

    ``cells`` chỉ đếm ô quyết định (B/P); ``ties`` của mỗi ô là số tay hoà nằm ngay
    sau ô đó. ``leading_ties`` là số hoà trước tay quyết định đầu tiên.
    """
    rows = max(1, int(rows))
    letters = _clean(history)
    columns = []
    taken = set()
    col = -1
    row = 0
    previous = ""
    leading_ties = 0
    newest = None
    cells = 0
    for side in letters:
        if side not in DECISIONS:
            if newest is None:
                leading_ties += 1
            else:
                newest["ties"] += 1
            continue
        cells += 1
        if side != previous:
            col += 1
            row = 0
        elif row + 1 < rows and (col, row + 1) not in taken:
            row += 1
        else:
            # Cột đã đủ 6 hàng: đi sang phải cùng hàng (đuôi rồng).
            probe = col + 1
            while (probe, row) in taken:
                probe += 1
            col = probe
        taken.add((col, row))
        while len(columns) <= col:
            columns.append([])
        newest = {"side": side, "row": row, "ties": leading_ties}
        columns[col].append(newest)
        previous = side
    return {"columns": columns, "cells": cells, "leading_ties": leading_ties}


def last_streak(history):
    """Độ dài chuỗi quyết định cuối cùng (bỏ qua hoà) và cửa của nó."""
    letters = [ch for ch in _clean(history) if ch in DECISIONS]
    if not letters:
        return {"side": None, "length": 0}
    side = letters[-1]
    length = 1
    for ch in reversed(letters[:-1]):
        if ch != side:
            break
        length += 1
    return {"side": side, "length": length}
