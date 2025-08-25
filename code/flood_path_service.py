import pandas as pd
import sqlite3
import os
from typing import List, Dict, Tuple, Optional
import logging

class FloodPathService:
    """洪水路徑規劃服務：根據水位監控資料動態調整路徑規劃"""
    
    def __init__(self, water_level_csv_path: str, avoid_zone_db_path: str):
        """
        初始化洪水路徑規劃服務
        
        Args:
            water_level_csv_path: fukui_水位.csv 文件路徑
            avoid_zone_db_path: aviod_zone.db 資料庫路徑
        """
        self.water_level_csv_path = water_level_csv_path
        self.avoid_zone_db_path = avoid_zone_db_path
        self.logger = self._setup_logger()
        
    def _setup_logger(self) -> logging.Logger:
        """設置日誌記錄"""
        logger = logging.getLogger('FloodPathService')
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger
    
    def read_water_level_data(self) -> pd.DataFrame:
        """
        讀取水位資料 CSV 文件
        
        Returns:
            pd.DataFrame: 水位資料
        """
        try:
            if not os.path.exists(self.water_level_csv_path):
                self.logger.error(f"水位資料文件不存在: {self.water_level_csv_path}")
                return pd.DataFrame()
            
            # 讀取CSV文件，處理編碼和分隔符
            df = pd.read_csv(
                self.water_level_csv_path,
                encoding='utf-8-sig',
                dtype=str  # 先以字串讀取避免數值轉換問題
            )
            
            self.logger.info(f"成功讀取水位資料，共 {len(df)} 筆記錄")
            return df
            
        except Exception as e:
            self.logger.error(f"讀取水位資料時發生錯誤: {e}")
            return pd.DataFrame()
    
    def filter_flood_risk_rivers(self, current_disaster: str = None) -> List[str]:
        """
        篩選出水位超過通報水位的河川
        
        Args:
            current_disaster: 當前災害類型，支援洪水、内水氾濫、高潮
            
        Returns:
            List[str]: 超過通報水位的河川名稱列表
        """
        # 定義需要考慮 avoid_zone.db 的災害類型（津波除外）
        avoid_zone_disasters = ["洪水", "内水氾濫", "高潮"]
        
        # 檢查災害情境：僅在這三種水災相關災害時執行
        if current_disaster not in avoid_zone_disasters:
            self.logger.info(f"當前災害類型為 '{current_disaster}'，不需要考慮 avoid_zone.db")
            return []
        
        try:
            df = self.read_water_level_data()
            if df.empty:
                return []
            
            flood_risk_rivers = []
            
            for idx, row in df.iterrows():
                try:
                    # 提取河川名稱
                    river_name = str(row['河川名_河川名']).strip() if '河川名_河川名' in row else ''
                    
                    # 提取水位數據（移除箭頭符號並轉換為浮點數）
                    current_level_str = str(row['河川 水位_[m]']).strip() if '河川 水位_[m]' in row else ''
                    warning_level_str = str(row['水防団 待機水位 (通報水位)_[m]']).strip() if '水防団 待機水位 (通報水位)_[m]' in row else ''
                    
                    # 清理水位字串（移除箭頭符號）
                    current_level_str = current_level_str.replace('→', '').replace('↑', '').replace('↓', '').strip()
                    
                    # 跳過空值或無效數據
                    if (not river_name or 
                        not current_level_str or 
                        not warning_level_str or
                        current_level_str == '---' or 
                        warning_level_str == '---'):
                        continue
                    
                    # 轉換為數值
                    current_level = float(current_level_str)
                    warning_level = float(warning_level_str)
                    
                    # 檢查是否超過通報水位
                    if current_level >= warning_level:
                        flood_risk_rivers.append(river_name)
                        self.logger.info(f"河川 {river_name}: 水位 {current_level}m >= 通報水位 {warning_level}m")
                        
                except (ValueError, TypeError) as e:
                    # 跳過無法處理的數據
                    continue
                    
            self.logger.info(f"找到 {len(flood_risk_rivers)} 條超過通報水位的河川")
            return flood_risk_rivers
            
        except Exception as e:
            self.logger.error(f"篩選洪水風險河川時發生錯誤: {e}")
            return []
    
    def get_avoid_zones_for_rivers(self, river_names: List[str]) -> List[Dict]:
        """
        根據河川名稱從避難區域資料庫中查詢對應的避難區域
        
        Args:
            river_names: 河川名稱列表
            
        Returns:
            List[Dict]: 避難區域資訊列表
        """
        if not river_names:
            return []
            
        try:
            if not os.path.exists(self.avoid_zone_db_path):
                self.logger.error(f"避難區域資料庫不存在: {self.avoid_zone_db_path}")
                return []
            
            conn = sqlite3.connect(self.avoid_zone_db_path)
            
            # 構建查詢條件
            placeholders = ','.join(['?' for _ in river_names])
            query = f"""
            SELECT id, type, name, coordinates 
            FROM avoid_zones 
            WHERE name IN ({placeholders})
            """
            
            cursor = conn.execute(query, river_names)
            results = cursor.fetchall()
            
            avoid_zones = []
            for result in results:
                avoid_zone = {
                    'id': result[0],
                    'type': result[1],
                    'name': result[2],
                    'coordinates': result[3]
                }
                avoid_zones.append(avoid_zone)
            
            conn.close()
            self.logger.info(f"找到 {len(avoid_zones)} 個匹配的避難區域")
            return avoid_zones
            
        except Exception as e:
            self.logger.error(f"查詢避難區域時發生錯誤: {e}")
            return []
    
    def get_disaster_obstacle_zones(self, current_disaster: str = None) -> List[Dict]:
        """
        獲取當前災害的障礙區域（支援洪水、内水氾濫、高潮）
        
        Args:
            current_disaster: 當前災害類型
            
        Returns:
            List[Dict]: 需要避開的障礙區域列表
        """
        # 步驟1: 篩選超過通報水位的河川（僅洪水、内水氾濫、高潮）
        flood_risk_rivers = self.filter_flood_risk_rivers(current_disaster)
        
        if not flood_risk_rivers:
            self.logger.info("沒有發現超過通報水位的河川，無需設置障礙區域")
            return []
        
        # 步驟2: 查詢對應的避難區域
        obstacle_zones = self.get_avoid_zones_for_rivers(flood_risk_rivers)
        
        return obstacle_zones
    
    def parse_coordinates(self, coordinates_str: str) -> List[Tuple[float, float]]:
        """
        解析座標字串為座標點列表
        
        Args:
            coordinates_str: 座標字串
            
        Returns:
            List[Tuple[float, float]]: 座標點列表 [(lat, lon), ...]
        """
        try:
            # 這裡根據實際的座標格式進行解析
            # 假設格式為 "lat1,lon1;lat2,lon2;..." 或其他格式
            if not coordinates_str:
                return []
            
            # 示例解析邏輯，需要根據實際數據格式調整
            coord_pairs = coordinates_str.split(';')
            coordinates = []
            
            for pair in coord_pairs:
                if ',' in pair:
                    parts = pair.split(',')
                    if len(parts) >= 2:
                        lat = float(parts[0].strip())
                        lon = float(parts[1].strip())
                        coordinates.append((lat, lon))
            
            return coordinates
            
        except Exception as e:
            self.logger.error(f"解析座標時發生錯誤: {e}")
            return []
    
    def is_point_in_obstacle_zone(self, lat: float, lon: float, obstacle_zones: List[Dict]) -> bool:
        """
        檢查指定點是否在障礙區域內
        
        Args:
            lat: 緯度
            lon: 經度
            obstacle_zones: 障礙區域列表
            
        Returns:
            bool: 是否在障礙區域內
        """
        for zone in obstacle_zones:
            coordinates = self.parse_coordinates(zone['coordinates'])
            if self._point_in_polygon(lat, lon, coordinates):
                return True
        return False
    
    def _point_in_polygon(self, lat: float, lon: float, polygon_coords: List[Tuple[float, float]]) -> bool:
        """
        使用射線法判斷點是否在多邊形內
        
        Args:
            lat: 點的緯度
            lon: 點的經度
            polygon_coords: 多邊形頂點座標列表
            
        Returns:
            bool: 是否在多邊形內
        """
        if len(polygon_coords) < 3:
            return False
        
        x, y = lon, lat
        n = len(polygon_coords)
        inside = False
        
        p1x, p1y = polygon_coords[0]
        for i in range(1, n + 1):
            p2x, p2y = polygon_coords[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        
        return inside
    
    def get_safe_route_avoiding_disaster_zones(self, start_lat: float, start_lon: float, 
                                          end_lat: float, end_lon: float, 
                                          current_disaster: str = None) -> Optional[List[Tuple[float, float]]]:
        """
        獲取避開災害危險區域的安全路徑（支援洪水、内水氾濫、高潮）
        
        Args:
            start_lat: 起點緯度
            start_lon: 起點經度
            end_lat: 終點緯度
            end_lon: 終點經度
            current_disaster: 當前災害類型
            
        Returns:
            Optional[List[Tuple[float, float]]]: 安全路徑座標點列表，如果無法找到則返回None
        """
        # 獲取障礙區域
        obstacle_zones = self.get_disaster_obstacle_zones(current_disaster)
        
        if not obstacle_zones:
            self.logger.info("無障礙區域，使用一般路徑規劃")
            return None  # 返回None表示可以使用一般路徑規劃
        
        self.logger.info(f"找到 {len(obstacle_zones)} 個障礙區域，將在路徑規劃中避開")
        
        # 這裡可以整合更複雜的路徑規劃算法，考慮避開障礙區域
        # 目前返回障礙區域資訊，讓調用者決定如何處理
        return obstacle_zones

def create_flood_path_service():
    """創建洪水路徑規劃服務實例"""
    # 從環境變數或設定文件中獲取路徑
    base_path = os.path.dirname(os.path.abspath(__file__))
    dataset_path = os.path.join(base_path, '..', 'dataset')
    
    water_level_csv = os.path.join(dataset_path, 'fukui_水位.csv')
    avoid_zone_db = os.path.join(dataset_path, 'avoid_zone.db')
    
    return FloodPathService(water_level_csv, avoid_zone_db)

if __name__ == "__main__":
    # 測試用例
    service = create_flood_path_service()
    
    # 測試洪水災害情境
    print("=== 測試洪水災害情境 ===")
    obstacle_zones = service.get_flood_obstacle_zones("洪水")
    print(f"找到 {len(obstacle_zones)} 個障礙區域")
    
    for zone in obstacle_zones:
        print(f"- {zone['name']} (類型: {zone['type']})")
    
    # 測試非洪水災害情境
    print("\n=== 測試地震災害情境 ===")
    obstacle_zones_earthquake = service.get_flood_obstacle_zones("地震")
    print(f"找到 {len(obstacle_zones_earthquake)} 個障礙區域")