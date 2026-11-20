# -*- coding: utf-8 -*-
"""AI_BCR - bot bàn Baccarat theo kiến trúc MVC, giao diện Electron.

Tầng (trên xuống):

    ui/                 View       - Electron (HTML/JS/CSS): chỉ vẽ và gửi lệnh
    aibcr.service         Transport  - JSON-RPC stdin/stdout, một tiến trình Baccarat
    aibcr.controllers     Controller - điều phối Model + Adapter (composition root)
    aibcr.adapters        Adapter    - Chrome/Selenium/CDP: đọc DOM, bấm chuột, đặt chip
    aibcr.models          Model      - luật cầu, lệnh cược, sổ vốn (thuần, không I/O)

Luồng một lệnh: Electron -> preload/IPC -> aibcr.service.engine -> controller
-> adapter/model, rồi sự kiện ``state``/``log`` trả ngược lên giao diện.
"""
