import pandas as pd
import sqlite3
import os

def csv_to_sqlite():
    """將CSV檔案轉換為SQLite資料庫"""
    
    # 檔案路徑
    csv_path = r'E:\python_project\contest\fukui_summer\dataset\output_shelters.csv'
    db_path = r'E:\python_project\contest\fukui_summer\dataset\shelters.db'
    
    print("正在讀取CSV檔案...")
    df = pd.read_csv(csv_path)
    
    # 資料清理
    print("正在清理資料...")
    df.dropna(subset=['latitude', 'longitude'], inplace=True)
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    df.dropna(subset=['latitude', 'longitude'], inplace=True)
    df['evaspot_capacity'] = df['evaspot_capacity'].fillna(0)
    
    # 建立資料庫連接
    print("正在建立資料庫...")
    conn = sqlite3.connect(db_path)
    
    # 將資料寫入資料庫
    df.to_sql('shelters', conn, if_exists='replace', index=False)
    
    # 建立索引以提升查詢效能
    print("正在建立索引...")
    cursor = conn.cursor()
    
    # 為座標建立索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_coordinates ON shelters(latitude, longitude)')
    
    # 為災害類型建立索引
    disaster_columns = ['内水氾濫', '土石流', '地震', '大規模な火事', '崖崩れ・地滑り', '津波', '洪水', '高潮']
    for col in disaster_columns:
        cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_{col} ON shelters("{col}")')
    
    # 為名稱建立索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_name ON shelters(evaspot_name)')
    
    conn.commit()
    conn.close()
    
    print(f"資料庫建立完成！")
    print(f"總共匯入 {len(df)} 筆資料")
    print(f"資料庫檔案：{db_path}")

if __name__ == "__main__":
    csv_to_sqlite()
