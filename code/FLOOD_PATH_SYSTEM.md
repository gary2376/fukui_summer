# 多災害智能路徑規劃系統

## 系統概述

本系統實現了一個智能的災害路徑規劃功能，支援多種水災相關災害，能夠：

1. **實時監控水位**: 讀取福井縣各河川的水位資料
2. **多災害支援**: 支援洪水、内水氾濫、高潮三種災害類型
3. **自動風險評估**: 識別超過通報水位的危險河川
4. **動態避障規劃**: 自動避開水位超標的危險區域
5. **安全路徑生成**: 為用戶提供最安全的疏散路徑

## 系統架構

### 核心組件

1. **FloodPathService** (`flood_path_service.py`)
   - 水位資料處理
   - 風險河川篩選
   - 避難區域查詢
   - 座標解析與地理計算

2. **Website Integration** (`website.py`)
   - Streamlit 網頁界面
   - 地圖視覺化 (Folium)
   - 路徑規劃整合 (OSMnx)
   - 用戶互動功能

3. **資料來源**
   - `fukui_水位.csv`: 福井縣河川水位即時資料
   - `avoid_zone.db`: 避難區域地理資料庫

## 工作流程

### 步驟 1: 水位監控與篩選
```python
# 讀取福井_水位.csv 檔案
df = service.read_water_level_data()

# 遍歷每筆資料，檢查河川水位 >= 通報水位
for row in df:
    if current_level >= warning_level:
        flood_risk_rivers.append(river_name)
```

### 步驟 2: 災害情境確認
```python
# 支援三種水災相關災害（津波除外）
avoid_zone_disasters = ["洪水", "内水氾濫", "高潮"]
if current_disaster in avoid_zone_disasters:
    flood_risk_rivers = service.filter_flood_risk_rivers(current_disaster)
```

### 步驟 3: 避難區域匹配
```python
# 在 aviod_zone.db 中查詢匹配的避難區域
obstacle_zones = service.get_avoid_zones_for_rivers(flood_risk_rivers)
```

### 步驟 4: 路徑規劃整合
```python
# 修改路網權重，避開危險區域
if service.is_point_in_obstacle_zone(edge_lat, edge_lon, obstacle_zones):
    G[u][v][key]['length'] *= 10  # 權重增加10倍
```

## 使用方式

### 1. 啟動系統
```bash
cd fukui_summer/code
streamlit run website.py
```

### 2. 操作步驟
1. 開啟網頁界面
2. 啟動「🚨 Emergency Mode」
3. 選擇災害類型：
   - 🌀 **洪水**
   - 💧 **内水氾濫** 
   - 🌊 **高潮**
4. 系統自動：
   - 檢查當前水位狀況
   - 識別危險區域
   - 規劃安全路徑
   - 顯示警報訊息

### 3. 結果展示
- 🌀💧🌊 **災害警報**: 顯示檢測到的水位超標區域數量
- 🚧 **避障路徑**: 紅色線條顯示避開危險區域的安全路徑
- 📍 **避難所資訊**: 顯示最近避難所的距離和容量

### 4. 災害類型說明
- ✅ **支援 avoid_zone.db**: 洪水、内水氾濫、高潮
- ❌ **不支援 avoid_zone.db**: 津波、地震、土石流、大規模な火事、崖崩れ・地滑り

## 技術特色

### 1. 即時資料整合
- 解析 CSV 格式的水位資料
- 處理各種數值格式 (箭頭符號、負值、缺失值)
- 支援多種編碼格式

### 2. 智能風險評估
```python
# 水位比較邏輯
current_level = float(current_level_str.replace('→', '').replace('↑', '').replace('↓', ''))
if current_level >= warning_level:
    # 標記為危險河川
```

### 3. 地理空間計算
- 點在多邊形內判斷 (Point-in-Polygon)
- 射線法幾何算法
- 路網權重調整

### 4. 動態路徑避障
```python
# 路徑規劃權重調整
for edge in graph.edges():
    if is_in_danger_zone(edge):
        edge_weight *= 10  # 避開危險區域
```

## 測試與驗證

### 運行測試
```bash
python test_flood_integration.py
```

### 測試內容
- ✅ 水位資料讀取 (119筆記錄)
- ✅ 風險河川篩選
- ✅ 避難區域匹配
- ✅ 座標解析功能
- ✅ 系統整合測試

### 主要河川監測狀況
當前所有主要河川 (九頭竜川、足羽川、日野川、竹田川、真名川) 水位均正常，無超標情況。

## 系統特色

### 1. 自動化決策
- 無需人工判斷，系統自動檢測水位風險
- 災害類型自動匹配相應的處理邏輯

### 2. 動態適應
- 根據即時水位資料調整路徑規劃
- 支援多種災害類型的差異化處理

### 3. 用戶友好
- 直觀的地圖界面
- 清晰的警報資訊
- 一鍵操作模式

### 4. 可擴展性
- 模組化設計
- 易於新增其他災害類型
- 支援不同資料源格式

## 未來擴展

1. **即時資料更新**: 整合氣象局 API
2. **機器學習預測**: 水位趨勢預測
3. **多災害整合**: 地震、土石流等複合災害
4. **行動裝置優化**: 響應式設計

## 技術依賴

- **Python 3.8+**
- **Streamlit**: 網頁應用框架
- **Folium**: 地圖視覺化
- **OSMnx**: 路網資料與路徑規劃
- **NetworkX**: 圖論算法
- **Pandas**: 資料處理
- **SQLite**: 資料庫操作

---

這個系統成功實現了您的需求：當洪水災害發生時，自動讀取水位資料，識別危險區域，並在路徑規劃中避開這些區域，為用戶提供最安全的疏散路徑。