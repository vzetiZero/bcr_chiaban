# ChiaBanBCR Desktop

Electron desktop app for managing 1-8 browser profiles. Each profile can use its own supported casino site and browser provider (app-managed Chrome or OmniLogin).

## Multi-site Dream Gaming workflow

1. Set the profile count and choose a site separately on each row in the **Profiles** tab.
2. Press **Run Tool**. Profiles using FEBET or GK881 enter Dream Gaming through separate site controllers and JSON-RPC services. GK881 closes its optional notice, opens the navigation menu, selects **DG Trực Tuyến**, and waits for the popup lobby.
3. The app waits for the DG lobby, selects a real table ID (`60xxx`), moves every profile to that table, applies the configured bet ladder and group settings, and starts the group coordinator.
4. Other sites currently stay on their configured page until the user enters the DG lobby manually. The app checks those profiles every five seconds and continues the shared table flow when all profiles are ready.

The DG table and bet readers are shared across portal hosts. Each profile keeps its own site session and iframe URL while joining the common DG table.

### Hai site khác nhau — cùng một bàn (đo thật 24/11/2026)

Chạy profile 1 = `m.gk881.vip`, profile 2 = `e39d5d05qc.e3951.com/m/home`, hai Chrome
riêng (cổng CDP 9222/9223), đăng nhập tay, rồi đọc sảnh bằng CDP:

| Số đo | GK881 | E3951 |
| --- | --- | --- |
| Host sảnh | `new-dd-cloudfront.ywjxi.com` | `new-dd-cn.dingdangmail.com` |
| Bản build | `ddnewwap/index.html` | `ddnewwap/index.html` |
| Danh sách bàn | `60101…60105` | `60101…60105` (cùng thứ tự) |
| Bàn đã vào | 60101 `RB01` | 60101 `RB01` |
| Mã ván | `202611240022R1049` | `202611240022R1049` |
| Giới hạn bàn | **10–1000** | **10–1M** |
| Khay chip | `10 … 500000` | `10 … 500000` |

Ba kết luận được khoá bằng `tests/test_shared_table.py`:

- Sảnh của hai site là hai host và **hai bản build khác nhau**, nhưng cùng một bộ bàn
  DG, cùng thứ tự — đúng như quan sát "chung giao diện và thứ tự các bàn trên sảnh".
- Vào cùng bàn thì `round_id` trùng nhau qua nhiều ván liên tiếp; đây là bằng chứng
  nhóm thật sự ở chung một bàn, không chỉ trùng mã trên URL.
- **Giới hạn cược khác nhau trên cùng một bàn** (10–1000 so với 10–1M). Vì vậy mức
  cược chung phải lấy mức **nhỏ nhất** mà mọi sảnh cùng đặt được, và bàn chung phải là
  **giao** danh sách bàn của mọi profile (`ui/table_sync.js`), không lấy danh sách của
  profile dẫn đầu.

#### Sảnh DG là iframe khác tiến trình (OOPIF)

Đo trên cả hai site: sảnh DG không nằm trong tài liệu của trang site mà là CDP target
`type: iframe`, tài liệu thật là `ddnewwap/index.html` — trong khi `<iframe src>` vẫn
ghi `ddnewpc/direct1.html`. Hệ quả và cách xử lý:

| Việc | Đường chạy |
| --- | --- |
| Tìm sảnh | `/json/list` của cổng CDP, lọc target `ddnew*` (`dg_pages.find_game_target`) |
| Đọc sảnh/bàn | eval thẳng trên websocket của target đó (`Runtime.evaluate`) |
| Đưa sảnh lên tab | `Page.navigate` gửi trên websocket **của tab**, không phải của browser |
| Đổi bàn | `_loader_url` giữ `ddnewwap/index.html` và đặt `?tableId=`; `direct1.html` chỉ cho `ddnewpc` |
| Xác nhận đã vào bàn | đọc `view.tableId` của màn hình cược, **không** dựa vào URL |

`Page.navigate` gửi qua websocket cấp browser trả `{}` và trang vẫn nguyên `/m/home` —
đây là lỗi thật đã gặp, nên `febet.navigate_top` và các probe đều gửi trên websocket tab.

#### Công cụ đo hai site cùng lúc

Các script dưới đây chỉ dùng CDP thuần (không Selenium, nên không làm tắt Chrome của
người dùng). Chúng không in token: chỉ host, path và tên tham số.

```
python tools/launch_profile_chrome.py "https://m.gk881.vip/" --profile 1 --port 9222
python tools/launch_profile_chrome.py "https://<host>.e3951.com/m/home" --profile 2 --port 9223
python tools/sync_profiles.py --table 60101 --ports 9222 9223   # về sảnh rồi vào chung bàn
python tools/probe_round_compare.py 9222 9223 --rounds 4         # so mã ván hai sảnh
python tools/probe_dg_limits.py --port 9222                      # giới hạn bàn từng sảnh
```

`tools/sync_profiles.py` làm đúng ba bước của app: đưa sảnh từ iframe lên tab, bỏ
`tableId` để về sảnh, thêm `tableId` của bàn chung — rồi in `cùng bàn` / `cùng mã ván`.

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
| Vừa mở Chrome đã bị báo **"Chrome đã đóng"**, dù cửa sổ Chrome vẫn đang mở | `chrome_open` chạy ở thread riêng, còn `_tick` (và UI) poll `browser.connected` mỗi 2 giây. Trong lúc `start()` đang chạy, cổng CDP chưa mở và `window_handles` còn ném lỗi, nên `connected` trả `False`; tệ hơn, cache 3 giây còn giữ `False` từ trước khi Chrome lên, và `connected` dùng cache đó để gọi `mark_closed()` — xoá luôn phiên vừa tạo (`driver = None`), rồi `_on_chrome_lost()` báo Chrome đã đóng | `BrowserSession._launching` bật quanh `_start_driver()` + `fit_viewport()` (tắt trong `finally`) và `connected` trả `True` khi đang khởi động; ngoài cửa sổ đó, `connected` **dò lại tươi** trước khi `mark_closed()`, không dựa vào cache cũ. Đo lại: 2 profile mở đồng thời, không còn lần nào báo "Chrome đã đóng" |
| Profile đúng trang chủ mà vẫn bị bỏ lượt: *"đang ở trang tổng hợp link"* | `isHub` khớp `/link truy cập/i` trên `document.body.innerText`, tức là **bất kỳ** câu nào trên trang — kể cả dòng footer. Đo được: profile 2 đọc đúng `m.gk881.vip/` nhưng DOM chưa dựng thanh danh mục, chuỗi đó nằm ở footer nên `isHub=true` và cả lượt chạy bị huỷ | `isHub` giờ chỉ xét **tiêu đề** (`h1, h2, h3, .title, .page-title`, ngắn < 60 ký tự); và gặp tiêu đề đó thì chỉ **cảnh báo rồi thử tiếp** thay vì `return` lỗi, vì trang có thể đang dựng dở |

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
| Lưu | `gk881.openDG` gọi `session_store.save()` trong `finally` (kể cả khi flow lỗi), ghi `chrome_profile*/session-gk881.json` — nằm trong `.gitignore`, không bao giờ commit |
| Đọc cookie đúng | `driver.get_cookies()` **chỉ trả cookie của tab đang mở**. Sau khi sảnh DG mở, tab đã sang `new-dd-cn…` nên lần lưu cuối lượt ghi ra `cookies: 0` — đo trên đĩa: tệp của profile 1 còn 105 byte trong khi profile 2 có 10 cookie. `_read_cookies()` dùng CDP `Network.getAllCookies` để lấy **mọi** tên miền (đo lại: 0 → **16 cookie**, đủ `.gk881.vip`, `.m.gk881.vip`, `m.gk881.vip`) |
| Không ghi đè phiên tốt | Lượt lưu không thấy cookie nào thì **giữ nguyên** cookie cũ và chỉ bổ sung localStorage, thay vì thay phiên thật bằng bản rỗng |
| Khôi phục | `session_store.restore()` nạp cookie trước khi chạy; **chỉ điều hướng** khi tab còn trắng (`about:blank`), vì WebDriver từ chối mọi cookie trên origin trắng và `driver.get()` sẽ phá mất sảnh DG đang mở |
| Không lộ bí mật | `describe()` chỉ trả số cookie, tên miền và thời điểm lưu — không có giá trị token/cookie, nên log/UI không thể rò rỉ |

Đo thật (Chrome 157, profile `chrome_profile`): mở → lưu **7 cookie / 8 khoá localStorage**
→ `quit()` Chrome → mở lại → khôi phục `ok=True, cookies=7` → vẫn `signed_in=True`, không
hiện lại form đăng nhập.

### 888AE66 (`https://www.888ae66.com/m`) — site thứ ba, sảnh DG chạy trong khung OOPIF

Bản `/m` là app Vue dựng giao diện điện thoại. Đường vào sảnh đã **đo lại trên Chrome
thật** (profile 1, viewport 880×1103) — bản ghi cũ trong README này sai ở 3 điểm và đã
được sửa:

| Bước | Thực tế đo được | Ghi chú |
| --- | --- | --- |
| 1 | Về `/m` (hoặc quay về `/m` nếu tab đang ở trang con không có menu) | tab trắng / trang con đều được đưa về `/m` |
| 2 | Bấm **`SÒNG BÀI`** = `.swiper-slide.nav-anchor.home-quick-item.navigation-PRODUCT` (x≈249, y≈604) | `.nav-item.live` **không tồn tại** trên bản này; adapter vẫn nhận nó cho build khác |
| 3 | `/gamelobby/live` mở **popup khuyến mãi** `.nrc-modal.fade-in` phủ toàn trang | phải **đóng popup trước**, nếu không mọi cú bấm đều rơi vào lớp phủ |
| 4 | Bấm thẻ Dream Gaming = `div.game-item.DG.customized` chứa `img[src*=live-dg]` | ảnh đó có `alt` **rỗng**; quy tắc cũ `img[alt=banner-dg]` khớp **0** node nên luồng đứng ở sảnh |
| 5 | Tab tự chuyển sang `/launchgame`; sảnh DG chạy là **OOPIF** `ddnewwap/index.html` trên `new-dd-cloudfront.ywjxi.com` (Laya stage 750×940) | **không** có "tab ddnew" nào xuất hiện — chờ tab mới là chờ vô hạn |
| 6 | `promote_frame_to_tab` + `navigate_top` URL OOPIF → tab thành tài liệu DG sau ~2 s | WebDriver không vào được frame khác tiến trình |
| 7 | **Captcha** `sliderBtn`/`System` với chữ `"SafetyVerify"` / `"Drag the slider"` | chờ tay, không tự giải (xem dưới) |
| 8 | **Một tab**: đóng các tab site còn lại, giữ tab DG | đúng yêu cầu "chỉ còn duy nhất 1 tab sảnh" |

Hai điểm dễ hỏng nữa, đã đo:

- **Thẻ DG nằm ngoài viewport**: đo được ở `y≈2406` trong khi viewport cao 1103 px. Bấm
  theo toạ độ viewport mà không cuộn thì cú bấm rơi ra ngoài trang. `_LIVE_ROUTE_JS` gọi
  `scrollIntoView({block:'center'})` rồi mới trả hình chữ nhật.
- **Chỉ bấm nút đóng thật**: trang còn một `div.close-button` nằm ngoài màn hình ở (0,0)
  và các chấm icon 12 px. Mỗi nút đóng phải qua `elementFromPoint` tại đúng tâm của nó,
  nếu không sẽ bấm vào rác và rời trang.

```python
from aibcr.adapters import ae888
ae888.open_dg(driver, wait=180, log=print)   # -> {'ok', 'tables', 'tabs'=1, 'in_table'}
```

Mỗi bước đều có dòng log riêng (`Đã bấm SÒNG BÀI`, `Đã đóng popup …`, `Đã chạm thẻ
DreamGaming …`, `Thấy khung DG …`, `Sảnh DG đã chạy trên tab chính …`), và khi hỏng thì
`result["stage"]` nêu **đúng bước** đang dừng (`đóng popup`, `chờ thẻ DreamGaming`,
`chờ sảnh DG tải`, `đọc danh sách bàn`) để UI không còn câu chung "chưa vào sảnh DG".

#### Captcha thanh trượt — tool không bao giờ giải

Dream Gaming có thể chặn sảnh bằng **"Xác minh an toàn" / "Kéo thanh trượt sang phải"**, và
bản Laya hiện tại trên 888AE66 vẽ bằng **tiếng Anh**: `"SafetyVerify"` / `"Drag the slider"`.
Đo trên 888AE66: captcha vẽ bằng **node Laya**, `document.body.innerText` rỗng và không
có `[class*=captcha]` nào — nên chỉ soi DOM sẽ báo "không có captcha" và tool chờ vô ích.

| Hành vi | Chi tiết |
| --- | --- |
| Nhận diện | `febet.captcha_state()` đọc **cả** cây node Laya và DOM; `_CAPTCHA_BLOCK_RE` khớp cả câu Việt lẫn Anh đang chặn (`xác minh an toàn`, `kéo thanh trượt`, `drag the slider`, `safety verify`), còn "Xác minh thành công" / "Verified successfully" là `_CAPTCHA_PASS_RE` nên không báo động mãi sau khi đã vượt |
| Báo động | Log mức `action` → `alarm.js` hú còi (mẫu `'xác minh an toàn'`, `'kéo thanh trượt'`, `'drag the slider'`, `'safetyverify'`) và dòng nhật ký tô màu cảnh báo riêng. Cả hai chỗ chờ của nhóm (`chờ sảnh`, `quét bàn chung`) đều gửi `error: true` nên không bao giờ treo im lặng |
| Báo ngay | `lobby_tables(..., log=…)` kiểm captcha mỗi 2 giây **trong lúc chờ lưới bàn**, không đợi hết hạn: đo được captcha bật lên sau cổng chờ đầu tiên, nếu chỉ đọc ở hạn chót thì người dùng thấy "chưa có bàn" trước khi được báo kéo tay |
| Không giải | Không có `dispatchMouseEvent`/kéo chuột nào trong đường captcha; `wait_for_captcha()` chỉ poll tới khi người dùng kéo tay xong (mặc định 300 giây) rồi chạy tiếp, và **không** bị tính vào hạn chờ của cả lượt |
| Không chạy lại khi đang chờ | Vòng `runDGGroup` **không** thử lại luồng vào sảnh khi profile đang ở trạng thái captcha: mỗi lần chạy lại sẽ nạp lại sảnh và xoá thanh trượt người dùng đang kéo |
| Chờ đúng chỗ | `lobby_tables(..., log=…)` và `sync_table(..., log=…)` nhận `log` để **chờ** captcha; không truyền `log` (nhịp dò `dg.table` 5 giây) thì chỉ đọc một lượt, không treo nhịp nền |

Đo lại toàn bộ luồng trên Chrome thật (profile 1, CDP 9222, 25/11/2026): `/m` → `SÒNG BÀI`
→ đóng 2 popup → thẻ `game-item DG customized` tại (220, 543) → khung `ddnewwap` → tab chính
→ còi captcha ở giây 10 → người dùng kéo tay → `Sảnh DG sẵn sàng; tìm thấy 5 bàn, 1 tab`.

#### Một bản `ddnewpc` có nhiều "view cược" — bài học đo được

Trên 888AE66, `Laya.stage` chứa **5** node cùng thoả `betBtn`:

| Node | tableId | gameNo | Diễn giải |
| --- | --- | --- | --- |
| `stage.0.1.0.0` | 60101 | `202611240024R1050` | **bàn đang chơi** (RB01), có `tableInfoMan` + limit 10–1M |
| `stage.0.2.1.0.4.0` | 94103 | `2611245132517` | view phụ (QC03) |
| `stage.0.2.1.0.4.1` | 60104 | `202611240024R4053` | view phụ (RB04) |

Cách cũ lấy node **đầu tiên** khớp nên đọc ra `table_name = "QD07"` và `round_id` sai
định dạng, làm `groupBettingTick` tưởng hai profile lệch ván dù cùng bàn. `_DG_STATE_JS`
và `_DG_BET_STATE_JS` giờ chọn view theo **điểm đo được**: có `tableInfoMan` (+4), có
`playerInfo.tableId` trùng `gameInfo.tableId` (+4), có `baccaratLimit` thật min>0 (+2).
Đo lại trên Chrome thật: `table_name = "RB01"`, `round_id = "202611240025R1001"`,
`min_k 10 / max_k 1000000`, `table_id 60101` — trùng GK881/E3951.


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
│  ├─ adapters/              Chrome/Selenium/CDP: mở trang, chọn bàn, bấm chip
│  │  ├─ browser.py          mở/gắn Chrome CDP 9222, đọc tab
│  │  ├─ lobby_stream.py     đọc sảnh, quét ô bàn, bấm mở bàn bằng chuột thật
│  │  ├─ febet.py            sảnh/bàn DG (Laya): URL, danh sách bàn, chốt cược
│  │  ├─ dg_pages.py         nhận tab DG + đọc mã bàn từ URL
│  │  ├─ wm_pages.py         nhận tab WM (M88) qua CDP
│  │  ├─ reader.js           logic đọc Big Road / bead road trong trang
│  │  ├─ table_bets.py       bấm chip, đọc chip đang đặt
│  │  ├─ human_mouse.py      chuyển động chuột "người thật" qua CDP
│  │  ├─ mouse_chromedriver.py  fallback ChromeDriver
│  │  └─ ghost_mouse.py      con trỏ ảo vẽ trong trang
│  ├─ models/                logic thuần, không I/O
│  │  ├─ engine.py           trạng thái ván, SIDE_NAME
│  │  ├─ money.py            định dạng tiền
│  │  ├─ chips.py            mệnh giá chip
│  │  ├─ bet_ladder.py       dãy cược cố định + lịch đổi bàn
│  │  └─ live_sim.py         bám bàn, giữ cầu, vòng đời lệnh cược, đối chiếu chip
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
| **Profile Chrome** | 8 slot P1–P8, chọn **site** và khung cửa sổ, `Chọn tất cả` / `Bỏ chọn` / `Mở đã chọn` / `Đóng tất cả Chrome` |
| **OmniLogin** | API `127.0.0.1:35353`, tìm profile, `Gán lần lượt`, `Mở tất cả`, `Đóng tất cả`, `Bỏ gán`, mỗi dòng có nút Mở/Đóng **và ô chọn site riêng** |
| **Hidemium** | API `127.0.0.1:5555` (v2), UUID profile, cùng bộ thao tác như OmniLogin, cũng có ô chọn site riêng |

- **Mỗi slot của OmniLogin/Hidemium có ô chọn site riêng**, giống tab Profile Chrome:
  danh sách đổ từ cùng `profileSites`, lựa chọn lưu chung một chỗ
  (`localStorage['aibcr.profileSites']`), nên profile mở ra đúng site game đã chọn thay
  vì luôn rơi về site đầu danh sách. Đổi site ở tab Chrome thì ô ở tab provider cập nhật
  theo và ngược lại — hai nơi không thể nói hai kiểu.
- Hai `<select>` trong một dòng cùng mang `data-profile`, nên handler phân biệt bằng
  class (`select.provider-site-select` = đổi site, `select[data-profile]` = đổi profile
  đang gán). Thiếu phân biệt này thì đổi site sẽ âm thầm bỏ gán profile.
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

## Phạm vi backend: chỉ đặt cược

Backend giữ đúng vòng đặt cược: mở site → vào sảnh → vào bàn dùng chung → xếp chip →
xác nhận. Toàn bộ phần đọc kết quả, dự đoán, AI và sổ lãi/lỗ đã bị xoá khỏi cả model,
controller và giao diện.

Tab **Bàn chơi** có một nút thao tác bàn: **VÀO BÀN HỢP LỆ** (`table.enterValid`).
Các nút cũ (Gắn Chrome / Nhận tab sảnh / Quét sảnh / Đọc lại bàn / Rời bàn / Đóng
Chrome) đã bị bỏ để tránh bấm nhầm.

Một lần bấm chạy đúng chuỗi:

1. Gắn Chrome CDP (chưa mở thì mở Chrome profile rồi yêu cầu đăng nhập + mở sảnh,
   bấm lại nút).
2. Nhận tab sảnh DG → quét danh sách ô bàn (cuộn hết, gom mọi ô bàn đã render).
3. Mở **ô bàn đầu tiên có mã bàn**. Không chấm điểm/lọc cầu, không đối chiếu shoe.
4. Bấm đúng ô bàn bằng pointer event thật, chờ URL xác nhận `?tableId=`.
5. Xác nhận chỉ cần đọc được cầu trong bàn.
6. **Dừng ở đây**: bàn đã vào nhưng **chưa có lệnh cược**, chưa bấm chip
   (`sim.running = false`, `pending = null`).

### Sảnh DG (Laya) — phạm vi hiện tại

- `aibcr/adapters/febet.py` — URL sảnh/bàn DG, danh sách bàn, đọc pha cược
  (`betState`), xếp chip + xác nhận (`stage_bet`), rời bàn.
- `aibcr/adapters/dg_pages.py` — nhận tab DG đang mở và đọc mã bàn từ `?tableId=`.
- `aibcr/adapters/lobby_stream.py` — quét ô bàn trong sảnh, mở đúng bàn đã chọn,
  quay lại sảnh.
- `aibcr/adapters/wm_bet.py` / `table_bets.py` — đường bấm chip dùng chung.

Đơn vị tiền của DG bằng đơn vị hiển thị (VND2 = 1.000đ), nên `scale` phải là **1**:
mức cược `10` trong cấu hình là 10.000đ trên bàn.

`bets:start-open` (UI) chỉ chạy khi mọi profile đã mở và đứng trong bàn DG; nó từ chối
khi một chip đã được xếp/xác nhận trong ván hiện tại, tránh đặt trùng.

### Quy tắc một nút (chuẩn hiện tại)

Người dùng mở các profile, mỗi profile vào site riêng và đứng trong bàn DG, rồi bấm
**Chạy cược**:

1. tool đọc `betState` của từng profile (`ok`, `in_table`, `table_id`, `round_id`,
   `bet_open`, `confirmed[side]`);
2. chia cửa đối lập: profile lẻ một cửa, profile chẵn cửa còn lại, **cùng một mức**;
3. chờ cửa cược mở rồi xếp chip theo mệnh giá khay; `auto_confirm` bật thì bấm xác
   nhận luôn;
4. đếm vòng bằng **mã ván đổi** (không đọc thắng/thua) rồi đổi bàn theo lịch đã cấu
   hình (`hop_min`, tối đa `hop_max` lượt);
5. bấm **Dừng** → dừng nhóm và rời bàn.

Mức cược **giữ nguyên** mức đã cấu hình: không tiến/lùi bước theo kết quả ván.

### Xếp chip DG — những gì đo được trên bàn 60101

Laya của DG không nhận sự kiện chuột tự phát vào node, nên các đường dưới đây đã đo
bằng Chrome thật và được ghi lại trong `tests/test_dg_stage_bet.py`:

| Việc | Đường **chạy** | Đường **không** chạy |
| --- | --- | --- |
| Chọn mệnh giá | `chipMan.selectChipHandler(chip)` → đổi `playerInfo.selectChip` | `chip.event('click')` |
| Đặt chip vào cửa | `view.betHandler({buttonName:'Player'|'Banker'})` → tăng `betMoneyTmp` | `spot.event('click')` |
| Xác nhận | `view.confirmBet()` → điền `betMoneyTrue` | `confirmBtn.event('click')` |

Đơn vị tiền: nhãn bàn `10-1000`, `baccaratLimit.bpMin/bpMax` = 10/1000, khay chip
`10 … 500000` → **1 đơn vị DG = 1k**, nên `scale = 1` (chia thêm 1000 sẽ khiến bước
tự kiểm tra đồng ý với chính cái sai).

`playerInfo.balance = 0` làm `checkBet` của Laya từ chối **mọi** cú bấm chip (chỉ bật
hộp "NoBalance"). Vì vậy khi số dư đọc được là 0 mà chip không lên, thông báo lỗi nêu
thẳng nghi phạm số dư thay vì đổ lỗi cho mệnh giá chip.

## Backend wagering

Giao diện chỉ có luồng đặt cược theo cấu hình; không có bảng tiền, lịch sử thắng/thua
hay dự đoán. Mọi lệnh cược chỉ nhận lựa chọn `P`, `B`, `T` tường minh.

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
bet.config|bet.place|bet.ladder.configure,  # explicit P/B/T selection only
febet.table|tables|syncTable, dg.table|tables|syncTable,
config.get|set, session.new|reset, log.clear
```

UI chỉ gọi `table.enterValid` cho thao tác vào bàn; `table.open`/`table.select` giữ
lại cho script.

## Kiểm thử

```
python -m unittest discover -s tests -t . -q      # toàn bộ test Python
python -m unittest tests.test_engine -v           # engine JSON-RPC + vào bàn + lệnh cược
python -m unittest tests.test_bet_tick -v         # vòng tự đặt cược, đối chiếu chip
python -m unittest tests.test_dg_stage_bet -v     # hợp đồng xếp chip DG đo trên bàn thật
python -m unittest tests.test_dg_floor_parse -v   # đọc sàn bàn DG, bỏ bộ đếm tiền mỗi cửa
python -m unittest tests.test_enter_valid_flow -v # harness pipeline chọn bàn (Chrome giả)
python -m unittest tests.test_lobby_promote -v    # tách iframe sảnh DG ra URL trang (GK881 mobile)
python -m unittest tests.test_gk881_mobile_flow -v # lớp che CDK, thẻ DG, sảnh Laya bản điện thoại
python -m unittest tests.test_session_store -v    # lưu/khôi phục phiên đăng nhập (cookie + localStorage)
python -m unittest tests.test_ae888_entry -v      # 888AE66: thẻ DG, quy tắc một tab, captcha chờ tay
python -m unittest tests.test_architecture -v     # ranh giới tầng MVC, không LONG-LONG
python tools/check_js_syntax.py                   # biên dịch mọi blob *_JS của adapter (bắt lỗi ngoặc)
node tests/test_reader.cjs                        # test logic đọc bàn + chọn mức cược chung
node tests/test_skip_round.cjs                    # bỏ qua tay lỗi, nhóm vẫn chạy
node tests/test_profile_subtabs.cjs               # tab Profiles: Chrome / OmniLogin / Hidemium
node tests/test_toast_theme.cjs                   # toast + dark/light theme
```

Kiểm tra thực tế ở mức chọn bàn (Chrome đang mở sảnh, cổng CDP 9222):

```
python tools/kiem_tra_chon_ban.py                  # đọc sảnh, in danh sách bàn
python tools/kiem_tra_chon_ban.py --vao-ban        # bấm ô bàn đầu tiên có mã + chờ đọc
                                                    # được cầu, KHÔNG đặt cược
```

Bàn đã mở sẵn mà cổng CDP khác 9222 (ví dụ OmniLogin mở ở 9223) thì đổi
`BR.CDP_PORT` bằng `--port` của script tương ứng, hoặc sửa biến môi trường của tool
đang dùng; adapter không tự đoán cổng.

## Ghi chú

- **Push GitHub bắt buộc sau mỗi lần cập nhật/sửa đổi** —
  `https://github.com/vzetiZero/AI_BCR.git`, nhánh `main`. Chạy test trước khi push;
  nếu push lỗi (mạng, xác thực) thì sửa và push lại.
- **Đóng Chrome bằng tay**: app dò cổng CDP (mỗi 2 giây, cache 3 giây) nên phát hiện
  ngay, tạm dừng phiên và xoá danh sách bàn cũ. Bấm **VÀO BÀN HỢP LỆ** để vào lại —
  không cần khởi động lại app.
- Không có LONG-LONG: `aibcr/__init__.py`, `service/engine.py::GAMES` và
  `tests/test_architecture.py` đều chặn ký hiệu LONG-LONG quay lại.
