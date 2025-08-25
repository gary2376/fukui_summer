# -*- coding: utf-8 -*-
"""
福井縣防災網站 - 水位現況表完整爬蟲 (確保獲取最新資料版本)

功能:
1. 透過 nw=1 參數確保請求的是伺服器上的最新資料。
2. 爬取所有分頁的水位資料。
3. 處理 Shift_JIS 日文編碼。
4. 清理並合併資料。
5. 將結果儲存為 CSV 檔案。
"""
import requests
import pandas as pd
import time
from datetime import datetime

def scrape_fukui_latest_water_level():
    """
    爬取福井縣防災網站當前發布的最新水位觀測站資料。
    """
    # 基本設定
    base_url = "https://sabo.pref.fukui.lg.jp/bousai/servlet/bousaiweb.servletBousaiTableStatus"
    total_pages = 6  # 根據網頁顯示，總共有 6 頁資料
    all_data_frames = []

    print("開始爬取福井縣『最新』水位資料...")
    print(f"目標網站: {base_url}")
    print("-" * 30)

    # 迴圈遍歷所有頁面
    for page_num in range(1, total_pages + 1):
        print(f"正在抓取第 {page_num} / {total_pages} 頁的最新資料...")

        # 組合請求參數
        params = {
            'sv': '3',
            'dk': '2',      # '2' 代表水位
            'nw': '1',      # ⭐️ 關鍵參數：'1' 代表請求 "Now" (最新) 的資料
            'st': '1',      # '1' 代表警報順排序
            'sb': '1',
            'pg': page_num  # 'pg' 代表頁碼
        }

        try:
            # 發送 GET 請求
            response = requests.get(base_url, params=params, timeout=10)
            response.raise_for_status()

            # 設定正確的日文編碼
            response.encoding = 'shift_jis'

            # 解析表格
            tables_on_page = pd.read_html(response.text, attrs={'class': 'tableStatus'})

            if tables_on_page:
                df = tables_on_page[0]
                df.columns = ['_'.join(map(str, col)).strip() for col in df.columns.values]
                if not df.empty:
                    df = df.iloc[:-1]
                all_data_frames.append(df)
                print(f"第 {page_num} 頁資料解析成功，共 {len(df)} 筆數據。")
            else:
                print(f"警告：在第 {page_num} 頁找不到指定的資料表格。")
            
            time.sleep(1)

        except requests.exceptions.RequestException as e:
            print(f"錯誤：抓取第 {page_num} 頁時網路請求失敗: {e}")
            break
        except Exception as e:
            print(f"錯誤：處理第 {page_num} 頁時發生未知錯誤: {e}")
            break

    print("-" * 30)

    if not all_data_frames:
        print("爬取結束，未能獲取任何資料。")
        return

    print("所有頁面抓取完畢，正在合併資料...")
    try:
        full_df = pd.concat(all_data_frames, ignore_index=True)
        
        # 產生一個包含執行時間的檔案名稱
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = r"/Users/wangweizhi/Desktop/file/Project/Project_Fukui/fukui_summer/dataset/fukui_水位.csv"
        
        full_df.to_csv(output_filename, index=False, encoding='utf-8-sig')

        print("\n🎉 任務完成！🎉")
        print(f"總共合併了 {len(full_df)} 筆觀測站資料。")
        print(f"資料已成功儲存至檔案: {output_filename}")

    except Exception as e:
        print(f"錯誤：合併或儲存資料時發生錯誤: {e}")

# --- 執行主程式 ---
if __name__ == "__main__":
    scrape_fukui_latest_water_level()