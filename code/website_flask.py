from flask import Flask, render_template_string, request, session, redirect, url_for
import pandas as pd
import folium
import os
import sqlite3
import math
import random
import osmnx as ox
import networkx as nx
from flask_session import Session

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../dataset/shelters.db'))

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

# --- Helper Functions ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def get_virtual_gps_location():
    if 'fukui_walk_nodes' not in session:
        G = ox.graph_from_point((36.0652, 136.2216), dist=4000, network_type='walk')
        session['fukui_walk_nodes'] = [(n, d['y'], d['x']) for n, d in G.nodes(data=True)]
    nodes = session['fukui_walk_nodes']
    node = random.choice(nodes)
    lat, lon = node[1], node[2]
    return lat, lon

def get_route_osmnx(start_lat, start_lon, end_lat, end_lon, dist=None, max_tries=4):
    # 根據起終點距離自動設置 dist，確保路網覆蓋起點和終點
    if dist is None:
        d = calculate_distance(start_lat, start_lon, end_lat, end_lon)
        dist = max(2000, int(d * 1200))  # 1km距離就設1200m，最小2000m
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

def load_shelter_data():
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM shelters", conn)
    conn.close()
    return df

@app.route('/', methods=['GET', 'POST'])
def index():
    df = load_shelter_data()
    required_columns = ['latitude', 'longitude', 'evaspot_name', 'evaspot_capacity', 'evaspot_kind_name']
    if not all(col in df.columns for col in required_columns + disaster_columns):
        return "<h2>Error: Missing required columns in database.</h2>"

    # 災害篩選
    if 'selected_disasters' not in session:
        session['selected_disasters'] = disaster_columns
    if 'emergency_mode' not in session:
        session['emergency_mode'] = False
    if 'user_location' not in session:
        session['user_location'] = None
    if 'emergency_disaster' not in session:
        session['emergency_disaster'] = None

    if request.method == 'POST':
        if 'toggle_emergency' in request.form:
            session['emergency_mode'] = not session['emergency_mode']
            if session['emergency_mode']:
                lat, lon = get_virtual_gps_location()
                session['user_location'] = (lat, lon)
                # 隨機選災害
                available_disasters = [d for d in disaster_columns if (df[d] == 1).any()]
                session['emergency_disaster'] = random.choice(available_disasters) if available_disasters else None
            else:
                session['user_location'] = None
                session['emergency_disaster'] = None
        elif 'locate_me' in request.form:
            # 模擬定位：福井市中心，只設定 user_location，不影響 emergency_mode
            session['user_location'] = (36.0652, 136.2216)
            # 不做其他動作
        elif 'select_disasters' in request.form:
            session['selected_disasters'] = request.form.getlist('disasters')

    selected_disasters = session.get('selected_disasters', disaster_columns)
    if not selected_disasters:
        selected_disasters = disaster_columns
    filter_condition = df[selected_disasters].sum(axis=1) > 0
    filtered_df = df[filter_condition].copy()

    # 地圖中心與地圖物件建立
    if session.get('emergency_mode') and session.get('user_location'):
        user_lat, user_lon = session['user_location']
        map_center = [user_lat, user_lon]
        zoom_level = 16
    else:
        map_center = [filtered_df['latitude'].mean(), filtered_df['longitude'].mean()]
        zoom_level = 12

    m = folium.Map(location=map_center, zoom_start=zoom_level)

    # Emergency mode 下畫 marker 與路徑
    if session.get('emergency_mode') and session.get('user_location'):
        # 只考慮對應 emergency_disaster 的避難所
        disaster = session.get('emergency_disaster')
        if disaster and disaster in disaster_columns:
            disaster_shelters = filtered_df[filtered_df[disaster] == 1]
        else:
            disaster_shelters = filtered_df
        # 最近的對應災害避難所
        distances = []
        for idx, row in disaster_shelters.iterrows():
            distance = calculate_distance(user_lat, user_lon, row['latitude'], row['longitude'])
            distances.append((distance, idx, row))
        distances.sort(key=lambda x: x[0])
        nearest_shelter = distances[0] if distances else None
        # 只顯示 disaster_shelters（有該災害標籤的避難所）
        for idx, row in disaster_shelters.iterrows():
            applicable_disasters = [d for d in disaster_columns if row[d] == 1]
            marker_color = 'blue'
            popup_html = f"""
            <b>📍 Name:</b> {row['evaspot_name']}<br>
            <b>👥 Capacity:</b> {row['evaspot_capacity']:,}<br>
            <b>🔰 Type:</b> {row['evaspot_kind_name']}<br>
            <b>⚠️ Applicable Disasters:</b> {', '.join(applicable_disasters)}<br>
            """
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=popup_html,
                tooltip=f"{row['evaspot_name']} ({', '.join(applicable_disasters)})",
                icon=folium.Icon(color=marker_color, icon='info-sign')
            ).add_to(m)
        # 畫最近的對應災害避難所 marker（紅色）和路徑
        if nearest_shelter:
            _, idx, row = nearest_shelter
            route_coords = get_route_osmnx(user_lat, user_lon, row['latitude'], row['longitude'])
            if route_coords:
                folium.PolyLine(
                    locations=route_coords,
                    color='red', weight=4, opacity=0.8,
                    popup=f"Route to {row['evaspot_name']}"
                ).add_to(m)
            applicable_disasters = [d for d in disaster_columns if row[d] == 1]
            popup_html = f"""
            <b>📍 Name:</b> {row['evaspot_name']}<br>
            <b>👥 Capacity:</b> {row['evaspot_capacity']:,}<br>
            <b>🔰 Type:</b> {row['evaspot_kind_name']}<br>
            <b>⚠️ Applicable Disasters:</b> {', '.join(applicable_disasters)}<br>
            <b>📏 Distance from you:</b> {calculate_distance(user_lat, user_lon, row['latitude'], row['longitude']):.2f} km<br>
            """
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=popup_html,
                tooltip=f"{row['evaspot_name']} ({', '.join(applicable_disasters)})",
                icon=folium.Icon(color='red', icon='info-sign')
            ).add_to(m)
        # 用戶位置 marker
        folium.Marker(
            location=[user_lat, user_lon],
            popup="🧑 Your Current Location",
            tooltip="Your Location",
            icon=folium.Icon(color='green', icon='user', prefix='fa')
        ).add_to(m)
    # 準備 info 區塊資料
    if session.get('emergency_mode') and session.get('user_location') and nearest_shelter:
        _, _, target_row = nearest_shelter
        target_info = {
            'name': target_row['evaspot_name'],
            'capacity': target_row['evaspot_capacity'],
            'kind': target_row['evaspot_kind_name'],
            'lat': target_row['latitude'],
            'lon': target_row['longitude'],
            'distance': calculate_distance(user_lat, user_lon, target_row['latitude'], target_row['longitude']),
            'disasters': [d for d in disaster_columns if target_row[d] == 1]
        }
    else:
        target_info = None

    map_html = m._repr_html_()

    # HTML模板（簡化版）
    html = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Evacuation Shelter Map</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f6f8fb; }
            .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
            .sidebar {
                float: left;
                width: 250px;
                background: linear-gradient(135deg, #e3f0ff 0%, #c8e0ff 100%);
                padding: 24px 18px 18px 18px;
                border-radius: 32px;
                margin-right: 28px;
                box-shadow: 0 8px 32px 0 rgba(80,120,200,0.13), 0 2px 8px 0 rgba(0,0,0,0.06);
                border: 1.5px solid #d0e3fa;
                min-height: 540px;
                position: relative;
            }
            .main {
                margin-left: 278px;
                padding-left: 8px;
                max-width: calc(100% - 290px);
            }
            .sidebar h2 {ㄋㄋ
                font-size: 1.3em;
                font-weight: 900;
                margin-bottom: 20px;
                letter-spacing: 0.5px;
                color: #1a2a4a;
                text-shadow: 0 2px 8px rgba(80,120,200,0.07);
            }
            .form-group label, .sidebar label {
                font-size: 1em;
                font-weight: 500;
                color: #1a2a4a;
                margin-bottom: 8px;
                display: inline-block;
                cursor: pointer;
            }
            .form-group input[type="checkbox"] {
                margin-right: 12px;
                transform: scale(1.35);
                accent-color: #5499ff;
                vertical-align: middle;
            }
            .btn {
                padding: 12px 28px;
                border: none;
                border-radius: 999px;
                background: linear-gradient(90deg, #5499ff 0%, #6ec6ff 100%);
                color: white;
                cursor: pointer;
                font-size: 1.1em;
                font-weight: 700;
                margin-bottom: 14px;
                transition: background 0.2s, box-shadow 0.2s;
                box-shadow: 0 2px 8px rgba(80,120,200,0.10);
            }
            .btn:hover {
                background: linear-gradient(90deg, #357ae8 0%, #4fc3f7 100%);
                box-shadow: 0 4px 16px rgba(80,120,200,0.18);
            }
            .btn-danger {
                background: linear-gradient(90deg, #ff6b6b 0%, #ffb199 100%);
                color: #fff;
            }
            .btn-danger:hover {
                background: linear-gradient(90deg, #e14a4a 0%, #ffb199 100%);
            }
            .btn-secondary {
                background: #aaa;
            }
            .btn-real-locate {
                background: linear-gradient(90deg, #43e97b 0%, #38f9d7 100%);
                color: #fff;
            }
            .btn-real-locate:hover {
                background: linear-gradient(90deg, #38f9d7 0%, #43e97b 100%);
            }
            .sidebar hr {
                border: none;
                border-top: 2px solid rgba(80,120,200,0.13);
                margin: 24px 0 18px 0;
            }
            .sidebar .current-disaster {
                margin-top: 18px;
                font-size: 1em;
                font-weight: 600;
                color: #fff;
                background: linear-gradient(90deg, #ffb347 0%, #ff6b6b 100%);
                border-radius: 12px;
                padding: 10px 16px;
                box-shadow: 0 2px 8px rgba(255,107,107,0.10);
                display: inline-block;
            }
            .sidebar .current-location {
                margin-top: 10px;
                font-size: 0.98em;
                font-weight: 500;
                color: #1a2a4a;
                background: #e3f7e3;
                border-radius: 8px;
                padding: 6px 12px;
                display: block;
                margin-bottom: 22px;
            }
        </style>
        <script>
        function realLocate() {
            if (!navigator.geolocation) {
                alert('Geolocation is not supported by your browser.');
                return;
            }
            navigator.geolocation.getCurrentPosition(function(position) {
                fetch('/set_location', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        lat: position.coords.latitude,
                        lon: position.coords.longitude
                    })
                }).then(response => {
                    response.text().then(txt => { console.log('set_location response:', txt); });
                    if (response.ok) {
                        setTimeout(() => { window.location.reload(); }, 300);
                    } else {
                        alert('Failed to set location.');
                    }
                });
            }, function(error) {
                alert('Unable to retrieve your location.');
            });
        }
        </script>
    </head>
    <body>
    <div class="container">
        <div class="sidebar">
            <form method="post" style="margin-bottom: 16px;">
                <button class="btn btn-danger" name="toggle_emergency" type="submit" style="margin-bottom: 0; width:100%;">{{ 'Deactivate' if emergency_mode else 'Activate' }} Emergency Mode</button>
            </form>
            {% if emergency_disaster %}
            <div class="current-disaster" style="margin-bottom: 18px;"><b>Current Disaster:</b> {{emergency_disaster}}</div>
            {% endif %}
            {% if emergency_mode and target_info %}
            <div style="background: #fffbe6; border: 1.5px solid #ffe58f; border-radius: 14px; padding: 14px 14px 10px 14px; margin-bottom: 18px;">
                <div style="font-size:1.08em;font-weight:700;margin-bottom:6px;">🚩 路徑規劃資訊</div>
                <div><b>目前位置：</b>{{user_location[0]|round(4)}}, {{user_location[1]|round(4)}}</div>
                <div><b>目的避難所：</b>{{target_info.name}}</div>
                <div><b>容量：</b>{{target_info.capacity}}</div>
                <div><b>類型：</b>{{target_info.kind}}</div>
                <div><b>適用災害：</b>{{target_info.disasters|join(', ')}}</div>
                <div><b>距離：</b>{{target_info.distance|round(2)}} km</div>
            </div>
            {% else %}
            <h2>Disaster Type Filter</h2>
            <form method="post">
                <div class="form-group">
                    {% for d in disaster_columns %}
                        <input type="checkbox" name="disasters" value="{{d}}" {% if d in selected_disasters %}checked{% endif %}> <label>{{d}}</label><br>
                    {% endfor %}
                </div>
                <button class="btn" name="select_disasters" type="submit" style="margin-top: 10px; width:100%;">Apply Filter</button>
            </form>
            {% endif %}
            <hr>
            <form method="post" style="margin-bottom: 10px;">
                <button class="btn btn-secondary" name="locate_me" type="submit" style="width:100%;">📍 定位目前位置（模擬）</button>
            </form>
            <button class="btn btn-real-locate" type="button" style="width:100%;margin-bottom:10px;" onclick="realLocate()">📡 真實定位（Real）</button>
            {% if user_location %}
            <div class="current-location">
                <b>Current Location:</b><br>
                {{user_location[0]|round(4)}}, {{user_location[1]|round(4)}}
            </div>
            {% endif %}
        </div>
        <div class="main">
            <h1>Evacuation Shelter Map</h1>
            <div style="display: flex; gap: 30px; align-items: center; margin-bottom: 10px;">
                <div style="background-color: #f0f2f6; border-radius: 8px; padding: 10px 20px; text-align: center;">
                    <span style="color: #5499ff; font-weight: bold; font-size: 1.3em;">🏠 Total Shelters:</span>
                    <span style="color: #5499ff; font-size: 2.2em; font-weight: bold;">{{filtered_df|length}}</span>
                </div>
                <div style="background-color: #f0f2f6; border-radius: 8px; padding: 10px 20px; text-align: center;">
                    <span style="color: #ff7f0e; font-weight: bold; font-size: 1.3em;">👥 Total Capacity:</span>
                    <span style="color: #ff7f0e; font-size: 2.2em; font-weight: bold;">{{total_capacity}}</span>
                </div>
            </div>
            <div style="width:95%;max-width:95%;">{{map_html|safe}}</div>
            {% if emergency_mode and target_info %}
            <div style="background: #fffbe6; border: 1.5px solid #ffe58f; border-radius: 14px; padding: 18px 24px; margin-bottom: 18px; max-width: 600px;">
                <div style="font-size:1.15em;font-weight:700;margin-bottom:6px;">🚩 路徑規劃資訊</div>
                <div><b>目前位置：</b>{{user_location[0]|round(4)}}, {{user_location[1]|round(4)}}</div>
                <div><b>目的避難所：</b>{{target_info.name}}</div>
                <div><b>容量：</b>{{target_info.capacity}}</div>
                <div><b>類型：</b>{{target_info.kind}}</div>
                <div><b>適用災害：</b>{{target_info.disasters|join(', ')}}</div>
                <div><b>距離：</b>{{target_info.distance|round(2)}} km</div>
            </div>
            {% endif %}
            <!-- 移除 Filtered Data Table 及表格 -->
            <div style="margin: 24px auto 0 auto; text-align: center; color: #8a99b3; font-size: 0.95em; letter-spacing: 0.2px; background: #f6f8fb; padding: 10px 0 6px 0; border-radius: 8px; max-width: 480px;">
                © 2025 Evacuation System<br>For demo only
            </div>
        </div>
    </div>
    </body>
    </html>
    '''
    total_capacity = int(filtered_df['evaspot_capacity'].fillna(0).sum())
    return render_template_string(
        html,
        disaster_columns=disaster_columns,
        selected_disasters=selected_disasters,
        emergency_mode=session.get('emergency_mode'),
        user_location=session.get('user_location'),
        emergency_disaster=session.get('emergency_disaster'),
        map_html=map_html,
        filtered_df=filtered_df,
        total_capacity=total_capacity,
        target_info=target_info,
    )

# 在 index() 之後新增一個新路由
@app.route('/set_location', methods=['POST'])
def set_location():
    data = request.get_json()
    lat = data.get('lat')
    lon = data.get('lon')
    if lat is not None and lon is not None:
        session['user_location'] = (lat, lon)
        # 只設定 user_location，不影響 emergency_mode
        print('Set user_location to:', session['user_location'])
        return 'OK', 200
    return 'Invalid', 400

if __name__ == '__main__':
    app.run(debug=True) 