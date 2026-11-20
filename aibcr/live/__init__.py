# -*- coding: utf-8 -*-
"""Đọc bàn live + dự đoán tay kế tiếp cho site Petalive (BCR).

Tách khỏi ``aibcr.adapters`` (vốn chỉ phục vụ Evolution) để không trộn hai giao thức:

    cards.py    giải mã id lá bài -> rank/giá trị, tổng điểm, theo dõi shoe
    decode.py   phân tích khung WebSocket ";game;...;onGetGameResult;0;0;{json}"
    reader.py   gắn CDP, bắt khung live và phát sự kiện
    predict.py  xác suất B/P/T + EV từ bộ bài còn lại (Monte Carlo + Markov)
    ai.py       gọi API AI (tuỳ chọn) để diễn giải kết quả đã tính
"""
