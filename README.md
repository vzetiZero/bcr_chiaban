# ChiaBanBCR Desktop

Electron desktop app for managing 1-8 browser profiles. Each profile can use its own supported casino site and browser provider (app-managed Chrome or OmniLogin).

## Multi-site Dream Gaming workflow

1. Set the profile count and choose a site separately on each row in the **Profiles** tab.
2. Press **Run Tool**. Profiles using FEBET or GK881 enter Dream Gaming through separate site controllers and JSON-RPC services. GK881 closes its optional notice, opens the navigation menu, selects **DG Trực Tuyến**, and waits for the popup lobby.
3. The app waits for the DG lobby, selects a real table ID (`60xxx`), moves every profile to that table, applies the configured bet ladder and group settings, and starts the group coordinator.
4. Other sites currently stay on their configured page until the user enters the DG lobby manually. The app checks those profiles every five seconds and continues the shared table flow when all profiles are ready.

The DG table and bet readers are shared across portal hosts. Each profile keeps its own site session and iframe URL while joining the common DG table.

### GK881 mobile (`https://m.gk881.vip/`, Chrome Android / OmniLogin)

The phone build is a different Angular app, so `gk881.openDG` runs its own four-step flow:

1. **Vào sảnh** — close the mobile overlays ("TÔI BIẾT RỒI", "Đóng", "×"), open the
   `Casino` category (`.category-item`), then tap the **DG Trực Tuyến** card.
2. **Lấy URL iframe sảnh** — walk every frame and prefer the `ddnewpc` document; if
   the lobby lives inside a site iframe, read the frame's real `location.href`.
3. **Thay URL trang** — navigate the profile tab to that URL with
   `Page.navigate` over CDP (never `driver.get`, which makes OmniLogin/Hidemium
   tear the session down). The window then shows only the DG lobby, with no site
   DOM or promo overlays left.
4. **Nạp bàn + đồng bộ** — re-read the Laya table list from the page, pick a table
   (the busiest one by default), then every profile rewrites
   `direct1.html?tableId=<id>` so all of them join the same table.

`gk881.openDG` returns `promoted: true/false` so the UI/activity log shows whether
the iframe URL replaced the page URL. If the site draws Laya directly in its own
body (no separate iframe), steps 2–3 are skipped and the flow falls back to tapping
the table card inside the Laya lobby. The same promotion helper
(`febet.promote_lobby_to_tab`) is used by E3951 and VNWTop.

#### Lớp che, thẻ DG và sảnh Laya trên bản điện thoại

Ba lỗi thật đã đo trực tiếp trên `m.gk881.vip` (Chrome Android qua CDP), kèm cách sửa:

| Hiện tượng | Nguyên nhân thật | Cách sửa |
| --- | --- | --- |
| Bấm thẻ DG không ăn, bị đá sang `/Maintenance` hoặc `/Account/Login` | Trang chồng **2 dialog Angular-CDK** ("TIN TỨC MỚI NHẤT" + "GK88 – THƯỞNG NGHÌN TỶ"); nút đóng là `<span class="close …">X</span>`, không phải `<button>`, nên danh sách selector cũ không bao giờ khớp. Backdrop còn đó thì cú bấm rơi vào backdrop | `_MOBILE_CLOSE_JS` quét `.cdk-overlay-pane` / `[role=dialog]`, nhận cả `span` + `[class*=close]`, trả về `backdrops`/`panes` còn lại; `close_mobile_popups()` lặp tới khi sạch và được gọi lại **trước mỗi lần** bấm thẻ DG và trong lúc chờ sảnh (dialog mở lại sau khi đổi danh mục) |
| Bấm "Casino" nhưng lại mở trang **đại lý** (bắt đăng nhập) | `<li>ĐẠI LÝ</li>` nằm trước thanh danh mục trong DOM và khớp danh sách alias cũ (`…, 'đại lý', …`) | `_MOBILE_CATEGORY_JS` ưu tiên tuyệt đối `.category-item` khớp đúng nhãn, và danh sách loại trừ hẳn `đại lý/nạp tiền/cskh/tài khoản…`; trả về `via` để log biết nhánh nào |
| Sảnh DG đã hiện "Baccarat RB01…RB05" mà tool báo *"chưa tìm thấy node bàn thật"* / *"Chưa thấy frame game DG đang tải"* | Bản `ddnewwap` giữ `tableId`/`gameType`/`onlineNum` **ngay trên node thẻ** và vẽ tên bằng các `Text` con; không có wrapper `tableInfo`, không có `enterMC` (dùng `tableMC`/`roadMC`) | `_DG_LOBBY_JS` đọc id/`onlineNum` trên chính node và lấy nhãn từ text con; `_DG_STATE_JS` nhận `tableMC`/`roadMC` và đếm `tableId` (`table_cards`); mọi chỗ so marker `ddnewpc` đổi thành `ddnew` để bản điện thoại `ddnewwap` cũng được nhận; `_LAYA_ENTER_JS` khớp thẻ theo **thuộc tính `tableId`** thay vì so nhãn với mã số |
| Vào bàn thì tab trắng **404 Not Found** (`ddnewwap/direct1.html`) | `_loader_url` áp loader của bản desktop (`direct1.html`) cho **cả** bản điện thoại; `ddnewwap` không có file đó — đo trực tiếp: trang 404, `typeof Laya === 'undefined'` | `_loader_url` giữ nguyên `index.html` khi URL thuộc `ddnewwap` và chỉ đặt `tableId=<id>`; `direct1.html` chỉ dùng cho `ddnewpc`. Đo lại: `ddnewwap/index.html?tableId=60101` → Laya mount, `in_table=true` |
| Đã ở trong bàn mà `dg.table`/`dg.syncTable` vẫn báo `in_table=false` | `_DG_STATE_JS` chỉ nhận màn hình bàn qua node tên `banker` (chỉ có ở bản desktop). Bản mobile dựng view cược với `betBtn`/`betHandler`, nên `bet_state` bảo đã vào bàn còn `_DG_STATE_JS` thì không | `_DG_STATE_JS` dùng **cùng dấu hiệu** với `_DG_BET_STATE_JS` (`betBtn` + `betHandler`/`betBtnMan`/`baccaratLimit`/`tableInfoMan`); `lobby` chỉ còn `true` khi **chưa** ở trong bàn (`&& !inTable`) |

Khi profile **chưa đăng nhập**, site đá sang `/Account/Login?loginToGame=…`. Trước đây
flow dừng sau 10 s và báo *"Profile chưa đăng nhập GK881…"*, tức là bỏ dở một lượt chạy
mà người dùng sẵn sàng đăng nhập tay. Giờ flow **chờ** thay vì bỏ cuộc:

| Việc | Hành vi |
| --- | --- |
| Phát hiện màn hình đăng nhập | `_login_page_state()` chỉ tính là "tường" khi có `input[type=password]` **hiển thị** hoặc route `/account/login`/`/maintenance`; `/Account/LoginToSupplier?SupplierType=DG` là trang bàn giao DG, **không** phải tường |
| Chờ người dùng | `login_gate()` chạy **trong** vòng poll (không chặn), nên một redirect tự hết (`?loginToGame=…` → `LoginToSupplier`) vẫn được nhận là bình thường. Tường thật phải đứng yên `_LOGIN_GRACE` (8 s) mới báo *"Hãy đăng nhập trong cửa sổ Chrome; tool sẽ chờ tối đa 300 giây"* |
| Không ăn ngân sách | Thời gian chờ người được **cộng lại** vào `deadline`/`poll`, nên các bước sau (thẻ DG, sảnh Laya) vẫn còn đủ thời gian thay vì chết ngay sau khi đăng nhập xong |
| Hết giờ chờ | Sau `_LOGIN_WAIT` (300 s) mới trả lỗi nêu đúng nguyên nhân đăng nhập |

Phiên đăng nhập được **lưu và khôi phục** (`aibcr/adapters/session_store.py`):

| Việc | Hành vi |
| --- | --- |
| Lưu | `gk881.openDG` gọi `session_store.save()` trong `finally` (kể cả khi flow lỗi), chỉ giữ cookie thuộc `gk881` + localStorage, ghi `chrome_profile*/session-gk881.json` — nằm trong `.gitignore`, không bao giờ commit |
| Khôi phục | `session_store.restore()` nạp cookie trước khi chạy; **chỉ điều hướng** khi tab còn trắng (`about:blank`), vì WebDriver từ chối mọi cookie trên origin trắng và `driver.get()` sẽ phá mất sảnh DG đang mở |
| Không lộ bí mật | `describe()` chỉ trả số cookie, tên miền và thời điểm lưu — không có giá trị token/cookie, nên log/UI không thể rò rỉ |

Đo thật (Chrome 157, profile `chrome_profile`): mở → lưu **7 cookie / 8 khoá localStorage**
→ `quit()` Chrome → mở lại → khôi phục `ok=True, cookies=7` → vẫn `signed_in=True`, không
hiện lại form đăng nhập.


> **BẮT BUỘC — push GitHub sau MỖI lần cập nhật hoặc sửa đổi**
>
> Remote: `https://github.com/vzetiZero/bcr_chiaban.git` (nhánh `main`).
> Mọi thay đổi (code, cấu hình mặc định, tài liệu) phải được đẩy lên ngay trong cùng
> lần làm việc, không để tồn đọng. Chạy test trước khi push.
>
> ```
> push_update.bat                          # commit "Update <thời gian>" rồi push
> push_update.bat "mô tả thay đổi"         # commit kèm mô tả
> powershell -ExecutionPolicy Bypass -File .\push_update.ps1 "mô tả"
> ```
>
> Script `push_update.ps1` chạy `git add -A` (tôn trọng `.gitignore`:
> `chrome_profile*`, `aibcr_state*.json`, `drivers`, `__pycache__`…), commit rồi
> `git push origin main`. Không kết thúc công việc khi commit còn cục bộ.

## Cấu trúc

```
ChiaBanBCR/
├─ aibcr/                    backend Python (MVC)
│  ├─ config.py              hằng số chung (nhịp quét, gate đặt chip, CDP…)
│  ├─ adapters/              Chrome/Selenium/CDP: đọc DOM, bấm chuột, đặt chip
│  │  ├─ browser.py          mở/gắn Chrome CDP 9222, đọc bàn, đọc số dư
│  │  ├─ lobby_stream.py     đọc sảnh, quét ô bàn, bấm mở bàn bằng chuột thật
│  │  ├─ reader.js           logic đọc Big Road / bead road trong trang
│  │  ├─ table_bets.py       bấm chip, đọc chip đang đặt
│  │  ├─ human_mouse.py      chuyển động chuột "người thật" qua CDP
│  │  ├─ mouse_chromedriver.py  fallback ChromeDriver
│  │  └─ ghost_mouse.py      con trỏ ảo vẽ trong trang
│  ├─ live/                  bộ đọc WebSocket Petalive + dự đoán + AI
│  │  ├─ cards.py            id lá 1..52 → điểm, đếm bài còn lại
│  │  ├─ decode.py           tách khung `onGetGameResult`
│  │  ├─ reader.py           gắn CDP, phát on_round/on_state
│  │  ├─ predict.py          Monte Carlo + Markov + EV (nguồn số liệu)
│  │  ├─ ai.py               gọi AI local/API, chỉ diễn giải
│  │  └─ session.py          trạng thái một bàn, chạy AI ở thread riêng
│  ├─ models/                logic thuần, không I/O
│  │  ├─ engine.py           trạng thái ván, SIDE_NAME
│  │  ├─ money.py            sổ tiền, định dạng
│  │  ├─ chips.py            mệnh giá chip
│  │  └─ live_sim.py         vòng đời phiên, đối chiếu chip, ghi lãi/lỗ
│  ├─ controllers/
│  │  ├─ baccarat.py         BaccaratController - composition root
│  │  └─ sites/               separate FEBET/GK881 entry controllers
│  ├─ service/
│  │  ├─ engine.py          transport JSON-RPC stdin/stdout
│  │  └─ sites/              separate FEBET/GK881 JSON-RPC routes
├─ ui/                       Electron
│  ├─ main.js                spawn engine, IPC, cửa sổ
│  ├─ preload.js             contextBridge `window.aibcr`
│  └─ renderer/
│     ├─ index.html          khung màn hình, tab, form
│     ├─ styles.css          token màu dark/light + layout
│     ├─ theme.js            áp `data-theme` trong <head> (không nháy nền)
│     ├─ toast.js            khay thông báo nổi có animation
│     ├─ alarm.js            còi sự cố (Web Audio)
│     └─ app.js              luồng UI: profile, proxy, cược, site, log
├─ tests/                    unittest + node --test
├─ tools/                    script chạy tay (đọc WebSocket, soi CDP, kiểm chọn bàn)
├─ Start.bat                 mở app (tự cài Electron nếu thiếu)
├─ install-toan-bo.bat       cài Python deps + Electron
└─ push_update.bat/.ps1      commit + push lên GitHub
```

Luồng một lệnh: Electron → `preload.js` → `ui/main.js` → `aibcr.service.engine`
→ controller → adapter/model, rồi sự kiện `state`/`log` trả ngược lên giao diện.

Quy trình tổng quát người dùng đi qua: **Profiles** (chọn P1–P8, gán site/proxy) →
**Chạy Tool** (mở Chrome, vào sảnh DG, đồng bộ một bàn) → **Cược** (dãy cược + vận hành
nhóm) → **Log** (theo dõi, còi sự cố). Tab **Proxy** và **Cấu hình** là phần chuẩn bị.

## Giao diện

- **Dark / Light**: nút ở titlebar; lựa chọn lưu trong `localStorage['aibcr.theme']`
  và được `ui/renderer/theme.js` áp ngay trong `<head>` nên không nháy nền khi mở app.
- **Toast**: `ui/renderer/toast.js` dựng khay `#toast-stack` với 4 loại
  `success / error / warning / info`, tự xếp chồng tối đa 4 cái, có thanh đếm giờ,
  rê chuột để tạm dừng, bấm × để đóng và chống lặp trong 1,2 giây.
  `showNotice()` trong `app.js` vẫn ghi vào `#notice` và đẩy thêm toast tương ứng.
- Mọi màu đi qua biến CSS trong `:root` / `:root[data-theme="light"]`.

### Tab Profiles chia 3 tab con

Tab **Profiles** có ba tab con nằm ngang, chuyển trang tại chỗ (không dồn hết vào
một trang dài):

| Tab con | Nội dung |
| --- | --- |
| **Profile Chrome** | 8 slot P1–P8, chọn site/khung cửa sổ, `Chọn tất cả` / `Bỏ chọn` / `Mở đã chọn` / `Đóng tất cả Chrome` |
| **OmniLogin** | API `127.0.0.1:35353`, tìm profile, `Gán lần lượt`, `Mở tất cả`, `Đóng tất cả`, `Bỏ gán`, mỗi dòng có nút Mở/Đóng |
| **Hidemium** | API `127.0.0.1:5555` (v2), UUID profile, cùng bộ thao tác như OmniLogin |

- Badge trên mỗi tab cho biết số profile đang dùng (Chrome: số slot đang chọn).
- Chọn **Nguồn profile** ở tab *Chạy Tool* sẽ tự nhảy sang tab con tương ứng, và
  ngược lại chuyển tab con sẽ đổi luôn nguồn chạy.
- Tab con đang xem lưu trong `localStorage['aibcr.profileSubtab']`.
- Mở/đóng ở tab provider dùng chung IPC `profile:open` / `profile:close`, nên cửa sổ
  mở ra chính là profile của OmniLogin/Hidemium. `Mở tất cả` chạy tuần tự để không
  nghẽn cổng CDP; đóng xong trạng thái được đồng bộ về cả tab Chrome.

### Sắp xếp site trong tab Cấu hình

Mỗi dòng site có nút **↑ Đầu** / **▲** / **▼** để đổi thứ tự. Thứ tự này là thật,
không chỉ là hiển thị:

- Lưu vào `sites-config.json` (`ui/main.js` → IPC `sites:reorder`, tính toán thuần
  trong `ui/site_order.js`), nên mở lại app vẫn giữ nguyên.
- Là thứ tự `<option>` trong dropdown chọn site của từng Profile, đồng bộ ngay sau
  mỗi lần bấm — không cần tải lại tab.
- Site ở vị trí 1 là lựa chọn mặc định cho profile chưa có lựa chọn riêng.
- Site đã ở đầu/cuối thì nút bị khoá và bấm vào chỉ báo "đã ở đầu/cuối danh sách",
  không ghi file, không báo lỗi.
- Đang gán site riêng cho profile nào thì lựa chọn đó được giữ nguyên khi đổi thứ tự.

## Cài đặt và chạy

```
install-toan-bo.bat      # lần đầu: pip deps + Electron
Start.bat                # mở app
```

Chạy engine bằng tay (CLI):

```
python -m aibcr --game baccarat
python -m aibcr.service.engine --game baccarat
```

Cấu hình Chrome: cổng CDP **9222**, profile `chrome_profile/`, file phiên
`aibcr_state_baccarat.json` (xem `aibcr/service/engine.py::GAMES`).

### Khung cửa sổ và dấu vết điện thoại

Khung mặc định là **Rộng 900 × Cao 1200 × Scale 60%** (dọc), đặt trong tab
**Profiles → Profile Chrome → Kích thước cửa sổ**. Mỗi profile Chrome mang một dấu
vết Android riêng (user-agent, `screen`, WebGL, nhiễu canvas) để site trả giao diện
di động.

Chrome **thu mặt phẳng render** của khung nhìn emulate cho vừa vùng trang của cửa sổ,
nên khung nhìn phải cùng tỉ lệ với vùng trang thì trang mới phủ kín khung. Vì vậy sau
khi mở Chrome, app đo vùng trang thật rồi đặt khung nhìn đúng bằng vùng đó:

| khung nhìn | render thật | phủ khung |
| --- | --- | --- |
| 412 × 915 (tỉ lệ 0.45) | 248 × 549 | 47% × 83% — còn dải trống |
| 880 × 1048 (tỉ lệ 0.84) | 528 × 629 | 100% × 100% |

Số đo bằng `Page.getLayoutMetrics` trên máy (khung 900 × 1200 @ 60%). Nhờ vậy giao
diện điện thoại vẫn giữ nguyên (user-agent Android, `mobile: true`, touch, bottom
nav của site) mà không còn bị thu nhỏ hay chừa khoảng trắng.

Đổi kích thước cửa sổ (kéo tay hoặc sửa cấu hình) sẽ đo lại và khớp lại khung nhìn,
nên không cần mở lại Chrome.

## Backend Baccarat legacy

Các mục dưới đây mô tả controller Baccarat và JSON-RPC cũ. Chúng không xuất hiện trong
giao diện hiện tại.

Tab **Bàn chơi** có một nút thao tác bàn: **VÀO BÀN HỢP LỆ**
(`table.enterValid`). Các nút cũ (Gắn Chrome / Nhận tab sảnh / Quét sảnh / Đọc lại
bàn / Rời bàn / Đóng Chrome) đã bị bỏ để tránh bấm nhầm. Danh sách bàn bên dưới chỉ
để **xem**, không bấm được.

Một lần bấm chạy đúng chuỗi:

1. Gắn Chrome CDP 9222 (chưa mở thì mở Chrome profile rồi yêu cầu đăng nhập + mở
   sảnh, bấm lại nút).
2. Nhận tab sảnh → quét toàn bộ danh sách (cuộn hết, gom mọi ô bàn đã render).
   Nhận cả sảnh EVO (`/frontend/evo/r3`), sảnh Petalive (`/live-games/lobby/bcr`) và
   sảnh **WM/M88** (tab có `iframe_109`/`iframe_101`); với Petalive, cầu được đọc
   trực tiếp từ ô bàn, còn WM đọc lịch sử + lá bài qua WebSocket nhị phân.
3. Mở **ô bàn đầu tiên có mã bàn**. Không chấm điểm/lọc cầu, không bỏ bàn Siêu
   Tốc Độ, không đối chiếu shoe.
4. Bấm đúng ô bàn bằng pointer event thật, chờ URL xác nhận bàn: EVO dùng
   `table_id`, Petalive dùng đường dẫn `/live-games/bcr/<id>`, WM chờ
   `iframe_101` (khung bàn) hiện ra.
5. Xác nhận chỉ cần đọc được cầu trong bàn.
6. **Dừng ở đây**: bàn đã vào nhưng **chưa có lệnh cược**, chưa bấm chip
   (`sim.running = false`, `pending = null`).

### Sảnh WM (M88)

`aibcr/adapters/wm.py` giải mã dữ liệu thật của WM đã đối chiếu với 783 ván:

- `protocol 26` — lịch sử từng bàn: mã kết quả + `resultContent` chứa danh sách lá
  của Banker (`b:`) và Player (`p:`).
- `protocol 25` — ván vừa ngã: `dtCard` khoá `1,3,5` là Player, `2,4,6` là Banker.
- `protocol 24` — từng lá được chia (dùng cho AI live).
- mã kết quả: `code & 3` → 1 = Banker, 2 = Player, 0 = Hoà; bit 3/4 là đôi Banker/
  Player; bit 5/6 là có/không rút lá thứ 3; bit 7/8 là natural.
- id lá 1..80, mỗi chất 20 mã: `rank = (id - 1) % 20 + 1` (14..20 là mã trống).

Bàn đang mở được nhận ra qua class `game101 group<id>` của `#container` trong
`iframe_101`, nên app chỉ đọc đúng bàn đang xem dù sảnh gửi kết quả của mọi bàn trên
cùng một socket. `aibcr/live/wm_reader.py` cấp lá bài cho AI live; `browser.scan()`
cấp cầu cho tool và tự nghe nền (`start_wm_watch`).

Vào bàn là nạp ngay lịch sử `protocol 26` (tối đa 400 ván của shoe) nên AI có xác
suất từ tay đầu thay vì phải chờ vài ván; shoe dự phòng chỉ trừ **40 ván cuối** vì
shoe thật đã chia hết từ lâu. WM phát lại `protocol 26` sau **mỗi** ván, thường
tới **muộn hơn** `protocol 25`; `LiveSession` bỏ ván trùng theo `(gameNo, gameNoRound)`
(nếu thiếu thì theo bộ lá) và ghép lịch sử theo đúng số tay, nên cầu không bị cộng
đôi và “Tay N” luôn bằng tay thật của bàn.

`protocol 25` **không** mang số tay. Bộ đọc gán số tay cho kết quả theo **lịch sử
`protocol 26`** (khớp bộ lá, không thì = ván cuối + 1), không lấy số tay của
`protocol 21`, vì WM phát lại vòng cược vừa xong sau khi ván đã ngã — nhận bản phát
lại đó sẽ làm “Tay N” lùi và lệnh cược bị arm lại cho tay cũ. Đổi shoe (`gameNo`
khác) thì xoá cầu cũ, số tay đếm lại từ đầu.

Khi AI live đang chạy, cầu WebSocket là nguồn chuẩn cho bàn đang theo dõi: lượt CDP
bắt đầu trước khi ván mới về (cầu ngắn hơn) bị bỏ qua thay vì ghi đè, tránh báo
“Cầu đổi nguồn” oan và huỷ lệnh đang chờ chip.

WM đặt chip theo cấu hình (mục “Đặt cược WM” bên dưới); app không tự bấm khi chưa bật
tool.

### Đặt cược WM (`wm_bet.py`, `wm_ws.py`)

Port nguyên tắc an toàn từ dự án LONG-LONG cũ (`bcr/adapters/longlong_table.py`) sang bàn
WM:

1. **Chia tiền theo mệnh giá khay** (`models/chips.decompose`, quy hoạch động): khay WM
   in `10 / 20 / 50 / 100 / 500 / 1k` theo nghìn đồng nên **1 đơn vị sảnh = 1.000đ**
   (chip `10` = 10.000đ). Không chia khít được thì **không đặt** (không bao giờ đặt thiếu).
2. **Đường chính — bấm chuột thật** (`wm_bet.py`): chờ khay chip hết bị lớp kết quả che,
   chọn mệnh giá, bấm chip → bấm ô → **đọc lại số tiền đang treo sau từng chip**; lệch thì
   bấm nút huỷ toàn bộ và báo lỗi; đủ tiền mới bấm xác nhận.
3. **Đường phụ — WebSocket `protocol 22`** (`wm_ws.py`), dùng khi hook đã bắt được socket
   của **iframe bàn**: `{"betSerialNumber", "gameNo", "gameNoRound",
   "betArr": [{"betArea", "addBetMoney"}], "commission": 0, "remark": "1,0"}` với
   `betArea` 1 = Banker, 2 = Player, 3 = Hoà. Server trả `{"protocol": 22, "bOk": true}` là
   lệnh đã vào; `bOk: false` thì tự rơi về bấm chuột.
   Hook được cài bằng `Page.addScriptToEvaluateOnNewDocument`, **không bao giờ tải lại
   tab** (tải lại sẽ đẩy Chrome về sảnh và mất bàn đang đứng). Socket chọn theo `groupID`
   khớp bàn đang mở **và** phải thuộc iframe bàn — socket khung gốc nhận được dữ liệu bàn
   nhưng server từ chối lệnh cược gửi từ đó.
4. **Đọc chip của mình**: `mybet_money` trên từng ô (`read_bets`) trả cùng định dạng
   `table_bets.read` nên `compare_chips` / `table_is_clear` dùng lại được.

Không có bàn nào có mã bàn thì tool tự quét lại (lượt đầu ngay, sau đó mỗi 15 giây)
tới khi hết `ENTER_VALID_TIMEOUT = 240` giây thì báo lỗi. Nút **Dừng tự quét** huỷ
ngay (`table.cancelEnter`).

### Quy tắc một nút (chuẩn hiện tại)

Người dùng chỉ cần mở Chrome đứng ở sảnh, rồi bấm **Chạy tool**:

1. tool tự gắn Chrome/ mở tab, nhận sảnh, quét và mở bàn đầu tiên có mã bàn;
2. The tool tracks results and places only the explicitly selected `P`, `B`, or `T` side at the configured stake.
   WM công bố kết quả xong mới mở cửa cược ván kế (~25–35 giây sau) nên gate chờ
   tối đa `BET_GATE_TIMEOUT = 45` giây trước khi bấm;
3. nếu chưa vào được bàn (Chrome vừa mở, chưa đăng nhập) tool tự thử lại mỗi 15 giây;
4. bấm **Dừng tool** → dừng phiên và tự rời bàn về sảnh.

The wager side is always selected explicitly by the user: `P`, `B`, or `T`. AI and predictions are for analysis only; they never choose a side or trigger a wager. One table unit is 1,000 VND.

## Đọc bàn live + dự đoán

Bộ đọc **WebSocket thật** nằm ở `aibcr/live/` — WM đọc khung nhị phân (protocol 21/24/
25/26), Petalive đọc khung text. Cả hai cùng đổ vào `LiveSession`:

```
python tools/dump_ws_frames.py --seconds 180     # gắn Chrome CDP đang mở, ghi khung
python tools/cdp_capture.py --url "<link bàn>"   # tự mở Chrome CDP riêng rồi ghi
python tools/bcr_live.py --trials 20000          # đọc live + in dự đoán từng ván
python tools/bcr_live.py --ai                    # thêm phần diễn giải AI (cần key)
```

Mã hoá lá bài đã đối chiếu **129/129 ván thật**:
`rank = (id-1)//4 + 1`, điểm = rank nếu ≤ 9, còn lại 0 (10/J/Q/K). Dự đoán chạy local
20k ván Monte Carlo ≈ 0,15 giây, đủ nhanh cho cửa sổ cược ~25 giây.

**Số liệu là của `predict.py`**: xác suất P/B/T, EV, sai số, shoe còn lại, cửa tốt
nhất (`best_side`), cửa có **xác suất cao nhất** (`top_side`) và cờ `playable`.
`playable = false` khi EV tốt nhất không vượt `2 × sai số Monte Carlo` — chỉ là nhãn
`playable = false` marks a prediction without sufficient edge; it does not alter the user selected side.

**Dạng cầu** (`pattern_stats`): đếm số tay mỗi cửa, độ dài chuỗi đang chạy, và tỉ lệ
cửa kế tiếp của những lần trước có **cùng cửa + cùng độ dài chuỗi** (cần ≥ 8 mẫu mới
dùng). Tín hiệu này **chỉ để hiển thị/mô tả**, không trộn vào xác suất: lịch sử ngắn
không chứng minh được cầu bệt hay 1-1 sẽ lặp lại, nên 1-1 không tạo lợi thế toán học.
Xác suất P/B/T chỉ đến từ bộ bài còn lại (Monte Carlo) + Markov phụ trợ 15%.


## AI live qua backend RPC

Luồng live có thể được điều khiển bằng backend RPC hoặc script:

1. Chọn nguồn: `off` · `local` (Ollama/llama.cpp, **không cần key**) · `api`
   (OpenAI-compatible, cần key). Endpoint/model mặc định:
   `https://api.vilao.ai/v1/chat/completions` và `chib/deepseek-v4.1-flash`.
2. Bấm **Lưu cấu hình AI**, rồi **Bật AI live**. Engine gắn CDP 9222, đọc WebSocket
   bàn Petalive, cập nhật shoe và gọi AI mỗi N ván (mặc định 5) trong **thread riêng**
   — không chặn vòng quét/đặt chip.
3. Panel hiện: xác suất P/B/T, EV tốt nhất ± sai số, % shoe đã chia, verdict
   (`BỎ TAY` / `Cân nhắc` / `Đánh`), mức tin cậy, rủi ro và giải thích. Nút
   **Phân tích ngay** gọi AI ngay cho ván kế.

Card **Bàn đang theo dõi** cập nhật theo từng ván WebSocket (không chờ lượt quét):

- **Tay hiện tại**: số tay lấy từ `gameNoRound` của bàn WM (Petalive đếm theo lịch
  sử) nên không còn đứng ở tay cũ; lịch sử cũ được nạp khi vào bàn nên xác suất có
  ngay từ tay đầu, và ván phát lại không bị cộng đôi;
- **Big Road**: sơ đồ cột 6 hàng đúng quy ước (lặp cửa xuống dòng, đổi cửa mở cột,
  đủ 6 hàng thì đi sang phải), dựng từ `road.big_road()`;
- **Dạng cầu**: dãy chuỗi gần nhất + câu `pattern_note` (số tay mỗi cửa, chuỗi tương
  tự trong lịch sử, cửa có xác suất cao nhất).

**Key AI chỉ có 2 nguồn, không bao giờ nằm trong repo:**

- Biến môi trường `BCR_AI_KEY` (đặt trước khi chạy `Start.bat`), ví dụ PowerShell:

  ```
  $env:BCR_AI_KEY = "<key của bạn>"
  .\Start.bat
  ```

- Ô **API key tuỳ biến** trong tab AI: engine nhận qua `ai.key.set` và giữ **trong
  RAM của tiến trình**. Ô nhập bị xoá ngay sau khi bấm Lưu; key không vào `config`,
  file state, log, snapshot hay JSON-RPC trả về. Bấm **Xoá key** để quay về env.

Các biến tuỳ chọn khác: `BCR_AI_MODE`, `BCR_AI_MODEL`, `BCR_AI_URL`, `BCR_AI_TIMEOUT`.

Nếu từng dán key vào code/chat/bug report thì coi như key đã lộ: **xoay key đó** ở
nhà cung cấp. Không dán giá trị key vào README, test, log hay issue.

**AI does not control wagering**: predictions and AI commentary remain in the analysis view only.

## Backend wagering

The current interface has no wager controls or money/statistics display. Legacy backend
methods accept only explicit `P`, `B`, or `T` selections; predictions cannot choose a wager.

## Quản lý profile trên giao diện

Trong trang quản lý, chọn các profile cần chạy (P1–P8), chọn website cho từng profile rồi
bấm **Chạy Tool**. Các cửa sổ Chrome mở cùng URL và được xếp theo lưới. Chọn **Đóng
profiles** để đóng các cửa sổ trong nhóm đang chạy. Đăng nhập từng profile lần đầu ngay
trong cửa sổ Chrome; phiên đăng nhập được Chrome lưu riêng theo profile.

## Lệnh JSON-RPC

```
ping, state,
chrome.open|attach|close|window|status,
lobby.enter|sweep|back,
tables, table.enterValid|cancelEnter|open|select|leave,
tool.start|stop, scan, chips.read,
live.start|stop|state|analyze, ai.key.set,
bet.config|bet.place,  # explicit P/B/T selection only
config.get|set, session.new|reset|recover, log.clear, export
```

UI chỉ gọi `table.enterValid` cho thao tác vào bàn; `table.open`/`table.select` giữ
lại cho script.

## Kiểm thử

```
python -m unittest discover -s tests -t . -q      # toàn bộ test Python
python -m unittest tests.test_engine -v           # engine JSON-RPC + vào bàn + lệnh cược
python -m unittest tests.test_enter_valid_flow -v # harness pipeline chọn bàn (Chrome giả)
python -m unittest tests.test_live_ai -v          # AI, key RAM, bet.place, chặn override
python -m unittest tests.test_lobby_promote -v    # tách iframe sảnh DG ra URL trang (GK881 mobile)
python -m unittest tests.test_gk881_mobile_flow -v # lớp che CDK, thẻ DG, sảnh Laya bản điện thoại
python -m unittest tests.test_session_store -v    # lưu/khôi phục phiên đăng nhập (cookie + localStorage)
python -m unittest tests.test_architecture -v     # ranh giới tầng MVC, không LONG-LONG
node tests/test_reader.cjs                        # test logic đọc bàn (node --test)
node tests/test_profile_subtabs.cjs               # tab Profiles: Chrome / OmniLogin / Hidemium
node tests/test_toast_theme.cjs                   # toast + dark/light theme
```

Kiểm tra thực tế ở mức chọn bàn (Chrome đang mở sảnh, CDP 9222):

```
python tools/kiem_tra_chon_ban.py                  # đọc sảnh, in danh sách bàn
python tools/kiem_tra_chon_ban.py --vao-ban        # bấm ô bàn đầu tiên có mã + chờ đọc
                                                    # được cầu, KHÔNG đặt cược
```

## Ghi chú

- **Push GitHub bắt buộc sau mỗi lần cập nhật/sửa đổi** —
  `https://github.com/vzetiZero/AI_BCR.git`, nhánh `main`. Chạy test trước khi push;
  nếu push lỗi (mạng, xác thực) thì sửa và push lại.
- **Đóng Chrome bằng tay**: app dò cổng CDP (mỗi 2 giây, cache 3 giây) nên phát hiện
  ngay, tạm dừng phiên và xoá danh sách bàn cũ. Bấm **VÀO BÀN HỢP LỆ** để vào lại —
  không cần khởi động lại app.
- Không có LONG-LONG: `aibcr/__init__.py`, `service/engine.py::GAMES` và
  `tests/test_architecture.py` đều chặn ký hiệu LONG-LONG quay lại.
