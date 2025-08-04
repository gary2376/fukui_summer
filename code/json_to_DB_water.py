import os
import json
import sqlite3

def create_db(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS avoid_zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            coordinates TEXT NOT NULL
        )
    ''')
    conn.commit()
    return conn

def import_geojson_to_db(geojson_path, zone_type, conn):
    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    c = conn.cursor()
    count = 0
    for feature in data.get("features", []):
        name = feature.get("properties", {}).get("A31a_102", "")
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if not name or not coordinates:
            continue
        c.execute(
            "INSERT INTO avoid_zones (type, name, coordinates) VALUES (?, ?, ?)",
            (zone_type, name, json.dumps(coordinates, ensure_ascii=False))
        )
        count += 1
    print(f"{os.path.basename(geojson_path)} 已匯入 {count} 筆 {zone_type} 區域")

def batch_import(folder_path, zone_type, db_path="dataset/avoid_zones.db"):
    conn = create_db(db_path)
    for filename in os.listdir(folder_path):
        if filename.endswith(".geojson"):
            geojson_path = os.path.join(folder_path, filename)
            import_geojson_to_db(geojson_path, zone_type, conn)
    conn.commit()
    conn.close()
    print(f"所有 {zone_type} geojson 已匯入 {db_path}")

if __name__ == "__main__":
    # 修改這裡的資料夾路徑和 type
    folder_path = r"/Users/gary/Documents/project/fukui_summer/dataset/洪水/10_計画規模"  # 你的資料夾路徑
    zone_type = "water"                 # 你要標記的類型
    db_path = r"/Users/gary/Documents/project/fukui_summer/dataset/avoid_zone.db"  # 資料庫路徑
    batch_import(folder_path, zone_type, db_path)