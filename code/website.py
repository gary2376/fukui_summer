import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import os
import sqlite3
import math
import random
import time
import osmnx as ox
import networkx as nx

# --- Helper Functions ---
def calculate_distance(lat1, lon1, lat2, lon2):
    """計算兩點間的距離 (Haversine公式)"""
    R = 6371  # 地球半徑 (公里)
    
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def find_nearest_shelter(user_lat, user_lon, shelters_df):
    """找到最近的避難所"""
    distances = []
    for idx, row in shelters_df.iterrows():
        distance = calculate_distance(user_lat, user_lon, row['latitude'], row['longitude'])
        distances.append((distance, idx, row))
    
    distances.sort(key=lambda x: x[0])
    return distances[0] if distances else None

def get_virtual_gps_location():
    """取得福井市步行路網上的隨機節點座標"""
    # 只抓一次，存在 session_state
    if 'fukui_walk_nodes' not in st.session_state:
        # 福井市中心附近
        G = ox.graph_from_point((36.0652, 136.2216), dist=4000, network_type='walk')
        st.session_state['fukui_walk_nodes'] = list(G.nodes(data=True))
    nodes = st.session_state['fukui_walk_nodes']
    node = random.choice(nodes)
    lat, lon = node[1]['y'], node[1]['x']
    return lat, lon

def get_route_osmnx(start_lat, start_lon, end_lat, end_lon, dist=1500, max_tries=3):
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
            dist *= 2  # 擴大搜尋範圍
    return None  # 找不到路徑

# --- 1. Set Page Title ---
st.set_page_config(page_title="Evacuation Shelter Map", layout="wide")
# 主標題縮小
st.markdown("""
<style>
.big-title {
    font-size: 1.8em !important;
    font-weight: 700;
    margin-bottom: 0.2em;
}
.sub-title {
    font-size: 1.1em !important;
    font-weight: 500;
    margin-bottom: 0.5em;
}
</style>
""", unsafe_allow_html=True)
st.markdown('<div class="big-title">🗺️ Evacuation Shelter Map | Emergency Shelter Location System</div>', unsafe_allow_html=True)

# --- 2. Database File Path ---
db_path = r'/Users/gary/Documents/project/fukui_summer/dataset/shelters.db'

# --- 3. Define Disaster Types ---
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

# --- 4. Load Data with Cache ---
@st.cache_data
def load_shelter_data(db_path):
    """Load shelter data and preprocessing"""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM shelters", conn)
    conn.close()
    
    return df

if os.path.exists(db_path):
    try:
        # Load data with cache
        df = load_shelter_data(db_path)
        
        required_columns = ['latitude', 'longitude', 'evaspot_name', 'evaspot_capacity', 'evaspot_kind_name']
        disaster_columns = ['内水氾濫', '土石流', '地震', '大規模な火事', '崖崩れ・地滑り', '津波', '洪水', '高潮']
        
        if not all(col in df.columns for col in required_columns + disaster_columns):
            st.error(f"Error: Missing required columns in CSV file.")
        else:
            # --- Sidebar Disaster Type Filter ---
            with st.sidebar:
                # Add custom CSS styles
                st.markdown("""
                <style>
                .sidebar-header {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 12px;
                    border-radius: 8px;
                    margin: -12px -12px 12px -12px;
                    text-align: center;
                }
                .sidebar-header h1 {
                    color: white;
                    margin: 0;
                    font-size: 18px;
                    text-shadow: 1px 1px 2px rgba(0,0,0,0.2);
                }
                .disaster-section {
                    background-color: #f8f9fa;
                    padding: 10px;
                    border-radius: 6px;
                    margin: 6px 0;
                    border-left: 3px solid #667eea;
                }
                .disaster-category {
                    margin: 5px 0;
                    padding: 5px;
                    border-radius: 4px;
                    background-color: white;
                    border: 1px solid #e9ecef;
                    transition: all 0.3s ease;
                    font-size: 14px;
                }
                .disaster-category:hover {
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                    border-color: #667eea;
                }
                .info-box {
                    background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
                    padding: 10px;
                    border-radius: 6px;
                    margin: 10px 0;
                    text-align: center;
                    border: 1px solid #ffc107;
                    font-size: 14px;
                }
                @keyframes blink {
                    0% { opacity: 1; }
                    50% { opacity: 0.3; }
                    100% { opacity: 1; }
                }
                .emergency-alert-strong {
                    animation: blink 1s infinite;
                    background: linear-gradient(135deg, #ff3b3b 0%, #ffb347 100%);
                    color: #fff;
                    padding: 12px 8px 10px 8px;
                    border-radius: 10px;
                    margin: 8px 0 10px 0;
                    text-align: center;
                    font-size: 1em;
                    font-weight: bold;
                    box-shadow: 0 0 8px 1px #ffb3b3;
                    border: 2px solid #fff;
                }
                .emergency-alert-strong .icon {
                    font-size: 1.2em !important;
                }
                .current-disaster-icon {
                    font-size: 1em !important;
                }
                </style>
                """, unsafe_allow_html=True)
                
                # --- Emergency Alert System ---
                if 'emergency_mode' not in st.session_state:
                    st.session_state.emergency_mode = False
                if 'user_location' not in st.session_state:
                    st.session_state.user_location = None
                
                # Emergency alert toggle
                emergency_alert = st.toggle("🚨 Activate Emergency Mode", value=st.session_state.emergency_mode)
                
                # 啟動 Emergency Mode 時自動產生 user_location 並隨機選災害
                if emergency_alert:
                    st.session_state.emergency_mode = True
                    if not st.session_state.user_location:
                        user_lat, user_lon = get_virtual_gps_location()
                        st.session_state.user_location = (user_lat, user_lon)
                    # 隨機選擇一種有對應避難所的災害
                    if 'emergency_disaster' not in st.session_state or st.session_state.emergency_disaster is None:
                        available_disasters = []
                        for d_col in disaster_columns:
                            if (df[d_col] == 1).any():
                                available_disasters.append(d_col)
                        if available_disasters:
                            chosen_disaster = random.choice(available_disasters)
                            st.session_state.emergency_disaster = chosen_disaster
                        else:
                            st.session_state.emergency_disaster = None
                    # --- 警報與重要諮詢移到最上方 ---
                    st.markdown("""
                    <div class="emergency-alert-strong">
                        <span class='icon'>🚨</span><br>
                        <span style='font-size:1.1em;'>EMERGENCY ALERT</span><br>
                        <span style='font-size:1em;'>災害警報已啟動</span>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # --- 當前災害種類顯示 ---
                    if 'emergency_disaster' in st.session_state and st.session_state.emergency_disaster:
                        disaster_name = [k for k, v in disaster_types.items() if v == st.session_state.emergency_disaster or k == st.session_state.emergency_disaster]
                        disaster_name = disaster_name[0] if disaster_name else st.session_state.emergency_disaster
                        st.markdown(f"""
                        <div style='background-color:#ffb347; color:#212529; padding:8px; border-radius:8px; margin:8px 0; text-align:center;'>
                        <span class='current-disaster-icon'>🚨</span> <strong>Current Disaster: {disaster_name}</strong>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    # --- 當前位置顯示 ---
                    if st.session_state.user_location:
                        lat, lon = st.session_state.user_location
                        st.markdown(f"""
                        <div style="background-color: #28a745; color: white; padding: 8px; border-radius: 5px; margin: 5px 0; font-size: 0.95em;">
                            <span class='current-disaster-icon'>📍</span> <strong>Current Location:</strong><br>
                            Lat: {lat:.4f}, Lon: {lon:.4f}
                        </div>
                        """, unsafe_allow_html=True)
                        if st.button("🗑️ Clear Location", use_container_width=True):
                            st.session_state.user_location = None
                            st.rerun()
                    
                    # --- 災害類型選擇區塊 ---
                    st.markdown("""
                    <div class="sidebar-header">
                        <h1>🔍 Disaster Type Filter</h1>
                    </div>
                    """, unsafe_allow_html=True)
                    st.markdown('<div class="disaster-section">', unsafe_allow_html=True)
                    st.markdown("**🌪️ Select Disaster Types:**")
                    
                    # Define disaster type emoji icons
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
                    
                    selected_disasters = []
                    
                    # Group display disaster types
                    col1, col2 = st.columns(2)
                    disaster_list = list(disaster_types.keys())
                    
                    for i, (disaster_name, disaster_col) in enumerate(zip(disaster_types.keys(), disaster_columns)):
                        icon = disaster_icons.get(disaster_name, '⚠️')
                        display_name = f"{icon} {disaster_name}"
                        
                        if i % 2 == 0:
                            with col1:
                                if st.checkbox(display_name, value=True, key=disaster_col):
                                    selected_disasters.append(disaster_col)
                        else:
                            with col2:
                                if st.checkbox(display_name, value=True, key=disaster_col):
                                    selected_disasters.append(disaster_col)
                    
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                    # Quick selection buttons
                    st.markdown("**⚡ Quick Selection:**")
                    col_btn1, col_btn2 = st.columns(2)
                    
                    with col_btn1:
                        if st.button("🔴 Clear All", use_container_width=True):
                            st.rerun()
                    
                    with col_btn2:
                        if st.button("🟢 Select All", use_container_width=True):
                            # Need to reload page to select all
                            st.info("Please manually check all options")
                    
                    # Display current selection statistics
                    if selected_disasters:
                        st.markdown(f"""
                        <div style="background-color: #d4edda; color: #155724; padding: 10px; border-radius: 5px; margin: 10px 0; border: 1px solid #c3e6cb;">
                            <strong>✅ Selected {len(selected_disasters)} disaster types</strong>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style="background-color: #f8d7da; color: #721c24; padding: 10px; border-radius: 5px; margin: 10px 0; border: 1px solid #f5c6cb;">
                            <strong>⚠️ Please select at least one disaster type</strong>
                        </div>
                        """, unsafe_allow_html=True)
                        selected_disasters = disaster_columns  # If none selected, show all
                    
                    # Add separator line
                    st.markdown("---")
                else:
                    st.session_state.emergency_mode = False
                    st.session_state.user_location = None
                    st.session_state.emergency_disaster = None
                    # --- 非緊急模式下恢復原本 sidebar 順序與內容 ---
                    st.markdown("""
                    <div class="sidebar-header">
                        <h1>🔍 Disaster Type Filter</h1>
                    </div>
                    """, unsafe_allow_html=True)
                    st.markdown("""
                    <div class="info-box">
                        <strong>📋 Filter Instructions</strong><br>
                        Please select the disaster types you want to view. The map will update in real-time to show corresponding shelter locations.
                    </div>
                    """, unsafe_allow_html=True)
                    st.markdown('<div class="disaster-section">', unsafe_allow_html=True)
                    st.markdown("**🌪️ Select Disaster Types:**")
                    
                    # Define disaster type emoji icons
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
                    
                    selected_disasters = []
                    
                    # Group display disaster types
                    col1, col2 = st.columns(2)
                    disaster_list = list(disaster_types.keys())
                    
                    for i, (disaster_name, disaster_col) in enumerate(zip(disaster_types.keys(), disaster_columns)):
                        icon = disaster_icons.get(disaster_name, '⚠️')
                        display_name = f"{icon} {disaster_name}"
                        
                        if i % 2 == 0:
                            with col1:
                                if st.checkbox(display_name, value=True, key=disaster_col):
                                    selected_disasters.append(disaster_col)
                        else:
                            with col2:
                                if st.checkbox(display_name, value=True, key=disaster_col):
                                    selected_disasters.append(disaster_col)
                    
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                    # Quick selection buttons
                    st.markdown("**⚡ Quick Selection:**")
                    col_btn1, col_btn2 = st.columns(2)
                    
                    with col_btn1:
                        if st.button("🔴 Clear All", use_container_width=True):
                            st.rerun()
                    
                    with col_btn2:
                        if st.button("🟢 Select All", use_container_width=True):
                            # Need to reload page to select all
                            st.info("Please manually check all options")
                    
                    # Display current selection statistics
                    if selected_disasters:
                        st.markdown(f"""
                        <div style="background-color: #d4edda; color: #155724; padding: 10px; border-radius: 5px; margin: 10px 0; border: 1px solid #c3e6cb;">
                            <strong>✅ Selected {len(selected_disasters)} disaster types</strong>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style="background-color: #f8d7da; color: #721c24; padding: 10px; border-radius: 5px; margin: 10px 0; border: 1px solid #f5c6cb;">
                            <strong>⚠️ Please select at least one disaster type</strong>
                        </div>
                        """, unsafe_allow_html=True)
                        selected_disasters = disaster_columns  # If none selected, show all
                    
                    # Add separator line
                    st.markdown("---")
                
                # Sidebar footer
                st.markdown("""
                <div style="background: linear-gradient(135deg, #5499ff 0%, #5499ff 100%); padding: 15px; border-radius: 8px; margin: 15px 0; text-align: center;">
                    <h4 style="color: white; margin: 0; font-size: 16px;">📊 Application Info</h4>
                    <p style="color: #f8f9fa; margin: 5px 0; font-size: 12px;">Emergency Shelter Map System</p>
                    <p style="color: #f8f9fa; margin: 0; font-size: 10px;">© 2025 Evacuation System</p>
                </div>
                """, unsafe_allow_html=True)
                
                # Usage instructions
                with st.expander("ℹ️ Usage Instructions"):
                    st.markdown("""
                    **How to use this system:**
                    
                    1. 🎯 **Select Disaster Types**: Check the disaster types you're interested in above
                    2. 🗺️ **View Map**: The map will automatically update to show relevant shelters
                    3. 📍 **Click Markers**: Click on map markers to view detailed information
                    4. 📊 **View Statistics**: Main page shows shelter count and capacity
                    5. 📋 **View Table**: Expand data table to view detailed information
                    
                    **🚨 Emergency Mode Features:**
                    
                    6. 🚨 **Activate Emergency Mode**: Toggle the emergency alert in the sidebar
                    7. 📍 **Get Location**: Click "Get Current Location" to simulate GPS positioning
                    8. 🧭 **View Route**: The system will automatically show the route to the nearest shelter
                    9. 📏 **Distance Info**: All shelter markers will show distance from your location
                    10. 🏃‍♂️ **Emergency Route**: Red line shows the optimal evacuation route
                    
                    **Color Legend:**
                    - Each disaster type has its own designated color
                    - 🟢 Green marker: Your current location (in emergency mode)
                    - 🔴 Red marker: Nearest shelter (in emergency mode)
                    - Red line: Evacuation route to nearest shelter
                    """)
                
                # Emergency contact information
                st.markdown("""
                <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; border-left: 4px solid #fdcb6e; padding: 10px; border-radius: 5px; margin: 10px 0;">
                    <strong>🚨 Emergency Contact</strong><br>
                    <small>In case of emergency, please immediately call your local emergency rescue number</small>
                </div>
                """, unsafe_allow_html=True)
            
            # --- Filter data based on selected disaster types ---
            if selected_disasters:
                # Create filter condition: at least one selected disaster type matches
                filter_condition = df[selected_disasters].sum(axis=1) > 0
                filtered_df = df[filter_condition].copy()
            else:
                filtered_df = df.copy()
            
            if not filtered_df.empty:
                # --- 緊急模式下隱藏主頁統計卡片 ---
                if not (st.session_state.emergency_mode and st.session_state.user_location):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"""
                        <div style="text-align: center; padding: 10px; background-color: #f0f2f6; border-radius: 8px;">
                            <h3 style="color: #5499ff; margin: 0;">🏠 Total Shelters</h3>
                            <h1 style="color: #5499ff; margin: 5px 0; font-size: 1.6em;">{len(filtered_df)}</h1>
                        </div>
                        """, unsafe_allow_html=True)
                    with col2:
                        total_capacity = filtered_df['evaspot_capacity'].fillna(0).sum()
                        st.markdown(f"""
                        <div style="text-align: center; padding: 10px; background-color: #f0f2f6; border-radius: 10px;">
                            <h3 style="color: #ff7f0e; margin: 0;">👥 Total Capacity</h3>
                            <h1 style="color: #ff7f0e; margin: 5px 0; font-size: 1.6em;">{total_capacity:,.0f}</h1>
                        </div>
                        """, unsafe_allow_html=True)
                
                
                # --- Emergency Mode: Adjust map center if user location is available ---
                if st.session_state.emergency_mode and st.session_state.user_location:
                    user_lat, user_lon = st.session_state.user_location
                    map_center = [user_lat, user_lon]
                    zoom_level = 16  # 放大地圖，清楚顯示路線

                    # 只顯示最近的5個避難所
                    distances = []
                    for idx, row in filtered_df.iterrows():
                        distance = calculate_distance(user_lat, user_lon, row['latitude'], row['longitude'])
                        distances.append((distance, idx, row))
                    distances.sort(key=lambda x: x[0])
                    nearest_shelters = distances[:5]
                    nearest_indices = set(idx for _, idx, _ in nearest_shelters)

                    # Display emergency route information (只顯示最近一個)
                    if nearest_shelters:
                        distance, shelter_idx, shelter_row = nearest_shelters[0]
                        st.markdown(f"""
                        <div style="background-color: #ffc107; color: #212529; padding: 15px; border-radius: 8px; margin: 10px 0;">
                            <h4 style="margin: 0;">🏃‍♂️ Nearest Shelter Route</h4>
                            <p style="margin: 5px 0;"><strong>📍 Shelter:</strong> {shelter_row['evaspot_name']}</p>
                            <p style="margin: 5px 0;"><strong>📏 Distance:</strong> {distance:.2f} km</p>
                            <p style="margin: 5px 0;"><strong>👥 Capacity:</strong> {shelter_row['evaspot_capacity']:,.0f}</p>
                            <p style="margin: 5px 0;"><strong>⏱️ Estimated Time:</strong> {distance*12:.0f} minutes (walking)</p>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    map_center = [filtered_df['latitude'].mean(), filtered_df['longitude'].mean()]
                    zoom_level = 12
                
                m = folium.Map(location=map_center, zoom_start=zoom_level)

                # Set different colors for different disaster types
                disaster_colors = {
                    '内水氾濫': 'lightblue',
                    '土石流': 'brown', 
                    '地震': 'red',
                    '大規模な火事': 'orange',
                    '崖崩れ・地滑り': 'darkred',
                    '津波': 'blue',
                    '洪水': 'lightgreen',
                    '高潮': 'purple'
                }

                # Add user location marker if in emergency mode
                if st.session_state.emergency_mode and st.session_state.user_location:
                    user_lat, user_lon = st.session_state.user_location
                    folium.Marker(
                        location=[user_lat, user_lon],
                        popup=folium.Popup("🧑 Your Current Location", max_width=200),
                        tooltip="Your Location",
                        icon=folium.Icon(color='green', icon='user', prefix='fa')
                    ).add_to(m)

                    # 只顯示最近5個避難所
                    for i, (distance, idx, row) in enumerate(nearest_shelters):
                        # Find applicable disaster types for this shelter
                        applicable_disasters = []
                        for j, disaster_col in enumerate(disaster_columns):
                            if row[disaster_col] == 1:
                                disaster_name = list(disaster_types.keys())[j]
                                applicable_disasters.append(disaster_name)
                        primary_disaster = applicable_disasters[0] if applicable_disasters else '地震'
                        marker_color = disaster_colors.get(primary_disaster, 'gray')
                        # 最近一個標紅
                        if i == 0:
                            marker_color = 'red'
                            # 路徑線（起點：user_lat, user_lon，終點：row['latitude'], row['longitude']）
                            route_coords = get_route_osmnx(user_lat, user_lon, row['latitude'], row['longitude'])
                            if route_coords:
                                folium.PolyLine(
                                    locations=route_coords,
                                    color='red', weight=4, opacity=0.8,
                                    popup=f"Route to {row['evaspot_name']} ({distance:.2f} km)"
                                ).add_to(m)
                            else:
                                st.warning(f"⚠️ 找不到步行路徑，請確認起點終點附近有道路。({row['evaspot_name']})")
                        capacity_display = f"{row['evaspot_capacity']:,.0f}" if pd.notna(row['evaspot_capacity']) and row['evaspot_capacity'] > 0 else "Not specified"
                        distance_info = f"<b>📏 Distance from you:</b> {distance:.2f} km<br>"
                        popup_html = f"""
                        <b>📍 Name:</b> {row['evaspot_name']}<br>
                        <b>👥 Capacity:</b> {capacity_display}<br>
                        <b>🔰 Type:</b> {row['evaspot_kind_name']}<br>
                        <b>⚠️ Applicable Disasters:</b> {', '.join(applicable_disasters)}<br>
                        {distance_info}
                        """
                        popup = folium.Popup(popup_html, max_width=300)
                        folium.Marker(
                            location=[row['latitude'], row['longitude']],
                            popup=popup,
                            tooltip=f"{row['evaspot_name']} ({', '.join(applicable_disasters)})",
                            icon=folium.Icon(color=marker_color, icon='info-sign')
                        ).add_to(m)
                else:
                    # 普通模式顯示全部
                    for idx, row in filtered_df.iterrows():
                        # Find applicable disaster types for this shelter
                        applicable_disasters = []
                        for i, disaster_col in enumerate(disaster_columns):
                            if row[disaster_col] == 1:
                                disaster_name = list(disaster_types.keys())[i]
                                applicable_disasters.append(disaster_name)
                        
                        # Select primary color (use first applicable disaster type)
                        primary_disaster = applicable_disasters[0] if applicable_disasters else '地震'
                        marker_color = disaster_colors.get(primary_disaster, 'gray')
                        
                        # Add distance info in emergency mode
                        distance_info = ""
                        if st.session_state.emergency_mode and st.session_state.user_location:
                            user_lat, user_lon = st.session_state.user_location
                            distance = calculate_distance(user_lat, user_lon, row['latitude'], row['longitude'])
                            distance_info = f"<b>📏 Distance from you:</b> {distance:.2f} km<br>"
                        
                        popup_html = f"""
                        <b>📍 Name:</b> {row['evaspot_name']}<br>
                        <b>👥 Capacity:</b> {row['evaspot_capacity']:,.0f}<br>
                        <b>🔰 Type:</b> {row['evaspot_kind_name']}<br>
                        <b>⚠️ Applicable Disasters:</b> {', '.join(applicable_disasters)}<br>
                        {distance_info}
                        """
                        popup = folium.Popup(popup_html, max_width=300)
                        
                        folium.Marker(
                            location=[row['latitude'], row['longitude']],
                            popup=popup,
                            tooltip=f"{row['evaspot_name']} ({', '.join(applicable_disasters)})",
                            icon=folium.Icon(color=marker_color, icon='info-sign') 
                        ).add_to(m)

                # Map title with emergency mode indicator
                if st.session_state.emergency_mode:
                    st.subheader("🚨 Emergency Route Map - Navigate to Safety")
                    if st.session_state.user_location:
                        st.markdown("""
                        <div style="background-color: #ff6b6b; color: white; padding: 10px; border-radius: 5px; margin: 5px 0; text-align: center;">
                            <strong>🧭 Emergency Navigation Active - Follow the red route to the nearest shelter</strong>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.subheader("🗺️ Map Preview")
                
                st_folium(m, width='100%', height=380)
                
                # Display legend
                with st.expander("🎨 Color Legend"):
                    legend_cols = st.columns(4)
                    for i, (disaster, color) in enumerate(disaster_colors.items()):
                        with legend_cols[i % 4]:
                            st.markdown(f"🔸 **{color.upper()}**: {disaster}")
                    
                    # Add emergency mode legend
                    if st.session_state.emergency_mode:
                        st.markdown("---")
                        st.markdown("**Emergency Mode Markers:**")
                        emergency_cols = st.columns(3)
                        with emergency_cols[0]:
                            st.markdown("🟢 **GREEN**: Your Location")
                        with emergency_cols[1]:
                            st.markdown("🔴 **RED**: Nearest Shelter")
                        with emergency_cols[2]:
                            st.markdown("🔴 **RED LINE**: Evacuation Route")

                with st.expander("📊 View Filtered Data Table"):
                    display_columns = required_columns + [col for col in disaster_columns if col in selected_disasters]
                    st.dataframe(filtered_df[display_columns])
            else:
                st.warning("⚠️ No shelter data matches the selected disaster types.")

    except Exception as e:
        st.error(f"Error occurred while reading or processing file: {e}")
else:
    st.error(f"Error: Database file not found at specified path!\nPlease confirm that '{db_path}' file exists.")
