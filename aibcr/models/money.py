# -*- coding: utf-8 -*-
"""Định dạng số tiền hiển thị trong log và thông báo đặt chip.

Sổ vốn, ngưỡng chốt lời và thống kê thắng/thua đã bị bỏ khỏi dự án: phạm vi chỉ còn
vòng đặt cược nên chỉ cần một hàm định dạng.
"""


def fmt_money(value):
    """Định dạng kiểu Việt Nam: 1.500.000 (bỏ phần thập phân nếu là số nguyên)."""
    return "{:,.0f}".format(float(value or 0)).replace(",", ".")
