import requests
import json
import pandas as pd

def fetch_and_save(csv_path: str, json_url: str):
    # 1. 下載 JSON
    resp = requests.get(json_url)
    resp.raise_for_status()
    data = resp.json()
    
    # 2. 拿到列表（若頂層是 dict 且有 "data" 則取 data，否則當作就是 list）
    if isinstance(data, dict) and 'data' in data:
        records = data['data']
    else:
        records = data
    
    rows = []
    for rec in records:
        # 把 map.lines 裡每段路線的 path 字串解析成 list，合併所有點
        coords = []
        for line in rec.get('map', {}).get('lines', []):
            path_str = line.get('path')
            if not path_str:
                continue
            try:
                pts = json.loads(path_str)  # e.g. [[lat, lng], ...]
                coords.extend(pts)
            except json.JSONDecodeError:
                continue
        
        rows.append({
            'title':              rec.get('title'),
            'beginPlace':         rec.get('beginPlace'),
            'reason':             rec.get('reason'),
            'reasonDetail':       rec.get('reasonDetail'),
            'content':            rec.get('content'),
            'beginAt':            rec.get('beginAt'),
            'expectedEndAt':      rec.get('expectedEndAt'),
            'endAt':              rec.get('endAt'),
            'note':               rec.get('note'),
            'category.name':      rec.get('category', {}).get('name'),
            # 把 list 轉 JSON 字串存進 CSV
            'coordinates':        json.dumps(coords, ensure_ascii=False)
        })
    
    # 3. 存檔
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"已寫入 {len(df)} 筆到 {csv_path}")

if __name__ == '__main__':
    # TODO: 改成你自己抓到的完整 URL
    JSON_URL = 'https://www.hozen.pref.fukui.lg.jp/hozen/yuki/assets/jsons/regulations.json?_=1749553405223'
    CSV_PATH = r'/Users/gary/Documents/project/fukui_summer/dataset/fukui_trans.csv'
    fetch_and_save(CSV_PATH, JSON_URL)
