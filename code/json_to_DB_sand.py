import json
import sqlite3
import sys
from pathlib import Path

# 使用方式: python json_to_avoid_zones_db.py <geojson_path> <zone_type>
# 例如: python json_to_avoid_zones_db.py ../dataset/landslide.json landslide

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

def import_geojson_to_db(geojson_path, zone_type, db_path="dataset/avoid_sand.db"):
    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    conn = create_db(db_path)
    c = conn.cursor()
    count = 0
    for feature in data.get("features", []):
        name = feature.get("properties", {}).get("A33_006", "")
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if not name or not coordinates:
            continue
        c.execute(
            "INSERT INTO avoid_zones (type, name, coordinates) VALUES (?, ?, ?)",
            (zone_type, name, json.dumps(coordinates, ensure_ascii=False))
        )
        count += 1
    conn.commit()
    conn.close()
    print(f"已匯入 {count} 筆 {zone_type} 區域到 {db_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python json_to_avoid_zones_db.py <geojson_path> <zone_type>")
        sys.exit(1)
    geojson_path = sys.argv[1]
    zone_type = sys.argv[2]
    import_geojson_to_db(geojson_path, zone_type) 