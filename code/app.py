from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import pandas as pd
import folium
import os
import sqlite3
import math
import random
import osmnx as ox
from pathlib import Path
import ast  # 新增，解析字串為 list
from shapely.geometry import Point, Polygon  # 新增，判斷點是否在多邊形內
from shapely.strtree import STRtree  # 新增，空間索引加速
# 設定 OSMnx 快取資料夾到專案內，避免 Windows 權限問題
ox.settings.cache_folder = str(Path(__file__).parent.parent / 'osmnx_cache')
ox.settings.use_cache = True
ox.settings.log_console = False
import networkx as nx
import csv
import openai
from email_service import create_email_service, DEFAULT_EMAIL_TEMPLATES
from sms_service import create_sms_service, DEFAULT_SMS_TEMPLATES
from auth_service import auth_service

# 全域快取福井市路網圖（10 公里，效能更佳）
G_FUKUI = ox.graph_from_point((36.0652, 136.2216), dist=10000, network_type='walk')

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 請改為安全的 key
app.config['SESSION_COOKIE_PARTITIONED'] = False

# --- Helper Functions ---
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R: float = 6371
    lat1_rad: float = math.radians(lat1)
    lon1_rad: float = math.radians(lon1)
    lat2_rad: float = math.radians(lat2)
    lon2_rad: float = math.radians(lon2)
    dlat: float = lat2_rad - lat1_rad
    dlon: float = lon2_rad - lon1_rad
    a: float = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c: float = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def calculate_safety_index(risk_count: int, max_consecutive_risk: int, route_length: float, total_nodes: int) -> dict:
    """
    計算路徑安全指數
    
    Args:
        risk_count: 風險節點數量
        max_consecutive_risk: 最大連續風險節點數
        route_length: 路徑長度（公尺）
        total_nodes: 路徑總節點數
    
    Returns:
        dict: 包含安全指數、等級、顏色等信息
    """
    if total_nodes == 0:
        return {
            'level': '未知',
            'color': 'gray',
            'description': '無法計算安全指數',
            'risk_ratio': 0,
            'consecutive_risk': 0
        }
    
    # 計算風險比例
    risk_ratio = risk_count / total_nodes if total_nodes > 0 else 0
    
    # 簡化的安全等級判斷
    # 主要基於風險節點比例和連續風險
    if risk_count == 0:
        # 無風險節點
        level = '高'
        color = 'green'
        description = '安全的路徑'
    elif risk_count <= 2 and max_consecutive_risk <= 2:
        # 低風險：少量分散的風險節點
        level = '中'
        color = 'orange'
        description = '中等安全的路徑'
    elif max_consecutive_risk > 3 or risk_count > 5:
        # 高風險：連續風險或大量風險節點
        level = '低'
        color = 'red'
        description = '較危險的路徑'
    else:
        # 中等風險
        level = '中'
        color = 'orange'
        description = '中等安全的路徑'
    
    return {
        'level': level,
        'color': color,
        'description': description,
        'risk_ratio': round(risk_ratio * 100, 1),
        'consecutive_risk': max_consecutive_risk
    }

def load_shelter_data(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM shelters", conn)
    conn.close()
    return df

def get_virtual_gps_location() -> tuple[float, float]:
    nodes = list(G_FUKUI.nodes(data=True))
    node = random.choice(nodes)
    lat, lon = node[1]['y'], node[1]['x']
    return lat, lon

def get_route_osmnx(start_lat: float, start_lon: float, end_lat: float, end_lon: float, dist: int = 1500, max_tries: int = 3):
    last_exception = None
    for i in range(max_tries):
        try:
            G = ox.graph_from_point((start_lat, start_lon), dist=dist, network_type='walk')
            orig_node = ox.nearest_nodes(G, start_lon, start_lat)
            dest_node = ox.nearest_nodes(G, end_lon, end_lat)
            route = nx.shortest_path(G, orig_node, dest_node, weight='length')
            route_coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in route]
            return route_coords
        except Exception as e:
            last_exception = e
            dist *= 2
    return None

@app.route('/', methods=['GET', 'POST'])
def index():
    db_path = str(Path(__file__).parent.parent / 'dataset' / 'shelters.db')
    print(f"[DEBUG] shelters.db path: {db_path}")  # 路徑 debug
    disaster_types = {
        '内水氾濫': 'internal_flooding',
        '土石流': 'debris_flow',
        '地震': 'earthquake',
        '大規模な火事': 'large_fire',
        '崖崩れ・地滑り': 'landslide',
        '津波': 'tsunami',
        '洪水': 'flood',
        '高潮': 'storm_surge'
    }
    disaster_columns = list(disaster_types.keys())
    disaster_icons = {
        '内水氾濫': '💧',
        '土石流': '🌊',
        '地震': '🌍',
        '大規模な火事': '🔥',
        '崖崩れ・地滑り': '⛰️',
        '津波': '🌊',
        '洪水': '🌀',
        '高潮': '🌊'
    }
    disaster_colors = {
        '内水氾濫': 'lightblue',
        '土石流': 'beige',  # 原本是 brown，改成合法顏色
        '地震': 'red',
        '大規模な火事': 'orange',
        '崖崩れ・地滑り': 'darkred',
        '津波': 'blue',
        '洪水': 'lightgreen',
        '高潮': 'purple'
    }
    # 處理表單
    if request.method == 'POST':
        selected_disasters = request.form.getlist('disaster')
        emergency_mode = request.form.get('emergency_mode') == 'on'
        session['emergency_mode'] = emergency_mode
        session['selected_disasters'] = selected_disasters
        # 根據模式處理區域顯示開關
        if emergency_mode:
            # 緊急模式：使用緊急模式專用的 session 變數
            # 處理所有按鈕狀態，包括隱藏的輸入欄位
            show_landslide_zones = request.form.get('show_landslide_zones') == 'on'
            show_forbidden_zones = request.form.get('show_forbidden_zones') == 'on'
            show_water_zones = request.form.get('show_water_zones') == 'on'
            
            session['emergency_show_landslide_zones'] = show_landslide_zones
            session['emergency_show_forbidden_zones'] = show_forbidden_zones
            session['emergency_show_water_zones'] = show_water_zones
        else:
            # 非緊急模式：使用一般模式的 session 變數
            # 處理所有按鈕狀態，包括隱藏的輸入欄位
            show_landslide_zones = request.form.get('show_landslide_zones') == 'on'
            show_forbidden_zones = request.form.get('show_forbidden_zones') == 'on'
            show_water_zones = request.form.get('show_water_zones') == 'on'
            
            session['show_landslide_zones'] = show_landslide_zones
            session['show_forbidden_zones'] = show_forbidden_zones
            session['show_water_zones'] = show_water_zones
        # 緊急模式啟動時模擬 GPS 與隨機災害
        if emergency_mode:
            if not session.get('user_location'):
                user_lat, user_lon = get_virtual_gps_location()
                session['user_location'] = (user_lat, user_lon)
            if not session.get('emergency_disaster'):
                # 從有 shelter 的災害隨機選一個
                df = load_shelter_data(db_path)
                available_disasters = [d for d in disaster_columns if (df[d] == 1).any()]
                if available_disasters:
                    session['emergency_disaster'] = random.choice(available_disasters)
        else:
            session.pop('user_location', None)
            session.pop('emergency_disaster', None)
            session.pop('emergency_email_sent', None)
            # 清除緊急模式的區域顯示狀態
            session.pop('emergency_show_landslide_zones', None)
            session.pop('emergency_show_forbidden_zones', None)
            session.pop('emergency_show_water_zones', None)
        return redirect(url_for('index'))
    # 清除登入訊息（如果有的話）
    login_error = session.pop('login_error', None)
    email_test_success = session.pop('email_test_success', None)
    email_test_message = session.pop('email_test_message', None)
    
    # 讀取 session 狀態
    selected_disasters = session.get('selected_disasters', disaster_columns)
    emergency_mode = session.get('emergency_mode', False)
    user_location = session.get('user_location')
    emergency_disaster = session.get('emergency_disaster')
    
    # 根據模式使用不同的區域顯示狀態
    if emergency_mode:
        # 緊急模式：使用緊急模式專用的區域顯示狀態，預設關閉
        show_landslide_zones = session.get('emergency_show_landslide_zones', False)
        show_forbidden_zones = session.get('emergency_show_forbidden_zones', False)
        show_water_zones = session.get('emergency_show_water_zones', False)
    else:
        # 非緊急模式：使用一般模式的區域顯示狀態（這些按鈕在非緊急模式下不會顯示）
        show_landslide_zones = session.get('show_landslide_zones', False)
        show_forbidden_zones = session.get('show_forbidden_zones', False)
        show_water_zones = session.get('show_water_zones', False)
    
    notify_message = session.pop('notify_message', None)
    # 載入資料
    df = None
    error = None
    if os.path.exists(db_path):
        try:
            df = load_shelter_data(db_path)
            required_columns = ['latitude', 'longitude', 'evaspot_name', 'evaspot_capacity', 'evaspot_kind_name']
            if not all(col in df.columns for col in required_columns + disaster_columns):
                error = '缺少必要欄位'
        except Exception as e:
            error = str(e)
    else:
        error = '找不到資料庫檔案'
    # 篩選資料
    filtered_df = None
    if df is not None and not error:
        if emergency_mode and user_location and emergency_disaster:
            # 緊急模式：只根據 emergency_disaster 篩選
            filtered_df = df[df[emergency_disaster] == 1].copy()
        else:
            # 一般模式：根據 selected_disasters 篩選
            filter_condition = df[selected_disasters].sum(axis=1) > 0 if selected_disasters else df.index >= 0
            filtered_df = df[filter_condition].copy()
    print(f"[DEBUG] filtered_df shape: {filtered_df.shape if filtered_df is not None else None}")
    # 地圖中心
    if emergency_mode and user_location:
        map_center = user_location
        zoom_level = 16
    elif filtered_df is not None and not filtered_df.empty:
        map_center = [filtered_df['latitude'].mean(), filtered_df['longitude'].mean()]
        zoom_level = 12
    else:
        map_center = [36.0652, 136.2216]
        zoom_level = 12
    # 產生 Folium 地圖
    m = folium.Map(location=map_center, zoom_start=zoom_level)
    # 緊急模式最近避難所
    nearest_shelters = []
    route_too_far_message = None
    landslide_polygons = []  # 修正作用域，確保任何情況下都初始化
    water_polygons = []  # 新增 water 區域多邊形
    if emergency_mode and user_location and filtered_df is not None and not filtered_df.empty and emergency_disaster:
        # 初始化變數
        forbidden_polygons = []
        landslide_polygons = []
        water_polygons = []
        landslide_tree = None
        water_tree = None
        
        # 只在需要顯示禁行區域時才讀取
        if show_forbidden_zones:
            trans_path = str(Path(__file__).parent.parent / 'dataset' / 'fukui_trans.csv')
            if os.path.exists(trans_path):
                df_trans = pd.read_csv(trans_path, encoding='utf-8')  # 強制 utf-8
                for _, row in df_trans.iterrows():
                    try:
                        coords = ast.literal_eval(row['coordinates'])
                        if len(coords) >= 3:
                            forbidden_polygons.append(Polygon(coords))
                    except Exception:
                        pass
        
        # 只在需要顯示 landslide 區域且災害類型符合時才讀取
        if show_landslide_zones and emergency_disaster in ['崖崩れ・地滑り', '地震']:
            avoid_db_path = str(Path(__file__).parent.parent / 'dataset' / 'avoid_zone.db')
            if os.path.exists(avoid_db_path):
                conn = sqlite3.connect(avoid_db_path)
                cursor = conn.cursor()
                try:
                    # 只讀取使用者附近 10km 範圍內的 landslide areas
                    user_lat, user_lon = user_location
                    lat_min, lat_max = user_lat - 0.1, user_lat + 0.1  # 約 11km
                    lon_min, lon_max = user_lon - 0.1, user_lon + 0.1  # 約 11km
                    
                    cursor.execute("SELECT coordinates FROM avoid_zones WHERE type='landslide'")
                    rows = cursor.fetchall()
                    
                    for (coord_str,) in rows:
                        try:
                            coords_raw = ast.literal_eval(coord_str)
                            # 支援多重巢狀格式
                            if coords_raw and isinstance(coords_raw[0], list) and isinstance(coords_raw[0][0], list):
                                coords = [[pt[1], pt[0]] for pt in coords_raw[0]]
                            else:
                                coords = [[pt[1], pt[0]] for pt in coords_raw]
                            
                            # 快速過濾：檢查多邊形是否在感興趣的範圍內
                            if len(coords) >= 3:
                                # 計算多邊形的邊界框
                                lats = [pt[0] for pt in coords]
                                lons = [pt[1] for pt in coords]
                                poly_lat_min, poly_lat_max = min(lats), max(lats)
                                poly_lon_min, poly_lon_max = min(lons), max(lons)
                                
                                # 檢查邊界框是否與感興趣區域重疊
                                if (poly_lat_max >= lat_min and poly_lat_min <= lat_max and 
                                    poly_lon_max >= lon_min and poly_lon_min <= lon_max):
                                    poly = Polygon(coords)
                                    landslide_polygons.append(poly)
                        except Exception as e:
                            print(f"landslide poly parse error: {e}")
                    
                    print(f"[DEBUG] Loaded {len(landslide_polygons)} landslide polygons in user area")
                    
                except Exception as e:
                    print(f"landslide db error: {e}")
                conn.close()
            landslide_tree = STRtree(landslide_polygons) if landslide_polygons else None
        
        # 只在需要顯示 water 區域且災害類型符合時才讀取
        if show_water_zones and emergency_disaster in ['洪水', '内水氾濫', '高潮']:
            avoid_db_path = str(Path(__file__).parent.parent / 'dataset' / 'avoid_zone.db')
            if os.path.exists(avoid_db_path):
                conn = sqlite3.connect(avoid_db_path)
                cursor = conn.cursor()
                try:
                    # 只讀取使用者附近 10km 範圍內的 water areas
                    user_lat, user_lon = user_location
                    lat_min, lat_max = user_lat - 0.1, user_lat + 0.1  # 約 11km
                    lon_min, lon_max = user_lon - 0.1, user_lon + 0.1  # 約 11km
                    
                    cursor.execute("SELECT coordinates FROM avoid_zones WHERE type='water'")
                    rows = cursor.fetchall()
                    
                    for (coord_str,) in rows:
                        try:
                            coords_raw = ast.literal_eval(coord_str)
                            if coords_raw and isinstance(coords_raw[0], list) and isinstance(coords_raw[0][0], list):
                                coords = [[pt[1], pt[0]] for pt in coords_raw[0]]
                            else:
                                coords = [[pt[1], pt[0]] for pt in coords_raw]
                            
                            # 快速過濾：檢查多邊形是否在感興趣的範圍內
                            if len(coords) >= 3:
                                # 計算多邊形的邊界框
                                lats = [pt[0] for pt in coords]
                                lons = [pt[1] for pt in coords]
                                poly_lat_min, poly_lat_max = min(lats), max(lats)
                                poly_lon_min, poly_lon_max = min(lons), max(lons)
                                
                                # 檢查邊界框是否與感興趣區域重疊
                                if (poly_lat_max >= lat_min and poly_lat_min <= lat_max and 
                                    poly_lon_max >= lon_min and poly_lon_min <= lon_max):
                                    poly = Polygon(coords)
                                    water_polygons.append(poly)
                        except Exception as e:
                            print(f"water poly parse error: {e}")
                    
                    print(f"[DEBUG] Loaded {len(water_polygons)} water polygons in user area")
                    
                except Exception as e:
                    print(f"water db error: {e}")
                conn.close()
            water_tree = STRtree(water_polygons) if water_polygons else None
        # 只顯示包含當前災害類型的避難所
        print(f"[DEBUG] emergency_disaster: {emergency_disaster}")
        print(f"[DEBUG] filtered_df columns: {filtered_df.columns}")
        print(f"[DEBUG] filtered_df preview: {filtered_df.head()}")
        filtered_df = filtered_df[filtered_df[emergency_disaster] == 1].copy()
        print(f"[DEBUG] filtered_df after disaster filter shape: {filtered_df.shape}")
        print(f"[DEBUG] filtered_df after disaster filter preview: {filtered_df.head()}")
        if not filtered_df.empty:
            user_lat, user_lon = user_location
            distances = []
            for idx, row in filtered_df.iterrows():
                distance = calculate_distance(user_lat, user_lon, row['latitude'], row['longitude'])
                distances.append((distance, idx, row))
            distances.sort(key=lambda x: x[0])
            # 顯示所有符合災害的避難所
            nearest_shelters = distances  # 不再只取前10，全部顯示
            print(f"[DEBUG] nearest_shelters: {nearest_shelters}")
            # 標記使用者位置
            folium.Marker(
                location=[user_lat, user_lon],
                popup=folium.Popup("🧑 Your location", max_width=200),
                tooltip="Your location",
                icon=folium.Icon(color='green', icon='user', prefix='fa')
            ).add_to(m)
            # 只針對最近一個 shelter 畫路線
            if nearest_shelters:
                distance, idx, row = nearest_shelters[0]
                route_coords = None
                route_length = None
                route_warning = None
                try:
                    # 動態產生 G，中心為 user_location，半徑 5000 公尺
                    G = ox.graph_from_point((user_lat, user_lon), dist=5000, network_type='walk')
                    
                    # 處理禁行區域（完全移除節點）
                    if forbidden_polygons:
                        nodes_to_remove = []
                        for n, data in G.nodes(data=True):
                            pt = Point(data['y'], data['x'])
                            if any(isinstance(poly, Polygon) and poly.contains(pt) for poly in forbidden_polygons):
                                nodes_to_remove.append(n)
                        G.remove_nodes_from(nodes_to_remove)
                    
                    # 標記高風險節點（不移除，而是標記風險等級）
                    risk_nodes = set()
                    if landslide_tree and emergency_disaster in ['崖崩れ・地滑り', '地震']:
                        for n, data in G.nodes(data=True):
                            pt = Point(data['y'], data['x'])
                            for poly in landslide_tree.query(pt):
                                if isinstance(poly, Polygon) and poly.contains(pt):
                                    risk_nodes.add(n)
                                    break
                    
                    if water_tree and emergency_disaster in ['洪水', '内水氾濫', '高潮']:
                        for n, data in G.nodes(data=True):
                            pt = Point(data['y'], data['x'])
                            for poly in water_tree.query(pt):
                                if isinstance(poly, Polygon) and poly.contains(pt):
                                    risk_nodes.add(n)
                                    break
                    
                    orig_node = ox.nearest_nodes(G, user_lon, user_lat)
                    dest_node = ox.nearest_nodes(G, row['longitude'], row['latitude'])
                    
                    # 調試節點資訊
                    orig_coords = (G.nodes[orig_node]['y'], G.nodes[orig_node]['x'])
                    dest_coords = (G.nodes[dest_node]['y'], G.nodes[dest_node]['x'])
                    print(f"[DEBUG] Original user location: ({user_lat}, {user_lon})")
                    print(f"[DEBUG] Nearest node to user: {orig_node} at {orig_coords}")
                    print(f"[DEBUG] Original shelter location: ({row['latitude']}, {row['longitude']})")
                    print(f"[DEBUG] Nearest node to shelter: {dest_node} at {dest_coords}")
                    
                    # 檢查節點距離
                    node_distance = calculate_distance(orig_coords[0], orig_coords[1], dest_coords[0], dest_coords[1])
                    print(f"[DEBUG] Distance between nearest nodes: {node_distance:.3f} km")
                    
                    # 嘗試多條路徑並選擇風險最低的路徑
                    best_route = None
                    best_route_score = float('inf')
                    best_route_length = None
                    
                    # 嘗試不同的路徑算法和權重
                    path_attempts = [
                        ('shortest', 'length'),
                        ('shortest', 'length', 1.5),  # 增加長度權重
                        ('shortest', 'length', 2.0),  # 進一步增加長度權重
                        ('astar', 'length'),  # A*算法
                    ]
                    
                    for attempt in path_attempts:
                        try:
                            if attempt[0] == 'astar':
                                # A*算法
                                route = nx.astar_path(G, orig_node, dest_node, weight=attempt[1])
                            elif len(attempt) == 2:
                                # 標準最短路徑
                                route = nx.shortest_path(G, orig_node, dest_node, weight=attempt[1])
                            else:
                                # 帶權重的最短路徑
                                weight_func = lambda u, v, d: d[attempt[1]] * attempt[2]
                                route = nx.shortest_path(G, orig_node, dest_node, weight=weight_func)
                            
                            # 計算路徑風險分數
                            risk_count = sum(1 for node in route if node in risk_nodes)
                            route_length = sum(
                                G.edges[route[i], route[i+1], 0]['length']
                                for i in range(len(route)-1)
                            )
                            # 確保路徑長度不為負數且合理
                            if route_length < 0:
                                print(f"[WARNING] Negative route length: {route_length}")
                                route_length = abs(route_length)
                            
                            # 計算連續風險段（連續的高風險節點）
                            consecutive_risk = 0
                            max_consecutive_risk = 0
                            for node in route:
                                if node in risk_nodes:
                                    consecutive_risk += 1
                                    max_consecutive_risk = max(max_consecutive_risk, consecutive_risk)
                                else:
                                    consecutive_risk = 0
                            
                            # 綜合評分：風險節點數量 + 連續風險懲罰 + 路徑長度懲罰
                            # 風險節點權重為1000，連續風險權重為5000，路徑長度權重為1
                            route_score = risk_count * 1000 + max_consecutive_risk * 5000 + route_length
                            
                            if route_score < best_route_score:
                                best_route = route
                                best_route_score = route_score
                                best_route_length = route_length
                                
                        except Exception as e:
                            print(f"Path attempt failed: {e}")
                            continue
                    
                    # 如果所有嘗試都失敗，使用原始的最短路徑
                    if best_route is None:
                        try:
                            best_route = nx.shortest_path(G, orig_node, dest_node, weight='length')
                            best_route_length = sum(
                                G.edges[best_route[i], best_route[i+1], 0]['length']
                                for i in range(len(best_route)-1)
                            )
                        except Exception as e:
                            print(f"Fallback path failed: {e}")
                            best_route = None
                            best_route_length = None
                    
                    if best_route:
                        route_coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in best_route]
                        route_length = best_route_length
                        
                        # 調試資訊
                        print(f"[DEBUG] Route calculation for shelter: {row['evaspot_name']}")
                        print(f"[DEBUG] User location: ({user_lat}, {user_lon})")
                        print(f"[DEBUG] Shelter location: ({row['latitude']}, {row['longitude']})")
                        print(f"[DEBUG] Straight distance: {distance:.3f} km")
                        print(f"[DEBUG] Route length: {route_length:.1f} meters ({route_length/1000:.3f} km)")
                        print(f"[DEBUG] Route nodes: {len(best_route)}")
                        
                        # 驗證路徑長度合理性
                        if route_length < distance * 1000 * 0.8:  # 路徑長度不應該比直線距離短太多
                            print(f"[WARNING] Route length ({route_length/1000:.3f} km) is shorter than straight distance ({distance:.3f} km)")
                            # 如果路徑長度不合理，使用直線距離的1.2倍作為估算
                            route_length = distance * 1000 * 1.2
                            print(f"[FIXED] Using estimated route length: {route_length/1000:.3f} km")
                        
                        # 將路徑長度添加到最近避難所的資訊中
                        if nearest_shelters and nearest_shelters[0][1] == idx:
                            nearest_shelters[0][2]['route_length'] = route_length
                            print(f"[DEBUG] Stored route_length: {route_length} meters to shelter info")
                        
                        # 計算風險統計
                        risk_count = sum(1 for node in best_route if node in risk_nodes)
                        consecutive_risk = 0
                        max_consecutive_risk = 0
                        for node in best_route:
                            if node in risk_nodes:
                                consecutive_risk += 1
                                max_consecutive_risk = max(max_consecutive_risk, consecutive_risk)
                            else:
                                consecutive_risk = 0
                        
                        # 計算安全指數
                        safety_info = calculate_safety_index(risk_count, max_consecutive_risk, route_length, len(best_route))
                        
                        if risk_count > 0:
                            if max_consecutive_risk > 3:
                                route_warning = f"⚠️ 高風險：路徑經過 {risk_count} 個高風險區域（連續 {max_consecutive_risk} 個）"
                            else:
                                route_warning = f"⚠️ 中風險：路徑經過 {risk_count} 個高風險區域"
                        else:
                            route_warning = "✅ 路徑安全，無高風險區域"
                    print(f"[DEBUG] orig_node: {orig_node}, dest_node: {dest_node}")
                    print(f"[DEBUG] route_coords: {route_coords}")
                    print(f"[DEBUG] route_length: {route_length}")
                    print(f"[DEBUG] distance: {distance}")
                    if 'best_route' in locals() and best_route:
                        risk_count = sum(1 for node in best_route if node in risk_nodes)
                        print(f"[DEBUG] Risk nodes in route: {risk_count}")
                        print(f"[DEBUG] Total risk nodes in graph: {len(risk_nodes)}")
                    route_warning = None
                except Exception as e:
                    route_coords = None
                    route_length = None
                    route_warning = None
                # 僅保留路徑規劃相關 debug print
                # print(f"[DEBUG] orig_node: {orig_node}, dest_node: {dest_node}")
                # print(f"[DEBUG] route_coords: {route_coords}")
                # print(f"[DEBUG] route_length: {route_length}")
                # print(f"[DEBUG] distance: {distance}")
                if (route_length is not None and route_length > 10000) or (distance > 10):
                    route_too_far_message = "The route is more than 10 km, and requires no evacuation."
                elif route_coords:
                    # 根據風險等級選擇路徑顏色
                    risk_count = sum(1 for node in best_route if node in risk_nodes) if 'best_route' in locals() else 0
                    consecutive_risk = 0
                    max_consecutive_risk = 0
                    for node in best_route:
                        if node in risk_nodes:
                            consecutive_risk += 1
                            max_consecutive_risk = max(max_consecutive_risk, consecutive_risk)
                        else:
                            consecutive_risk = 0
                    
                    # 使用藍色路線，移除安全評估
                    route_color = 'blue'
                    
                    # 簡化的路線資訊顯示
                    route_info_html = f"""
                    <div style="text-align: center; padding: 10px;">
                        <h4 style="margin: 0 0 10px 0; color: #007bff;">
                            🛣️ 避難路線
                        </h4>
                        <p style="margin: 5px 0; font-size: 12px;">
                            📏 路徑長度: {route_length:.0f} 公尺<br>
                            ⏱️ 預估時間: {int(route_length / 80)} 分鐘
                        </p>
                    </div>
                    """
                    
                    folium.PolyLine(
                        locations=route_coords,
                        color=route_color, weight=4, opacity=0.8,
                        popup=folium.Popup(
                            f"<div style='width: 300px;'>"
                            f"<h3 style='margin: 0 0 10px 0;'>📍 {row['evaspot_name']}</h3>"
                            f"<p style='margin: 5px 0;'>📍 距離: {distance:.2f} km</p>"
                            f"{route_info_html}"
                            f"</div>",
                            max_width=350
                        )
                    ).add_to(m)
            # 畫所有符合災害的避難所 marker
            for i, (distance, idx, row) in enumerate(nearest_shelters):
                applicable_disasters = [d for d in disaster_columns if row[d] == 1]
                primary_disaster = applicable_disasters[0] if applicable_disasters else '地震'
                marker_color = 'red' if i == 0 else disaster_colors.get(primary_disaster, 'gray')
                capacity_display = f"{row['evaspot_capacity']:,.0f}" if pd.notna(row['evaspot_capacity']) and row['evaspot_capacity'] > 0 else "未標示"
                if i == 0 and row.get('route_length'):
                    walk_time_min = int(row['route_length'] / 80)  # 80米/分鐘步行速度
                    distance_info = f"<b>📏 Straight Distance:</b> {distance:.2f} km<br><b>🛣️ Walking Distance:</b> {row['route_length']/1000:.2f} km<br>"
                    print(f"[DEBUG] Popup: route_length={row['route_length']}, walk_time={walk_time_min}")
                else:
                    walk_time_min = int(distance * 1000 / 80)
                    distance_info = f"<b>📏 Distance:</b> {distance:.2f} km<br>"
                popup_html = f"""
                <b>📍 Name:</b> {row['evaspot_name']}<br>
                <b>👥 Capacity:</b> {capacity_display}<br>
                <b>🔰 Type:</b> {row['evaspot_kind_name']}<br>
                <b>⚠️ Fit Disaster:</b> {', '.join(applicable_disasters)}<br>
                {distance_info}
                <b>⏱️ Predict time:</b> {walk_time_min} Minutes<br>
                """
                

                popup = folium.Popup(popup_html, max_width=300)
                try:
                    folium.Marker(
                        location=[row['latitude'], row['longitude']],
                        popup=popup,
                        tooltip=f"{row['evaspot_name']} ({', '.join(applicable_disasters)})",
                        icon=folium.Icon(color=marker_color, icon='info-sign')
                    ).add_to(m)
                except Exception as e:
                    print(f"[DEBUG] Marker error: {e}")
    elif filtered_df is not None and not filtered_df.empty:
        for idx, row in filtered_df.iterrows():
            applicable_disasters = [d for d in disaster_columns if row[d] == 1]
            primary_disaster = applicable_disasters[0] if applicable_disasters else '地震'
            marker_color = disaster_colors.get(primary_disaster, 'gray')
            popup_html = f"""
            <b>📍 Name:</b> {row['evaspot_name']}<br>
            <b>👥 Capacity:</b> {row['evaspot_capacity']:,.0f}<br>
            <b>🔰 Type:</b> {row['evaspot_kind_name']}<br>
            <b>⚠️ Fit Disaster:</b> {', '.join(applicable_disasters)}<br>
            """
            popup = folium.Popup(popup_html, max_width=300)
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=popup,
                tooltip=f"{row['evaspot_name']} ({', '.join(applicable_disasters)})",
                icon=folium.Icon(color=marker_color, icon='info-sign')
            ).add_to(m)
    # 疊加不可通行區域多邊形（紫色，僅開關開啟時）
    trans_path = str(Path(__file__).parent.parent / 'dataset' / 'fukui_trans.csv')
    if os.path.exists(trans_path) and show_forbidden_zones:
        df_trans = pd.read_csv(trans_path, encoding='utf-8')  # 強制 utf-8
        for _, row in df_trans.iterrows():
            if 'coordinates' in row and pd.notna(row['coordinates']):
                try:
                    coords_raw = ast.literal_eval(row['coordinates'])
                    # 自動修正格式：如果是 [(lon, lat), ...] 轉成 [(lat, lon), ...]
                    coords = []
                    for pt in coords_raw:
                        if isinstance(pt, (list, tuple)) and len(pt) == 2:
                            # 判斷是否經緯度反了（經度通常在 135~137，緯度在 35~37）
                            lon, lat = pt
                            if 130 < lon < 140 and 34 < lat < 38:
                                coords.append((lat, lon))
                            else:
                                coords.append((float(pt[0]), float(pt[1])))
                        else:
                            print(f"[DEBUG] skip invalid point: {pt}")
                    if len(coords) >= 3:
                        folium.Polygon(
                            locations=coords,
                            color='#8000ff',
                            fill=True,
                            fill_color='#8000ff',
                            fill_opacity=0.5,
                            popup=row.get('title', '不可通行區域')
                        ).add_to(m)
                    else:
                        print(f"[DEBUG] Not enough points for polygon: {coords}")
                except Exception as e:
                    print(f"[DEBUG] Polygon error: {e}")
            else:
                print(f"[DEBUG] row skipped, no coordinates")
    # 疊加 landslide 高風險區域多邊形（紅色，僅 landslide 開關開啟時）
    if landslide_polygons and show_landslide_zones:
        for poly in landslide_polygons:
            try:
                folium.Polygon(
                    locations=[(lat, lon) for lat, lon in poly.exterior.coords],
                    color='red',
                    fill=True,
                    fill_color='red',
                    fill_opacity=0.8,
                    popup='高風險崩塌/地滑區域'
                ).add_to(m)
                print(f"add folium poly: {poly.bounds}")
            except Exception as e:
                print(f"folium poly error: {e}")
    # 疊加 water 高風險區域多邊形（藍色，僅 water 開關開啟時）
    if water_polygons and show_water_zones:
        for poly in water_polygons:
            try:
                folium.Polygon(
                    locations=[(lat, lon) for lat, lon in poly.exterior.coords],
                    color='blue',
                    fill=True,
                    fill_color='blue',
                    fill_opacity=0.5,
                    popup='高風險水災區域'
                ).add_to(m)
                print(f"add water folium poly: {poly.bounds}")
            except Exception as e:
                print(f"water folium poly error: {e}")
    

    map_html = m._repr_html_()
    # 統計卡片
    total_shelters = len(filtered_df) if filtered_df is not None else 0
    total_capacity = int(filtered_df['evaspot_capacity'].fillna(0).sum()) if filtered_df is not None else 0
    # 數據表格
    display_columns = ['latitude', 'longitude', 'evaspot_name', 'evaspot_capacity', 'evaspot_kind_name'] + [d for d in disaster_columns if d in selected_disasters]
    table_html = filtered_df[display_columns].to_html(classes='table table-striped table-bordered', index=False) if filtered_df is not None else ''
    return render_template('index.html',
        error=error,
        filtered_df=filtered_df,
        disaster_types=disaster_types,
        disaster_columns=disaster_columns,
        disaster_icons=disaster_icons,
        disaster_colors=disaster_colors,
        selected_disasters=selected_disasters,
        emergency_mode=emergency_mode,
        user_location=user_location,
        emergency_disaster=emergency_disaster,
        map_html=map_html,
        total_shelters=total_shelters,
        total_capacity=total_capacity,
        table_html=table_html,
        nearest_shelters=nearest_shelters,
        route_too_far_message=route_too_far_message,
        show_landslide_zones=show_landslide_zones,
        show_forbidden_zones=show_forbidden_zones,
        show_water_zones=show_water_zones,
        notify_message=notify_message,
        login_error=login_error,
        email_test_success=email_test_success,
        email_test_message=email_test_message,
        user_info=session.get('user_info')
    )

@app.route('/clear_location')
def clear_location():
    session.pop('user_location', None)
    session.pop('emergency_disaster', None)
    return redirect(url_for('index'))

@app.route('/toggle_emergency', methods=['POST'])
def toggle_emergency():
    emergency_mode = not session.get('emergency_mode', False)
    session['emergency_mode'] = emergency_mode
    if emergency_mode:
        db_path = str(Path(__file__).parent.parent / 'dataset' / 'shelters.db')
        if not session.get('user_location'):
            user_lat, user_lon = get_virtual_gps_location()
            session['user_location'] = (user_lat, user_lon)
        if not session.get('emergency_disaster'):
            df = load_shelter_data(db_path)
            disaster_columns = [
                '内水氾濫', '土石流', '地震', '大規模な火事', '崖崩れ・地滑り', '津波', '洪水', '高潮'
            ]
            available_disasters = [d for d in disaster_columns if (df[d] == 1).any()]
            if available_disasters:
                session['emergency_disaster'] = random.choice(available_disasters)
    else:
        session.pop('user_location', None)
        session.pop('emergency_disaster', None)
    return redirect(url_for('index'))

@app.route('/add_contact', methods=['POST'])
def add_contact():
    name: str = request.form.get('name', '').strip()
    phone: str = request.form.get('phone', '').strip()
    email: str = request.form.get('email', '').strip()
    if not name or not phone or not email:
        return redirect(url_for('index'))
    csv_path = str(Path(__file__).parent.parent / 'dataset' / 'contacts.csv')
    file_exists: bool = os.path.isfile(csv_path)
    with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        if not file_exists:
            writer.writerow(['姓名', '電話', '信箱'])
        writer.writerow([name, phone, email])
    return redirect(url_for('index'))

@app.route('/login', methods=['POST'])
def login():
    """使用者登入處理"""
    email = request.form.get('email')
    password = request.form.get('password')
    
    if email and password:
        # 驗證使用者憑證
        success, message, user_info = auth_service.verify_credentials(email, password)
        
        if success:
            # 儲存使用者資訊到 session
            session['user_info'] = user_info
            session['logged_in'] = True
            
            # 測試 Email 發送功能
            test_success, test_message = auth_service.test_email_sending(user_info)
            if test_success:
                session['email_test_success'] = True
                session['email_test_message'] = test_message
            else:
                session['email_test_success'] = False
                session['email_test_message'] = test_message
            
            return redirect(url_for('index'))
        else:
            # 登入失敗，返回首頁並顯示錯誤訊息
            session['login_error'] = message
            return redirect(url_for('index'))
    
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """使用者登出"""
    session.clear()
    return redirect(url_for('index'))

@app.route('/contacts', methods=['GET', 'POST'])
def contacts():
    # 檢查是否已登入
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    
    csv_path = str(Path(__file__).parent.parent / 'dataset' / 'contacts.csv')
    contacts: list[dict] = []
    # 新增聯絡人
    if request.method == 'POST':
        name: str = request.form.get('name', '').strip()
        phone: str = request.form.get('phone', '').strip()
        email: str = request.form.get('email', '').strip()
        if name and phone and email:
            file_exists: bool = os.path.isfile(csv_path)
            with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                if not file_exists:
                    writer.writerow(['姓名', '電話', '信箱'])
                writer.writerow([name, phone, email])
        return redirect(url_for('contacts'))
    # 讀取聯絡人清單
    if os.path.isfile(csv_path):
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            contacts = list(reader)
    return render_template('contacts.html', contacts=contacts, user_info=session.get('user_info'))

@app.route('/delete_contact', methods=['POST'])
def delete_contact():
    """刪除聯絡人"""
    # 檢查是否已登入
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    
    email = request.form.get('email', '').strip()
    if not email:
        return redirect(url_for('contacts'))
    
    csv_path = str(Path(__file__).parent.parent / 'dataset' / 'contacts.csv')
    if os.path.isfile(csv_path):
        # 讀取所有聯絡人
        contacts = []
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            contacts = list(reader)
        
        # 過濾掉要刪除的聯絡人
        filtered_contacts = [contact for contact in contacts if contact['信箱'] != email]
        
        # 重新寫入檔案
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            if filtered_contacts:
                writer = csv.DictWriter(csvfile, fieldnames=['姓名', '電話', '信箱'])
                writer.writeheader()
                writer.writerows(filtered_contacts)
            else:
                # 如果沒有聯絡人了，只寫入標題
                writer = csv.writer(csvfile)
                writer.writerow(['姓名', '電話', '信箱'])
    
    return redirect(url_for('contacts'))

@app.route('/notify_contacts', methods=['POST'])
def notify_contacts():
    """發送簡訊通知（模擬模式）"""
    csv_path = str(Path(__file__).parent.parent / 'dataset' / 'contacts.csv')
    contacts: list[dict] = []
    if os.path.isfile(csv_path):
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            contacts = list(reader)
    
    if not contacts:
        session['notify_message'] = "沒有聯絡人可以通知。"
        return redirect(url_for('index'))
    
    # 取得簡訊模板類型
    template_type = request.form.get('template_type', 'emergency')
    custom_message = request.form.get('custom_message', '')
    
    # 選擇簡訊模板
    if template_type == 'custom' and custom_message:
        message_template = f"Custom message: {{name}}, {custom_message}"
    else:
        message_template = DEFAULT_SMS_TEMPLATES.get(template_type, DEFAULT_SMS_TEMPLATES['emergency'])
    
    # 建立簡訊服務並發送（模擬模式）
    sms_service = create_sms_service()
    results = sms_service.send_bulk_sms(contacts, message_template)
    
    # 統計結果
    success_count = sum(1 for result in results if result['success'])
    failed_count = len(results) - success_count
    
    if failed_count == 0:
        session['notify_message'] = f"Successfully sent SMS to {success_count} contacts (simulation mode)"
    else:
        session['notify_message'] = f"SMS sending completed: {success_count} successful, {failed_count} failed (simulation mode)"
    
    # 儲存發送記錄
    session['last_sms_results'] = results
    
    return redirect(url_for('index'))

@app.route('/notify_email', methods=['POST'])
def notify_email():
    """發送 Email 通知"""
    csv_path = str(Path(__file__).parent.parent / 'dataset' / 'contacts.csv')
    contacts: list[dict] = []
    if os.path.isfile(csv_path):
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            contacts = list(reader)
    if not contacts:
        session['notify_message'] = "沒有聯絡人可以通知。"
        return redirect(url_for('index'))
    template_type = request.form.get('template_type', 'emergency')
    custom_message = request.form.get('custom_message', '')
    user_location = session.get('user_location')
    latlng = ''
    nearest_shelter = ''
    nearest_distance = None
    if user_location:
        latlng = f"{user_location[0]:.5f},{user_location[1]:.5f}"
        db_path = str(Path(__file__).parent.parent / 'dataset' / 'shelters.db')
        df = load_shelter_data(db_path)
        emergency_disaster = session.get('emergency_disaster')
        if df is not None and emergency_disaster in df.columns:
            filtered_df = df[df[emergency_disaster] == 1].copy()
            if not filtered_df.empty:
                filtered_df['distance'] = filtered_df.apply(lambda row: calculate_distance(user_location[0], user_location[1], row['latitude'], row['longitude']), axis=1)
                nearest_row = filtered_df.sort_values('distance').iloc[0]
                nearest_shelter = nearest_row['evaspot_name']
                nearest_distance = nearest_row['distance']
    if template_type == 'custom' and custom_message:
        subject_template = f"Custom Notification - {{name}}"
        message_template = f"Custom message: {{name}}, {custom_message}"
        html_template = f'<html><body><p>Custom message: {{name}}, {custom_message}</p></body></html>'
    else:
        template = DEFAULT_EMAIL_TEMPLATES.get(template_type, DEFAULT_EMAIL_TEMPLATES['emergency'])
        subject_template = template['subject']
        message_template = template['message']
        html_template = template.get('html')
    user_info = session.get('user_info')
    if user_info:
        email_service = create_email_service('user', user_info)
    else:
        email_service = create_email_service()
    results = []
    for contact in contacts:
        if nearest_distance is not None and nearest_distance > 10:
            message = "I am safe now. The nearest shelter is over 10km away, so no evacuation is needed for now."
            html = '<html><body><p>I am safe now<br>The nearest shelter is over 10km away, so no evacuation is needed for now.</p></body></html>'
        else:
            message = message_template.format(name=contact['姓名'], latlng=latlng, nearest_shelter=nearest_shelter)
            html = html_template.format(name=contact['姓名'], latlng=latlng, nearest_shelter=nearest_shelter)
        subject = subject_template.format(name=contact['姓名'], latlng=latlng, nearest_shelter=nearest_shelter)
        result = email_service.send_email(contact['信箱'], subject, message, html)
        results.append(result)
    success_count = sum(1 for result in results if result['success'])
    failed_count = len(results) - success_count
    if failed_count == 0:
        session['notify_message'] = f"Successfully sent Email to {success_count} contacts."
    else:
        session['notify_message'] = f"Email sending completed: {success_count} successful, {failed_count} failed."
    session['last_email_results'] = results
    return redirect(url_for('index'))

@app.route('/api/email_status', methods=['GET'])
def email_status():
    """查詢 Email 發送狀態"""
    results = session.get('last_email_results', [])
    return jsonify({
        'results': results,
        'total': len(results),
        'success': sum(1 for r in results if r['success']),
        'failed': sum(1 for r in results if not r['success'])
    })

@app.route('/api/sms_status', methods=['GET'])
def sms_status():
    """查詢簡訊發送狀態"""
    results = session.get('last_sms_results', [])
    return jsonify({
        'results': results,
        'total': len(results),
        'success': sum(1 for r in results if r['success']),
        'failed': sum(1 for r in results if not r['success'])
    })

from flask import session

@app.route('/items', methods=['GET', 'POST'])
def items():
    # Default categories and items
    base_categories = [
        {
            'name': 'Food',
            'items': [
                {'name': 'Water', 'icon': '💧', 'jp': '水（みず）'},
                {'name': 'Bread', 'icon': '🍞', 'jp': 'パン'},
                {'name': 'Canned Food', 'icon': '🥫', 'jp': '缶詰（かんづめ）'},
                {'name': 'Biscuits', 'icon': '🍪', 'jp': 'ビスケット'},
            ]
        },
        {
            'name': 'Clothing',
            'items': [
                {'name': 'Clothes', 'icon': '👕', 'jp': '衣類（いるい）'},
                {'name': 'Blanket', 'icon': '🧣', 'jp': '毛布（もうふ）'},
                {'name': 'Socks', 'icon': '🧦', 'jp': '靴下（くつした）'},
            ]
        },
        {
            'name': 'Housing',
            'items': [
                {'name': 'Tent', 'icon': '⛺', 'jp': 'テント'},
                {'name': 'Sleeping Bag', 'icon': '🛏️', 'jp': '寝袋（ねぶくろ）'},
                {'name': 'Flashlight', 'icon': '🔦', 'jp': '懐中電灯（かいちゅうでんとう）'},
            ]
        },
        {
            'name': 'Transportation',
            'items': [
                {'name': 'Bicycle', 'icon': '🚲', 'jp': '自転車（じてんしゃ）'},
                {'name': 'Umbrella', 'icon': '☂️', 'jp': '傘（かさ）'},
                {'name': 'Medicine', 'icon': '💊', 'jp': '薬（くすり）'},
            ]
        },
    ]
    # 新增自定義用品
    if request.method == 'POST':
        category = request.form.get('category', '').strip()
        name = request.form.get('name', '').strip()
        icon = request.form.get('icon', '').strip()
        if category and name and icon:
            jp = name
            try:
                OPENAI_API_KEY = "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"  # <--- 請在這裡填入你的 API Key
                client = openai.OpenAI(api_key=OPENAI_API_KEY)
                if OPENAI_API_KEY:
                    prompt = f"請將下列中文詞語翻譯成日文，僅回傳日文詞語本身，不要加註解：{name}"
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=20,
                        temperature=0
                    )
                    jp = response.choices[0].message.content.strip()
                else:
                    print('未設定 OPENAI_API_KEY，無法自動翻譯')
                    jp = name + '（翻譯失敗）'
            except Exception as e:
                print(f'GPT翻譯失敗: {e}')
                jp = name + '（翻譯失敗）'
            custom_items = session.get('custom_items', [])
            custom_items.append({'category': category, 'name': name, 'jp': jp, 'icon': icon})
            session['custom_items'] = custom_items
        return redirect(url_for('items'))
    # Merge custom items
    item_categories = []
    for cat in base_categories:
        new_cat = {
            'name': cat['name'],
            'items': cat['items'].copy()
        }
        item_categories.append(new_cat)
    custom_items = session.get('custom_items', [])
    for item in custom_items:
        for cat in item_categories:
            if cat['name'] == item['category']:
                cat['items'].append({'name': item['name'], 'icon': item['icon'], 'jp': item['jp']})
    return render_template('items.html', categories=item_categories)

@app.route('/items/delete', methods=['POST'])
def delete_item():
    idx = request.form.get('idx', type=int)
    custom_items = session.get('custom_items', [])
    if idx is not None and 0 <= idx < len(custom_items):
        custom_items.pop(idx)
        session['custom_items'] = custom_items
    return redirect(url_for('items'))

@app.route('/first_aid', methods=['GET', 'POST'])
def first_aid():
    """急救包清單管理"""
    csv_path = str(Path(__file__).parent.parent / 'dataset' / 'first_aid_items.csv')
    items = []
    
    # Disaster type definitions
    disaster_types = {
        'Earthquake': {
            'icon': '🌍',
            'description': 'Earthquake emergency kit needs anti-seismic and protective supplies',
            'suggestions': [
                {'name': 'Safety Helmet', 'category': 'Protection', 'quantity': '1', 'description': 'Protect head safety'},
                {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'Lighting during power outage'},
                {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight and radio'},
                {'name': 'Radio', 'category': 'Communication', 'quantity': '1', 'description': 'Receive emergency broadcasts'},
                {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                {'name': 'Blanket', 'category': 'Warmth', 'quantity': '2', 'description': 'For warmth'},
                {'name': 'Drinking Water', 'category': 'Food & Water', 'quantity': '6', 'description': '3 liters per person per day'},
                {'name': 'Dry Food', 'category': 'Food & Water', 'quantity': '10', 'description': 'Biscuits, canned goods, etc.'},
                {'name': 'Wet Wipes', 'category': 'Hygiene', 'quantity': '2', 'description': 'For cleaning'},
                {'name': 'Whistle', 'category': 'Emergency', 'quantity': '1', 'description': 'Distress signal'},
            ]
        },
        'Flood': {
            'icon': '🌀',
            'description': 'Flood emergency kit needs waterproof and floating supplies',
            'suggestions': [
                {'name': 'Waterproof Bag', 'category': 'Waterproof', 'quantity': '2', 'description': 'Protect important items'},
                {'name': 'Life Jacket', 'category': 'Safety', 'quantity': '1', 'description': 'Prevent drowning'},
                {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'Night lighting'},
                {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight'},
                {'name': 'Radio', 'category': 'Communication', 'quantity': '1', 'description': 'Receive emergency broadcasts'},
                {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                {'name': 'Waterproof Cloth', 'category': 'Waterproof', 'quantity': '1', 'description': 'For rain protection'},
                {'name': 'Drinking Water', 'category': 'Food & Water', 'quantity': '6', 'description': '3 liters per person per day'},
                {'name': 'Dry Food', 'category': 'Food & Water', 'quantity': '10', 'description': 'Biscuits, canned goods, etc.'},
                {'name': 'Plastic Bags', 'category': 'Waterproof', 'quantity': '10', 'description': 'For storing items'},
            ]
        },
        'Fire': {
            'icon': '🔥',
            'description': 'Fire emergency kit needs fireproof and escape supplies',
            'suggestions': [
                {'name': 'Smoke Mask', 'category': 'Protection', 'quantity': '1', 'description': 'Prevent smoke inhalation'},
                {'name': 'Wet Towel', 'category': 'Protection', 'quantity': '2', 'description': 'Cover mouth and nose'},
                {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'For lighting'},
                {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight'},
                {'name': 'Whistle', 'category': 'Emergency', 'quantity': '1', 'description': 'Distress signal'},
                {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                {'name': 'Important Documents', 'category': 'Important', 'quantity': '1', 'description': 'ID, insurance, etc.'},
                {'name': 'Cash', 'category': 'Important', 'quantity': '1', 'description': 'Emergency money'},
                {'name': 'Phone Charger', 'category': 'Communication', 'quantity': '1', 'description': 'Keep communication'},
                {'name': 'Keys', 'category': 'Important', 'quantity': '1', 'description': 'For returning home'},
            ]
        },
        'Typhoon': {
            'icon': '🌪️',
            'description': 'Typhoon emergency kit needs windproof and waterproof supplies',
            'suggestions': [
                {'name': 'Raincoat', 'category': 'Waterproof', 'quantity': '1', 'description': 'For rain protection'},
                {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'Lighting during power outage'},
                {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight and radio'},
                {'name': 'Radio', 'category': 'Communication', 'quantity': '1', 'description': 'Receive typhoon information'},
                {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                {'name': 'Blanket', 'category': 'Warmth', 'quantity': '2', 'description': 'For warmth'},
                {'name': 'Drinking Water', 'category': 'Food & Water', 'quantity': '6', 'description': '3 liters per person per day'},
                {'name': 'Dry Food', 'category': 'Food & Water', 'quantity': '10', 'description': 'Biscuits, canned goods, etc.'},
                {'name': 'Plastic Bags', 'category': 'Waterproof', 'quantity': '10', 'description': 'For storing items'},
                {'name': 'Tape', 'category': 'Tools', 'quantity': '1', 'description': 'For securing items'},
            ]
        },
        'Landslide': {
            'icon': '⛰️',
            'description': 'Landslide emergency kit needs quick escape supplies',
            'suggestions': [
                {'name': 'Safety Helmet', 'category': 'Protection', 'quantity': '1', 'description': 'Protect head safety'},
                {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'Night lighting'},
                {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight'},
                {'name': 'Whistle', 'category': 'Emergency', 'quantity': '1', 'description': 'Distress signal'},
                {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                {'name': 'Drinking Water', 'category': 'Food & Water', 'quantity': '6', 'description': '3 liters per person per day'},
                {'name': 'Dry Food', 'category': 'Food & Water', 'quantity': '10', 'description': 'Biscuits, canned goods, etc.'},
                {'name': 'Important Documents', 'category': 'Important', 'quantity': '1', 'description': 'ID, insurance, etc.'},
                {'name': 'Cash', 'category': 'Important', 'quantity': '1', 'description': 'Emergency money'},
                {'name': 'Mobile Phone', 'category': 'Communication', 'quantity': '1', 'description': 'For emergency contact'},
            ]
        }
    }
    
    # 處理災害類型選擇
    selected_disaster = request.args.get('disaster', '')
    selected_suggestions = disaster_types.get(selected_disaster, {}).get('suggestions', [])
    
    # 新增物品
    if request.method == 'POST':
        # 檢查是否是批量新增
        batch_items = request.form.get('batch_items')
        if batch_items:
            try:
                import json
                items_data = json.loads(batch_items)
                import datetime
                created_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
                
                # 獲取建議清單以獲取正確的數量
                disaster_types = {
                    '地震': {
                        'suggestions': [
                            {'name': '安全帽', 'category': '防護用品', 'quantity': '1', 'description': '保護頭部安全'},
                            {'name': '手電筒', 'category': '照明用品', 'quantity': '2', 'description': '停電時照明'},
                            {'name': '電池', 'category': '電力用品', 'quantity': '10', 'description': '手電筒和收音機用'},
                            {'name': '收音機', 'category': '通訊用品', 'quantity': '1', 'description': '接收緊急廣播'},
                            {'name': '急救包', 'category': '醫療用品', 'quantity': '1', 'description': '基本急救用品'},
                            {'name': '毛毯', 'category': '保暖用品', 'quantity': '2', 'description': '保暖用'},
                            {'name': '飲用水', 'category': '食物飲水', 'quantity': '6', 'description': '每人每天3公升'},
                            {'name': '乾糧', 'category': '食物飲水', 'quantity': '10', 'description': '餅乾、罐頭等'},
                            {'name': '濕紙巾', 'category': '衛生用品', 'quantity': '2', 'description': '清潔用'},
                            {'name': '哨子', 'category': '求救用品', 'quantity': '1', 'description': '求救信號'},
                        ]
                    },
                    '洪水': {
                        'suggestions': [
                            {'name': '防水袋', 'category': '防水用品', 'quantity': '2', 'description': '保護重要物品'},
                            {'name': '救生衣', 'category': '安全用品', 'quantity': '1', 'description': '防止溺水'},
                            {'name': '手電筒', 'category': '照明用品', 'quantity': '2', 'description': '夜間照明'},
                            {'name': '電池', 'category': '電力用品', 'quantity': '10', 'description': '手電筒用'},
                            {'name': '收音機', 'category': '通訊用品', 'quantity': '1', 'description': '接收緊急廣播'},
                            {'name': '急救包', 'category': '醫療用品', 'quantity': '1', 'description': '基本急救用品'},
                            {'name': '防水布', 'category': '防水用品', 'quantity': '1', 'description': '遮雨用'},
                            {'name': '飲用水', 'category': '食物飲水', 'quantity': '6', 'description': '每人每天3公升'},
                            {'name': '乾糧', 'category': '食物飲水', 'quantity': '10', 'description': '餅乾、罐頭等'},
                            {'name': '塑膠袋', 'category': '防水用品', 'quantity': '10', 'description': '裝物品用'},
                        ]
                    },
                    '火災': {
                        'suggestions': [
                            {'name': '防煙面罩', 'category': '防護用品', 'quantity': '1', 'description': '防止吸入濃煙'},
                            {'name': '濕毛巾', 'category': '防護用品', 'quantity': '2', 'description': '捂住口鼻'},
                            {'name': '手電筒', 'category': '照明用品', 'quantity': '2', 'description': '照明用'},
                            {'name': '電池', 'category': '電力用品', 'quantity': '10', 'description': '手電筒用'},
                            {'name': '哨子', 'category': '求救用品', 'quantity': '1', 'description': '求救信號'},
                            {'name': '急救包', 'category': '醫療用品', 'quantity': '1', 'description': '基本急救用品'},
                            {'name': '重要文件', 'category': '重要物品', 'quantity': '1', 'description': '身份證、保險等'},
                            {'name': '現金', 'category': '重要物品', 'quantity': '1', 'description': '緊急用錢'},
                            {'name': '手機充電器', 'category': '通訊用品', 'quantity': '1', 'description': '保持通訊'},
                            {'name': '鑰匙', 'category': '重要物品', 'quantity': '1', 'description': '回家用'},
                        ]
                    },
                    '颱風': {
                        'suggestions': [
                            {'name': '雨衣', 'category': '防水用品', 'quantity': '1', 'description': '防雨用'},
                            {'name': '手電筒', 'category': '照明用品', 'quantity': '2', 'description': '停電時照明'},
                            {'name': '電池', 'category': '電力用品', 'quantity': '10', 'description': '手電筒和收音機用'},
                            {'name': '收音機', 'category': '通訊用品', 'quantity': '1', 'description': '接收颱風資訊'},
                            {'name': '急救包', 'category': '醫療用品', 'quantity': '1', 'description': '基本急救用品'},
                            {'name': '毛毯', 'category': '保暖用品', 'quantity': '2', 'description': '保暖用'},
                            {'name': '飲用水', 'category': '食物飲水', 'quantity': '6', 'description': '每人每天3公升'},
                            {'name': '乾糧', 'category': '食物飲水', 'quantity': '10', 'description': '餅乾、罐頭等'},
                            {'name': '塑膠袋', 'category': '防水用品', 'quantity': '10', 'description': '裝物品用'},
                            {'name': '膠帶', 'category': '工具用品', 'quantity': '1', 'description': '固定物品用'},
                        ]
                    },
                    '土石流': {
                        'suggestions': [
                            {'name': '安全帽', 'category': '防護用品', 'quantity': '1', 'description': '保護頭部安全'},
                            {'name': '手電筒', 'category': '照明用品', 'quantity': '2', 'description': '夜間照明'},
                            {'name': '電池', 'category': '電力用品', 'quantity': '10', 'description': '手電筒用'},
                            {'name': '哨子', 'category': '求救用品', 'quantity': '1', 'description': '求救信號'},
                            {'name': '急救包', 'category': '醫療用品', 'quantity': '1', 'description': '基本急救用品'},
                            {'name': '飲用水', 'category': '食物飲水', 'quantity': '6', 'description': '每人每天3公升'},
                            {'name': '乾糧', 'category': '食物飲水', 'quantity': '10', 'description': '餅乾、罐頭等'},
                            {'name': '重要文件', 'category': '重要物品', 'quantity': '1', 'description': '身份證、保險等'},
                            {'name': '現金', 'category': '重要物品', 'quantity': '1', 'description': '緊急用錢'},
                            {'name': '手機', 'category': '通訊用品', 'quantity': '1', 'description': '緊急聯絡用'},
                        ]
                    }
                }
                
                # 讀取現有物品以檢查重複
                existing_items = []
                if os.path.isfile(csv_path):
                    with open(csv_path, 'r', encoding='utf-8') as csvfile:
                        reader = csv.DictReader(csvfile)
                        existing_items = list(reader)
                
                # 為每個物品找到正確的數量並檢查重複
                for item_data in items_data:
                    # 檢查是否已存在相同名稱的物品
                    existing_item = None
                    for existing in existing_items:
                        if existing['name'] == item_data['name'] and existing['category'] == item_data['category']:
                            existing_item = existing
                            break
                    
                    if existing_item:
                        # 如果已存在，數量加1
                        current_quantity = int(existing_item.get('quantity', 0))
                        item_data['quantity'] = str(current_quantity + 1)
                        # 從現有物品列表中移除，避免重複添加
                        existing_items = [item for item in existing_items if not (item['name'] == item_data['name'] and item['category'] == item_data['category'])]
                    else:
                        # 如果不存在，在所有災害類型中查找該物品
                        for disaster_type, disaster_info in disaster_types.items():
                            for suggestion in disaster_info['suggestions']:
                                if suggestion['name'] == item_data['name'] and suggestion['category'] == item_data['category']:
                                    item_data['quantity'] = suggestion['quantity']
                                    break
                            else:
                                continue
                            break
                        else:
                            # 如果找不到，使用默認數量1
                            item_data['quantity'] = '1'
                
                # 準備最終的物品列表
                final_items = []
                
                # 添加現有的非重複物品
                final_items.extend(existing_items)
                
                # 添加新物品或更新重複物品
                for item_data in items_data:
                    # 檢查是否已存在相同名稱的物品
                    existing_item = None
                    for i, existing in enumerate(final_items):
                        if existing['name'] == item_data['name'] and existing['category'] == item_data['category']:
                            existing_item = existing
                            # 更新數量
                            final_items[i]['quantity'] = item_data['quantity']
                            break
                    
                    if not existing_item:
                        # 如果不存在，添加新物品
                        import uuid
                        item_id = str(uuid.uuid4())[:8]
                        final_items.append({
                            'id': item_id,
                            'name': item_data['name'],
                            'category': item_data['category'],
                            'quantity': item_data['quantity'],
                            'description': item_data['description'],
                            'created_at': created_at
                        })
                
                # 寫入所有物品
                with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=['id', 'name', 'category', 'quantity', 'description', 'created_at'])
                    writer.writeheader()
                    writer.writerows(final_items)
                
                # 計算新增和更新的物品數量
                new_items_count = 0
                updated_items_count = 0
                
                for item_data in items_data:
                    # 檢查是否已存在相同名稱的物品
                    existing_item = None
                    for existing in existing_items:
                        if existing['name'] == item_data['name'] and existing['category'] == item_data['category']:
                            existing_item = existing
                            break
                    
                    if existing_item:
                        updated_items_count += 1
                    else:
                        new_items_count += 1
                
                # 生成適當的成功訊息
                if new_items_count > 0 and updated_items_count > 0:
                    message = f'成功新增 {new_items_count} 個物品，更新 {updated_items_count} 個物品數量'
                elif new_items_count > 0:
                    message = f'成功新增 {new_items_count} 個物品'
                elif updated_items_count > 0:
                    message = f'成功更新 {updated_items_count} 個物品數量'
                else:
                    message = '操作完成'
                
                return jsonify({'success': True, 'message': message})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})
        
        # 單個物品新增
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        quantity = request.form.get('quantity', '1').strip()
        description = request.form.get('description', '').strip()
        
        if name and category and quantity:
            import datetime
            created_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            
            file_exists = os.path.isfile(csv_path)
            with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                if not file_exists:
                    writer.writerow(['id', 'name', 'category', 'quantity', 'description', 'created_at'])
                
                # 生成簡單的ID
                import uuid
                item_id = str(uuid.uuid4())[:8]
                writer.writerow([item_id, name, category, quantity, description, created_at])
        
        return redirect(url_for('first_aid', disaster=selected_disaster))
    
    # 讀取現有物品
    if os.path.isfile(csv_path):
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            items = list(reader)
    
    # 按分類組織物品
    items_by_category = {}
    total_items = len(items)
    total_quantity = 0
    categories_count = 0
    
    for item in items:
        category = item.get('category', '其他')
        if category not in items_by_category:
            items_by_category[category] = []
            categories_count += 1
        items_by_category[category].append(item)
        # 安全地處理數量字段，如果無法轉換為整數則使用默認值1
        try:
            quantity = int(item.get('quantity', 1))
        except (ValueError, TypeError):
            quantity = 1
        total_quantity += quantity
    
    return render_template('first_aid.html', 
                         items_by_category=items_by_category,
                         total_items=total_items,
                         total_quantity=total_quantity,
                         categories_count=categories_count,
                         disaster_types=disaster_types,
                         selected_disaster=selected_disaster,
                         selected_suggestions=selected_suggestions)

@app.route('/first_aid/delete', methods=['POST'])
def delete_first_aid_item():
    """刪除急救包物品"""
    item_id = request.form.get('id', '').strip()
    if not item_id:
        return redirect(url_for('first_aid'))
    
    csv_path = str(Path(__file__).parent.parent / 'dataset' / 'first_aid_items.csv')
    if os.path.isfile(csv_path):
        # 讀取所有物品
        items = []
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            items = list(reader)
        
        # 過濾掉要刪除的物品
        filtered_items = [item for item in items if item.get('id') != item_id]
        
        # 重新寫入檔案
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            if filtered_items:
                writer = csv.DictWriter(csvfile, fieldnames=['id', 'name', 'category', 'quantity', 'description', 'created_at'])
                writer.writeheader()
                writer.writerows(filtered_items)
            else:
                # 如果沒有物品了，只寫入標題
                writer = csv.writer(csvfile)
                writer.writerow(['id', 'name', 'category', 'quantity', 'description', 'created_at'])
    
    return redirect(url_for('first_aid'))

@app.route('/first_aid/delete_all', methods=['POST'])
def delete_all_first_aid_items():
    """刪除所有急救包物品"""
    csv_path = str(Path(__file__).parent.parent / 'dataset' / 'first_aid_items.csv')
    if os.path.isfile(csv_path):
        # 只保留標題行
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['id', 'name', 'category', 'quantity', 'description', 'created_at'])
    
    return redirect(url_for('first_aid'))

@app.route('/first_aid/delete_selected', methods=['POST'])
def delete_selected_first_aid_items():
    """刪除選中的急救包物品"""
    selected_ids = request.form.get('selected_ids', '').strip()
    if not selected_ids:
        return redirect(url_for('first_aid'))
    
    try:
        import json
        ids_to_delete = json.loads(selected_ids)
        
        csv_path = str(Path(__file__).parent.parent / 'dataset' / 'first_aid_items.csv')
        if os.path.isfile(csv_path):
            # 讀取所有物品
            items = []
            with open(csv_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                items = list(reader)
            
            # 過濾掉要刪除的物品
            filtered_items = [item for item in items if item.get('id') not in ids_to_delete]
            
            # 重新寫入檔案
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                if filtered_items:
                    writer = csv.DictWriter(csvfile, fieldnames=['id', 'name', 'category', 'quantity', 'description', 'created_at'])
                    writer.writeheader()
                    writer.writerows(filtered_items)
                else:
                    # 如果沒有物品了，只寫入標題
                    writer = csv.writer(csvfile)
                    writer.writerow(['id', 'name', 'category', 'quantity', 'description', 'created_at'])
        
        return jsonify({'success': True, 'message': f'成功刪除 {len(ids_to_delete)} 個物品'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/first_aid/preparation_status', methods=['POST'])
def get_preparation_status():
    """獲取智能準備狀況分析"""
    try:
        disaster_type = request.form.get('disaster_type', '').strip()
        if not disaster_type:
            return jsonify({'success': False, 'error': '未指定災害類型'})
        
        # Get suggested items list
        disaster_types = {
            'Earthquake': {
                'icon': '🌍',
                'description': 'Earthquake emergency kit needs anti-seismic and protective supplies',
                'suggestions': [
                    {'name': 'Safety Helmet', 'category': 'Protection', 'quantity': '1', 'description': 'Protect head safety'},
                    {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'Lighting during power outage'},
                    {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight and radio'},
                    {'name': 'Radio', 'category': 'Communication', 'quantity': '1', 'description': 'Receive emergency broadcasts'},
                    {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                    {'name': 'Blanket', 'category': 'Warmth', 'quantity': '2', 'description': 'For warmth'},
                    {'name': 'Drinking Water', 'category': 'Food & Water', 'quantity': '6', 'description': '3 liters per person per day'},
                    {'name': 'Dry Food', 'category': 'Food & Water', 'quantity': '10', 'description': 'Biscuits, canned goods, etc.'},
                    {'name': 'Wet Wipes', 'category': 'Hygiene', 'quantity': '2', 'description': 'For cleaning'},
                    {'name': 'Whistle', 'category': 'Emergency', 'quantity': '1', 'description': 'Distress signal'},
                ]
            },
            'Flood': {
                'icon': '🌀',
                'description': 'Flood emergency kit needs waterproof and floating supplies',
                'suggestions': [
                    {'name': 'Waterproof Bag', 'category': 'Waterproof', 'quantity': '2', 'description': 'Protect important items'},
                    {'name': 'Life Jacket', 'category': 'Safety', 'quantity': '1', 'description': 'Prevent drowning'},
                    {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'Night lighting'},
                    {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight'},
                    {'name': 'Radio', 'category': 'Communication', 'quantity': '1', 'description': 'Receive emergency broadcasts'},
                    {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                    {'name': 'Waterproof Cloth', 'category': 'Waterproof', 'quantity': '1', 'description': 'For rain protection'},
                    {'name': 'Drinking Water', 'category': 'Food & Water', 'quantity': '6', 'description': '3 liters per person per day'},
                    {'name': 'Dry Food', 'category': 'Food & Water', 'quantity': '10', 'description': 'Biscuits, canned goods, etc.'},
                    {'name': 'Plastic Bags', 'category': 'Waterproof', 'quantity': '10', 'description': 'For storing items'},
                ]
            },
            'Fire': {
                'icon': '🔥',
                'description': 'Fire emergency kit needs fireproof and escape supplies',
                'suggestions': [
                    {'name': 'Smoke Mask', 'category': 'Protection', 'quantity': '1', 'description': 'Prevent smoke inhalation'},
                    {'name': 'Wet Towel', 'category': 'Protection', 'quantity': '2', 'description': 'Cover mouth and nose'},
                    {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'For lighting'},
                    {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight'},
                    {'name': 'Whistle', 'category': 'Emergency', 'quantity': '1', 'description': 'Distress signal'},
                    {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                    {'name': 'Important Documents', 'category': 'Important', 'quantity': '1', 'description': 'ID, insurance, etc.'},
                    {'name': 'Cash', 'category': 'Important', 'quantity': '1', 'description': 'Emergency money'},
                    {'name': 'Phone Charger', 'category': 'Communication', 'quantity': '1', 'description': 'Keep communication'},
                    {'name': 'Keys', 'category': 'Important', 'quantity': '1', 'description': 'For returning home'},
                ]
            },
            'Typhoon': {
                'icon': '🌪️',
                'description': 'Typhoon emergency kit needs windproof and waterproof supplies',
                'suggestions': [
                    {'name': 'Raincoat', 'category': 'Waterproof', 'quantity': '1', 'description': 'For rain protection'},
                    {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'Lighting during power outage'},
                    {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight and radio'},
                    {'name': 'Radio', 'category': 'Communication', 'quantity': '1', 'description': 'Receive typhoon information'},
                    {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                    {'name': 'Blanket', 'category': 'Warmth', 'quantity': '2', 'description': 'For warmth'},
                    {'name': 'Drinking Water', 'category': 'Food & Water', 'quantity': '6', 'description': '3 liters per person per day'},
                    {'name': 'Dry Food', 'category': 'Food & Water', 'quantity': '10', 'description': 'Biscuits, canned goods, etc.'},
                    {'name': 'Plastic Bags', 'category': 'Waterproof', 'quantity': '10', 'description': 'For storing items'},
                    {'name': 'Tape', 'category': 'Tools', 'quantity': '1', 'description': 'For securing items'},
                ]
            },
            'Landslide': {
                'icon': '⛰️',
                'description': 'Landslide emergency kit needs quick escape supplies',
                'suggestions': [
                    {'name': 'Safety Helmet', 'category': 'Protection', 'quantity': '1', 'description': 'Protect head safety'},
                    {'name': 'Flashlight', 'category': 'Lighting', 'quantity': '2', 'description': 'Night lighting'},
                    {'name': 'Batteries', 'category': 'Power', 'quantity': '10', 'description': 'For flashlight'},
                    {'name': 'Whistle', 'category': 'Emergency', 'quantity': '1', 'description': 'Distress signal'},
                    {'name': 'First Aid Kit', 'category': 'Medical', 'quantity': '1', 'description': 'Basic first aid supplies'},
                    {'name': 'Drinking Water', 'category': 'Food & Water', 'quantity': '6', 'description': '3 liters per person per day'},
                    {'name': 'Dry Food', 'category': 'Food & Water', 'quantity': '10', 'description': 'Biscuits, canned goods, etc.'},
                    {'name': 'Important Documents', 'category': 'Important', 'quantity': '1', 'description': 'ID, insurance, etc.'},
                    {'name': 'Cash', 'category': 'Important', 'quantity': '1', 'description': 'Emergency money'},
                    {'name': 'Mobile Phone', 'category': 'Communication', 'quantity': '1', 'description': 'For emergency contact'},
                ]
            }
        }
        
        disaster_info = disaster_types.get(disaster_type)
        if not disaster_info:
            return jsonify({'success': False, 'error': '不支援的災害類型'})
        
        suggested_items = disaster_info['suggestions']
        
        # 讀取用戶現有的物品
        csv_path = str(Path(__file__).parent.parent / 'dataset' / 'first_aid_items.csv')
        user_items = []
        if os.path.isfile(csv_path):
            with open(csv_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                user_items = list(reader)
        
        # 分析準備狀況
        analysis = {
            'disaster_type': disaster_type,
            'disaster_icon': disaster_info['icon'],
            'total_suggested': len(suggested_items),
            'prepared_items': [],
            'missing_items': [],
            'insufficient_items': []
        }
        
        # 檢查每個建議物品
        for suggestion in suggested_items:
            suggestion_name = suggestion['name']
            suggestion_quantity = int(suggestion['quantity'])
            
            # 查找用戶是否有這個物品
            user_item = None
            for item in user_items:
                if item['name'] == suggestion_name:
                    user_item = item
                    break
            
            if user_item:
                user_quantity = int(user_item.get('quantity', 0))
                if user_quantity >= suggestion_quantity:
                    # 數量足夠
                    analysis['prepared_items'].append({
                        'name': suggestion_name,
                        'category': suggestion['category'],
                        'suggested_quantity': suggestion_quantity,
                        'user_quantity': user_quantity,
                        'description': suggestion['description']
                    })
                else:
                    # 數量不足
                    analysis['insufficient_items'].append({
                        'name': suggestion_name,
                        'category': suggestion['category'],
                        'suggested_quantity': suggestion_quantity,
                        'user_quantity': user_quantity,
                        'description': suggestion['description'],
                        'needed_more': suggestion_quantity - user_quantity
                    })
            else:
                # 完全缺少
                analysis['missing_items'].append({
                    'name': suggestion_name,
                    'category': suggestion['category'],
                    'suggested_quantity': suggestion_quantity,
                    'description': suggestion['description']
                })
        
        # 計算完成度
        total_prepared = len(analysis['prepared_items'])
        total_insufficient = len(analysis['insufficient_items'])
        total_missing = len(analysis['missing_items'])
        completion_percentage = round((total_prepared / analysis['total_suggested']) * 100)
        
        analysis['completion_percentage'] = completion_percentage
        analysis['total_prepared'] = total_prepared
        analysis['total_insufficient'] = total_insufficient
        analysis['total_missing'] = total_missing
        
        return jsonify({
            'success': True,
            'analysis': analysis
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/first_aid/update_quantity', methods=['POST'])
def update_item_quantity():
    """更新物品數量"""
    try:
        item_id = request.form.get('item_id', '').strip()
        quantity = request.form.get('quantity', '').strip()
        
        if not item_id or not quantity:
            return jsonify({'success': False, 'error': '缺少必要參數'})
        
        try:
            quantity = int(quantity)
            if quantity < 0:
                return jsonify({'success': False, 'error': '數量不能為負數'})
        except ValueError:
            return jsonify({'success': False, 'error': '數量必須是整數'})
        
        csv_path = str(Path(__file__).parent.parent / 'dataset' / 'first_aid_items.csv')
        if not os.path.isfile(csv_path):
            return jsonify({'success': False, 'error': '物品文件不存在'})
        
        # 讀取所有物品
        items = []
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            items = list(reader)
        
        # 查找並更新指定物品
        item_found = False
        for item in items:
            if item.get('id') == item_id:
                item['quantity'] = str(quantity)
                item_found = True
                break
        
        if not item_found:
            return jsonify({'success': False, 'error': '找不到指定物品'})
        
        # 重新寫入檔案
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=['id', 'name', 'category', 'quantity', 'description', 'created_at'])
            writer.writeheader()
            writer.writerows(items)
        
        return jsonify({'success': True, 'message': '數量更新成功'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_email_preview', methods=['POST'])
def get_email_preview():
    """獲取 Email 內容預覽"""
    try:
        # 取得目前經緯度與最近避難所
        user_location = session.get('user_location')
        latlng = ''
        nearest_shelter = ''
        nearest_distance = None
        
        if user_location:
            latlng = f"{user_location[0]:.5f},{user_location[1]:.5f}"
            db_path = str(Path(__file__).parent.parent / 'dataset' / 'shelters.db')
            df = load_shelter_data(db_path)
            emergency_disaster = session.get('emergency_disaster')
            if df is not None and emergency_disaster in df.columns:
                filtered_df = df[df[emergency_disaster] == 1].copy()
                if not filtered_df.empty:
                    filtered_df['distance'] = filtered_df.apply(lambda row: calculate_distance(user_location[0], user_location[1], row['latitude'], row['longitude']), axis=1)
                    nearest_row = filtered_df.sort_values('distance').iloc[0]
                    nearest_shelter = nearest_row['evaspot_name']
                    nearest_distance = nearest_row['distance']
        
        # 生成 Email 內容
        template = DEFAULT_EMAIL_TEMPLATES['emergency']
        subject = template['subject'].format(name='Contact', latlng=latlng, nearest_shelter=nearest_shelter)
        
        if nearest_distance is not None and nearest_distance > 10:
            message = "I am safe now. The nearest shelter is over 10km away, so no evacuation is needed for now."
        else:
            message = template['message'].format(name='Contact', latlng=latlng, nearest_shelter=nearest_shelter)
        
        return jsonify({
            'success': True,
            'subject': subject,
            'message': message
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })



@app.route('/send_emergency_notification', methods=['POST'])
def send_emergency_notification():
    """同時發送 Email 和簡訊"""
    try:
        csv_path = str(Path(__file__).parent.parent / 'dataset' / 'contacts.csv')
        contacts = []
        if os.path.isfile(csv_path):
            with open(csv_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                contacts = list(reader)
        
        if not contacts:
                    return jsonify({
            'success': False,
            'error': 'No contacts to notify'
        })
        
        # 取得目前經緯度與最近避難所
        user_location = session.get('user_location')
        latlng = ''
        nearest_shelter = ''
        nearest_distance = None
        
        if user_location:
            latlng = f"{user_location[0]:.5f},{user_location[1]:.5f}"
            db_path = str(Path(__file__).parent.parent / 'dataset' / 'shelters.db')
            df = load_shelter_data(db_path)
            emergency_disaster = session.get('emergency_disaster')
            if df is not None and emergency_disaster in df.columns:
                filtered_df = df[df[emergency_disaster] == 1].copy()
                if not filtered_df.empty:
                    filtered_df['distance'] = filtered_df.apply(lambda row: calculate_distance(user_location[0], user_location[1], row['latitude'], row['longitude']), axis=1)
                    nearest_row = filtered_df.sort_values('distance').iloc[0]
                    nearest_shelter = nearest_row['evaspot_name']
                    nearest_distance = nearest_row['distance']
        
        # 發送 Email
        template = DEFAULT_EMAIL_TEMPLATES['emergency']
        user_info = session.get('user_info')
        if user_info:
            email_service = create_email_service('user', user_info)
        else:
            email_service = create_email_service()
        
        email_results = []
        for contact in contacts:
            subject = template['subject'].format(name=contact['姓名'], latlng=latlng, nearest_shelter=nearest_shelter)
            if nearest_distance is not None and nearest_distance > 10:
                message = "I am safe now. The nearest shelter is over 10km away, so no evacuation is needed for now."
                html = '<html><body><p>I am safe now<br>The nearest shelter is over 10km away, so no evacuation is needed for now.</p></body></html>'
            else:
                message = template['message'].format(name=contact['姓名'], latlng=latlng, nearest_shelter=nearest_shelter)
                html = template['html'].format(name=contact['姓名'], latlng=latlng, nearest_shelter=nearest_shelter)
            
            result = email_service.send_email(contact['信箱'], subject, message, html)
            email_results.append(result)
        
        email_success_count = sum(1 for result in email_results if result['success'])
        email_failed_count = len(email_results) - email_success_count
        
        # 發送簡訊（模擬）
        sms_service = create_sms_service()
        message_template = DEFAULT_SMS_TEMPLATES['emergency']
        sms_results = sms_service.send_bulk_sms(contacts, message_template)
        
        sms_success_count = sum(1 for result in sms_results if result['success'])
        sms_failed_count = len(sms_results) - sms_success_count
        
        # 生成結果訊息
        if email_failed_count == 0:
            email_message = f"Successfully sent Email to {email_success_count} contacts"
        else:
            email_message = f"Email sending completed: {email_success_count} successful, {email_failed_count} failed"
        
        if sms_failed_count == 0:
            sms_message = f"Successfully sent SMS to {sms_success_count} contacts (simulation mode)"
        else:
            sms_message = f"SMS sending completed: {sms_success_count} successful, {sms_failed_count} failed (simulation mode)"
        
        return jsonify({
            'success': True,
            'email_message': email_message,
            'sms_message': sms_message
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

# --- 飲食卡功能 ---
def init_diet_database() -> None:
    """初始化飲食卡資料庫"""
    db_path = str(Path(__file__).parent.parent / 'dataset' / 'diet_card.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 創建基本資訊表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS diet_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            age INTEGER,
            blood_type TEXT,
            emergency_contact TEXT,
            emergency_phone TEXT,
            emergency_medication TEXT,
            medical_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 創建過敏食物表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS allergies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            food_name TEXT NOT NULL,
            severity TEXT NOT NULL,
            allergy_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 創建飲食偏好表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            food_name TEXT NOT NULL,
            preference_type TEXT NOT NULL,
            preference_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

@app.route('/diet_card', methods=['GET', 'POST'])
def diet_card() -> str:
    """飲食卡主頁面"""
    init_diet_database()
    
    db_path = str(Path(__file__).parent.parent / 'dataset' / 'diet_card.db')
    success_message = None
    error_message = None
    
    # 處理 POST 請求（基本資訊更新）
    if request.method == 'POST':
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 檢查是否已有記錄
            cursor.execute('SELECT * FROM diet_info ORDER BY id DESC LIMIT 1')
            existing_record = cursor.fetchone()
            
            if existing_record:
                # 獲取現有資料
                current_data = {
                    'name': existing_record[1] or '',
                    'age': existing_record[2] or '',
                    'blood_type': existing_record[3] or '',
                    'emergency_contact': existing_record[4] or '',
                    'emergency_phone': existing_record[5] or '',
                    'emergency_medication': existing_record[6] or '',
                    'medical_notes': existing_record[7] or ''
                }
                
                # 只更新有提交的欄位，保留其他欄位的現有值
                name = request.form.get('name', '').strip() or current_data['name']
                age = request.form.get('age', '').strip() or current_data['age']
                blood_type = request.form.get('blood_type', '').strip() or current_data['blood_type']
                emergency_contact = request.form.get('emergency_contact', '').strip() or current_data['emergency_contact']
                emergency_phone = request.form.get('emergency_phone', '').strip() or current_data['emergency_phone']
                emergency_medication = request.form.get('emergency_medication', '').strip() or current_data['emergency_medication']
                medical_notes = request.form.get('medical_notes', '').strip() or current_data['medical_notes']
                
                # 更新現有記錄
                cursor.execute('''
                    UPDATE diet_info SET 
                    name = ?, age = ?, blood_type = ?, emergency_contact = ?, 
                    emergency_phone = ?, emergency_medication = ?, medical_notes = ?, 
                    updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (name, age, blood_type, emergency_contact, emergency_phone, 
                     emergency_medication, medical_notes, existing_record[0]))
            else:
                # 創建新記錄
                name = request.form.get('name', '').strip()
                age = request.form.get('age', '').strip()
                blood_type = request.form.get('blood_type', '').strip()
                emergency_contact = request.form.get('emergency_contact', '').strip()
                emergency_phone = request.form.get('emergency_phone', '').strip()
                emergency_medication = request.form.get('emergency_medication', '').strip()
                medical_notes = request.form.get('medical_notes', '').strip()
                
                cursor.execute('''
                    INSERT INTO diet_info (name, age, blood_type, emergency_contact, 
                    emergency_phone, emergency_medication, medical_notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (name, age, blood_type, emergency_contact, emergency_phone, 
                     emergency_medication, medical_notes))
            
            conn.commit()
            conn.close()
            success_message = "資訊已成功儲存！"
            
        except Exception as e:
            error_message = f"儲存失敗：{str(e)}"
    
    # 查詢資料庫獲取最新資料
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 獲取基本資訊
    cursor.execute('SELECT * FROM diet_info ORDER BY id DESC LIMIT 1')
    diet_info_row = cursor.fetchone()
    
    diet_info = {}
    if diet_info_row:
        diet_info = {
            'id': diet_info_row[0],
            'name': diet_info_row[1],
            'age': diet_info_row[2],
            'blood_type': diet_info_row[3],
            'emergency_contact': diet_info_row[4],
            'emergency_phone': diet_info_row[5],
            'emergency_medication': diet_info_row[6],
            'medical_notes': diet_info_row[7]
        }
    
    # 獲取過敏食物
    cursor.execute('SELECT * FROM allergies ORDER BY created_at DESC')
    allergies_rows = cursor.fetchall()
    allergies = []
    for row in allergies_rows:
        allergies.append({
            'id': row[0],
            'food_name': row[1],
            'severity': row[2],
            'allergy_notes': row[3]
        })
    
    # 獲取飲食偏好
    cursor.execute('SELECT * FROM preferences ORDER BY created_at DESC')
    preferences_rows = cursor.fetchall()
    preferences = []
    for row in preferences_rows:
        preferences.append({
            'id': row[0],
            'food_name': row[1],
            'preference_type': row[2],
            'preference_notes': row[3]
        })
    
    conn.close()
    
    return render_template('diet_card.html', 
                         diet_info=diet_info, 
                         allergies=allergies, 
                         preferences=preferences,
                         success_message=success_message,
                         error_message=error_message)

@app.route('/diet_card/add_allergy', methods=['POST'])
def add_allergy() -> str:
    """新增過敏食物"""
    try:
        food_name = request.form.get('food_name', '').strip()
        severity = request.form.get('severity', '').strip()
        allergy_notes = request.form.get('allergy_notes', '').strip()
        
        if not food_name or not severity:
            return redirect(url_for('diet_card', error_message='請填寫過敏食物名稱和嚴重程度'))
        
        db_path = str(Path(__file__).parent.parent / 'dataset' / 'diet_card.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO allergies (food_name, severity, allergy_notes)
            VALUES (?, ?, ?)
        ''', (food_name, severity, allergy_notes))
        
        conn.commit()
        conn.close()
        
        return redirect(url_for('diet_card', success_message=f'已新增過敏食物：{food_name}'))
        
    except Exception as e:
        return redirect(url_for('diet_card', error_message=f'新增失敗：{str(e)}'))

@app.route('/diet_card/delete_allergy', methods=['POST'])
def delete_allergy() -> str:
    """刪除過敏食物"""
    try:
        allergy_id = request.form.get('allergy_id')
        
        if not allergy_id:
            return redirect(url_for('diet_card', error_message='缺少過敏食物ID'))
        
        db_path = str(Path(__file__).parent.parent / 'dataset' / 'diet_card.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM allergies WHERE id = ?', (allergy_id,))
        conn.commit()
        conn.close()
        
        return redirect(url_for('diet_card', success_message='過敏食物已刪除'))
        
    except Exception as e:
        return redirect(url_for('diet_card', error_message=f'刪除失敗：{str(e)}'))

@app.route('/diet_card/add_preference', methods=['POST'])
def add_preference() -> str:
    """新增飲食偏好"""
    try:
        food_name = request.form.get('food_name', '').strip()
        preference_type = request.form.get('preference_type', '').strip()
        preference_notes = request.form.get('preference_notes', '').strip()
        
        if not food_name or not preference_type:
            return redirect(url_for('diet_card', error_message='請填寫食物名稱和偏好類型'))
        
        db_path = str(Path(__file__).parent.parent / 'dataset' / 'diet_card.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO preferences (food_name, preference_type, preference_notes)
            VALUES (?, ?, ?)
        ''', (food_name, preference_type, preference_notes))
        
        conn.commit()
        conn.close()
        
        return redirect(url_for('diet_card', success_message=f'已新增飲食偏好：{food_name}'))
        
    except Exception as e:
        return redirect(url_for('diet_card', error_message=f'新增失敗：{str(e)}'))

@app.route('/diet_card/delete_preference', methods=['POST'])
def delete_preference() -> str:
    """刪除飲食偏好"""
    try:
        preference_id = request.form.get('preference_id')
        
        if not preference_id:
            return redirect(url_for('diet_card', error_message='缺少偏好ID'))
        
        db_path = str(Path(__file__).parent.parent / 'dataset' / 'diet_card.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM preferences WHERE id = ?', (preference_id,))
        conn.commit()
        conn.close()
        
        return redirect(url_for('diet_card', success_message='飲食偏好已刪除'))
        
    except Exception as e:
        return redirect(url_for('diet_card', error_message=f'刪除失敗：{str(e)}'))

if __name__ == '__main__':
    app.run(debug=True) 
