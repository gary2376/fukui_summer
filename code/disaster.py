
# @抓地震資訊
import asyncio
import sys
import csv
from pathlib import Path
from urllib.parse import urljoin

# ====== Windows 平台：讓 Playwright Async API 能正常 spawn 子程序 ======
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.async_api import async_playwright

# -----------------------------------------------------------------------------
# 參數設定
# -----------------------------------------------------------------------------
# 1) JMA 地震清單 (中文介面)
JMA_LIST_URL = "https://www.data.jma.go.jp/multi/quake/index.html?lang=cn_zt"

# 2) CWA 全球地震備援頁面 (臺灣即時全球地震)
CWA_FALLBACK_URL = "https://scweb.cwa.gov.tw/zh-tw/earthquake/world/"

# 3) 關鍵字：判斷「震央地名」是否包含「福井」
FUKUI_KEYWORD = "福井"

# 4) Headless 模式
HEADLESS = True

# 5) 輸出檔案路徑
GENERAL_CSV = Path(r"/Users/gary/Documents/project/fukui_summer/dataset/jma_quakes_all.csv")
FUKUI_CSV   = Path(r"/Users/gary/Documents/project/fukui_summer/dataset/jma_quakes_fukui.csv")


async def ensure_csv_files():
    """
    確保 GENERAL_CSV 和 FUKUI_CSV 存在，並且讀取已存在紀錄到集合以做去重檢查。
    回傳：
      existing_general (set of (detection_time, epicenter)),
      existing_fukui   (set of (detection_time, epicenter))
    """
    existing_general = set()
    if GENERAL_CSV.exists():
        with GENERAL_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["地震檢測日期時間"].strip(), row["震央地名"].strip())
                existing_general.add(key)
        print(f">>> GENERAL_CSV 已存在，共 {len(existing_general)} 筆。")
    else:
        # 不存在就建立並寫入表頭
        with GENERAL_CSV.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "地震檢測日期時間",
                "緯度",
                "經度",
                "規模",
                "震源深度",
                "震央地名"
            ])
        print(">>> GENERAL_CSV 不存在，已建立並寫入表頭。")

    existing_fukui = set()
    if FUKUI_CSV.exists():
        with FUKUI_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["地震檢測日期時間"].strip(), row["震央地名"].strip())
                existing_fukui.add(key)
        print(f">>> FUKUI_CSV 已存在，共 {len(existing_fukui)} 筆「福井」資料。")
    else:
        with FUKUI_CSV.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "地震檢測日期時間",
                "緯度",
                "經度",
                "規模",
                "震源深度",
                "震央地名"
            ])
        print(">>> FUKUI_CSV 不存在，已建立並寫入表頭。")

    return existing_general, existing_fukui


async def scrape_from_jma(existing_general, existing_fukui):
    """
    主資料來源：日本氣象廳 (JMA)，擷取地震清單並逐筆進 Detail 抓取六個欄位。
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context()
        page = await context.new_page()

        print(f">>> 前往 JMA 地震清單：{JMA_LIST_URL}")
        await page.goto(JMA_LIST_URL, wait_until="networkidle")

        # 等待清單表格出現
        await page.wait_for_selector("table#quakeindex_table")
        print(">>> 已定位到 JMA 清單表格，開始擷取每一列...")

        rows = await page.query_selector_all("table#quakeindex_table tbody tr")
        print(f">>> JMA 總共抓到 {len(rows)} 列 (含表頭)。")

        if len(rows) <= 1:
            await browser.close()
            raise RuntimeError(">>> JMA 清單表格只有表頭，沒有實際資料列。")

        # 只抓最近十筆（去掉表頭）
        recent_rows = rows[1:11]  # 1:11 代表第2到第11列（共10筆）

        # 開啟 CSV 以便 append
        gen_file = GENERAL_CSV.open("a", encoding="utf-8-sig", newline="")
        fuk_file = FUKUI_CSV.open("a", encoding="utf-8-sig", newline="")
        gen_writer = csv.writer(gen_file)
        fuk_writer = csv.writer(fuk_file)

        for idx, row in enumerate(recent_rows, start=1):
            cells = await row.query_selector_all("td")
            if len(cells) < 2:
                continue

            epicenter_text = (await cells[1].inner_text()).strip()
            is_fukui = (FUKUI_KEYWORD in epicenter_text)

            # 第一欄一定有 <a href="quake_detail.html?eventID=...">
            link_handle = await cells[0].query_selector("a")
            if not link_handle:
                continue
            href = await link_handle.get_attribute("href")
            detail_url = urljoin(page.url, href)

            # 打開 Detail 分頁
            detail_page = await context.new_page()
            await detail_page.goto(detail_url, wait_until="networkidle")

            # 等待 Detail 內地震資訊表格
            await detail_page.wait_for_selector("article.quake_detail table.quakeindex_table")
            detail_rows = await detail_page.query_selector_all(
                "article.quake_detail table.quakeindex_table tbody tr"
            )
            if len(detail_rows) < 2:
                print(f">>> [JMA] 第 {idx} 筆，Detail 資料列不足，跳過。")
                await detail_page.close()
                continue

            data_row = detail_rows[1]
            detail_tds = await data_row.query_selector_all("td")
            if len(detail_tds) < 6:
                print(f">>> [JMA] 第 {idx} 筆，Detail 欄位少於 6，跳過。")
                await detail_page.close()
                continue

            # 擷取六個欄位
            detection_time = (await detail_tds[0].inner_text()).strip()
            latitude       = (await detail_tds[1].inner_text()).strip()
            longitude      = (await detail_tds[2].inner_text()).strip()
            magnitude      = (await detail_tds[3].inner_text()).strip()
            depth          = (await detail_tds[4].inner_text()).strip()
            epicenter      = (await detail_tds[5].inner_text()).strip()

            key = (detection_time, epicenter)

            # (A) 寫入 GENERAL_CSV（若未重複）
            if key not in existing_general:
                gen_writer.writerow([
                    detection_time,
                    latitude,
                    longitude,
                    magnitude,
                    depth,
                    epicenter
                ])
                existing_general.add(key)
                print(f"+++ [JMA→GENERAL]  {key}")
            else:
                print(f"=== [JMA→GENERAL 跳過重複] {key}")

            # (B) 如果是「福井」，再寫入 FUKUI_CSV（若未重複）
            if is_fukui:
                if key not in existing_fukui:
                    fuk_writer.writerow([
                        detection_time,
                        latitude,
                        longitude,
                        magnitude,
                        depth,
                        epicenter
                    ])
                    existing_fukui.add(key)
                    print(f"+++ [JMA→FUKUI]    {key}")
                else:
                    print(f"=== [JMA→FUKUI 跳過重複] {key}")

            await detail_page.close()

        gen_file.close()
        fuk_file.close()
        await browser.close()
        print(">>> JMA 資料擷取完成。")


async def scrape_from_cwa_fallback(existing_general, existing_fukui):
    """
    備援方案：以台灣中央氣象署 (CWA) 的「即時全球地震」頁面，
    找出所有「地震位置」中含 “Japan” 或 “日本” 的列，
    擷取「地震時間、緯度、經度、深度、規模、地震位置」6 個欄位，
    同樣寫入 GENERAL_CSV，如果地震位置中含 “福井” 或 “Fukui”，額外寫入 FUKUI_CSV。
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context()
        page = await context.new_page()

        print(f">>> 前往 CWA 全球地震備援頁：{CWA_FALLBACK_URL}")
        await page.goto(CWA_FALLBACK_URL, wait_until="networkidle")

        # 表格可能在 <table id="Btable worldTable">，或 <div class="tsunamisInfoBg"> 內
        await page.wait_for_selector("table.worldTable, table#Btable")

        # 嘗試以通用 selector 抓到每一列
        rows = await page.query_selector_all("table.worldTable tbody tr")
        if not rows:
            # 若抓不到，就試抓「table#Btable tbody tr」
            rows = await page.query_selector_all("table#Btable tbody tr")

        print(f">>> CWA 備援頁總共找到 {len(rows)} 筆列。")

        if len(rows) == 0:
            await browser.close()
            raise RuntimeError(">>> CWA 表格抓不到任何列。")

        # 打開 CSV 並 append
        gen_file = GENERAL_CSV.open("a", encoding="utf-8-sig", newline="")
        fuk_file = FUKUI_CSV.open("a", encoding="utf-8-sig", newline="")
        gen_writer = csv.writer(gen_file)
        fuk_writer = csv.writer(fuk_file)

        for idx, row in enumerate(rows, start=1):
            cells = await row.query_selector_all("td")
            # 預期至少有 6 個 <td>，順序如下（對應上方截圖）：
            # 0: 地震時間(臺灣時間), 1: 經度, 2: 緯度, 3: 深度(公里), 4: 規模, 5: 地震位置
            if len(cells) < 6:
                continue

            # 擷取欄位文字
            detection_time = (await cells[0].inner_text()).strip()
            longitude      = (await cells[1].inner_text()).strip()
            latitude       = (await cells[2].inner_text()).strip()
            depth          = (await cells[3].inner_text()).strip()
            magnitude      = (await cells[4].inner_text()).strip()
            epicenter      = (await cells[5].inner_text()).strip()

            # 只挑「地震位置」中含 “Japan” 或 “日本” 的列
            if ("Japan" not in epicenter) and ("日本" not in epicenter):
                continue

            key = (detection_time, epicenter)

            # 寫入 GENERAL_CSV（若未重複）
            if key not in existing_general:
                gen_writer.writerow([
                    detection_time,
                    latitude,
                    longitude,
                    magnitude,
                    depth,
                    epicenter
                ])
                existing_general.add(key)
                print(f"+++ [CWA→GENERAL]  {key}")
            else:
                print(f"=== [CWA→GENERAL 跳過重複] {key}")

            # 如果「福井」或 “Fukui”，則寫入 FUKUI_CSV（若未重複）
            if ("福井" in epicenter) or ("Fukui" in epicenter) or ("fukui" in epicenter):
                if key not in existing_fukui:
                    fuk_writer.writerow([
                        detection_time,
                        latitude,
                        longitude,
                        magnitude,
                        depth,
                        epicenter
                    ])
                    existing_fukui.add(key)
                    print(f"+++ [CWA→FUKUI]    {key}")
                else:
                    print(f"=== [CWA→FUKUI 跳過重複] {key}")

        gen_file.close()
        fuk_file.close()
        await browser.close()
        print(">>> CWA 備援方案擷取完成。")


async def main():
    # step 1) 準備 CSV / 讀取已存在資料
    existing_general, existing_fukui = await ensure_csv_files()

    # step 2) 嘗試從 JMA 抓取；若失敗就啟動備援
    try:
        await scrape_from_jma(existing_general, existing_fukui)
    except Exception as e:
        print(f"!!! JMA 擷取過程發生異常：{e}")
        print(">>> 啟動備援方案：從 CWA 全球地震頁面抓取日本地震 ...")
        await scrape_from_cwa_fallback(existing_general, existing_fukui)

    print(">>> 全部任務完成，程式結束。")


if __name__ == "__main__":
    asyncio.run(main())
