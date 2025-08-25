import requests
import logging
from typing import List, Dict, Tuple
import os

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlacesService:
    """Google Places API 服務類別"""
    
    def __init__(self, api_key: str = None):
        # 您需要在這裡替換您的 Google Places API Key
        self.api_key = api_key or "AIzaSyCR_HQToL45fxDqbtoiqGM21NC6auBuOMc"
        self.base_url = "https://maps.googleapis.com/maps/api/place"
        
    def get_nearby_stores(self, lat: float, lng: float, radius: int = 2000) -> Dict:
        """
        搜尋附近的店家
        
        Args:
            lat: 緯度
            lng: 經度  
            radius: 搜尋半徑（公尺，最大 50000）
            
        Returns:
            包含不同類型店家的字典
        """
        try:
            # 定義不同類型的店家搜尋
            store_types = {
                'convenience_store': {
                    'type': 'convenience_store',
                    'keyword': 'convenience store',
                    'name': 'Convenience Store'
                },
                'supermarket': {
                    'type': 'supermarket', 
                    'keyword': 'supermarket',
                    'name': 'Supermarket'
                },
                'pharmacy': {
                    'type': 'pharmacy',
                    'keyword': 'pharmacy',
                    'name': 'Pharmacy'
                },
                'hardware_store': {
                    'type': 'hardware_store',
                    'keyword': 'hardware store',
                    'name': 'Hardware Store'
                }
            }
            
            results = {}
            
            for store_id, store_config in store_types.items():
                places = self._search_places(
                    lat=lat,
                    lng=lng,
                    radius=radius,
                    place_type=store_config['type'],
                    keyword=store_config['keyword']
                )
                
                results[store_id] = {
                    'name': store_config['name'],
                    'places': places[:5]  # 限制每種類型最多5個結果
                }
                
            return {
                'success': True,
                'data': results,
                'search_location': {'lat': lat, 'lng': lng},
                'radius': radius
            }
            
        except Exception as e:
            logger.error(f"搜尋附近店家時發生錯誤: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _search_places(self, lat: float, lng: float, radius: int, place_type: str, keyword: str) -> List[Dict]:
        """
        執行 Google Places API 搜尋
        """
        try:
            url = f"{self.base_url}/nearbysearch/json"
            
            params = {
                'location': f"{lat},{lng}",
                'radius': radius,
                'type': place_type,
                'keyword': keyword,
                'key': self.api_key,
                'language': 'zh-TW'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data['status'] == 'OK':
                places = []
                for place in data.get('results', []):
                    place_info = {
                        'place_id': place.get('place_id'),
                        'name': place.get('name'),
                        'address': place.get('vicinity', ''),
                        'rating': place.get('rating', 0),
                        'user_ratings_total': place.get('user_ratings_total', 0),
                        'location': place.get('geometry', {}).get('location', {}),
                        'opening_hours': place.get('opening_hours', {}).get('open_now', None),
                        'price_level': place.get('price_level', None),
                        'distance': self._calculate_distance(
                            lat, lng,
                            place.get('geometry', {}).get('location', {}).get('lat', 0),
                            place.get('geometry', {}).get('location', {}).get('lng', 0)
                        )
                    }
                    places.append(place_info)
                
                # 依距離排序
                places.sort(key=lambda x: x['distance'])
                return places
                
            else:
                logger.warning(f"Google Places API 回應狀態: {data['status']}")
                return []
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Google Places API 請求失敗: {e}")
            return []
        except Exception as e:
            logger.error(f"處理 Places API 回應時發生錯誤: {e}")
            return []
    
    def _calculate_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """
        計算兩點間的直線距離（公尺）
        使用 Haversine 公式
        """
        import math
        
        # 地球半徑（公尺）
        R = 6371000
        
        # 轉換為弧度
        lat1_rad = math.radians(lat1)
        lng1_rad = math.radians(lng1)
        lat2_rad = math.radians(lat2)
        lng2_rad = math.radians(lng2)
        
        # 計算差值
        dlat = lat2_rad - lat1_rad
        dlng = lng2_rad - lng1_rad
        
        # Haversine 公式
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        distance = R * c
        return distance
    
    def get_item_store_recommendations(self, items: List[Dict]) -> Dict[str, List[str]]:
        """
        根據物品類別推薦對應的店家類型
        
        Args:
            items: 物品清單，每個物品包含 'name', 'category' 等資訊
            
        Returns:
            物品對應的店家類型推薦
        """
        # 物品類別對應店家類型的映射
        category_store_mapping = {
            'Medical': ['pharmacy', 'convenience_store'],
            'Food & Water': ['supermarket', 'convenience_store'],
            'Protection': ['hardware_store', 'convenience_store'],
            'Lighting': ['hardware_store', 'convenience_store'],
            'Power': ['hardware_store', 'convenience_store'],
            'Communication': ['convenience_store'],
            'Warmth': ['convenience_store', 'supermarket'],
            'Hygiene': ['supermarket', 'convenience_store', 'pharmacy'],
            'Emergency': ['pharmacy', 'convenience_store'],
            'Waterproof': ['hardware_store', 'convenience_store'],
            'Safety': ['hardware_store', 'convenience_store'],
            'Important': ['convenience_store'],
            'Tools': ['hardware_store'],
            'Other': ['convenience_store']
        }
        
        # 店家類型英文名稱
        store_type_names = {
            'convenience_store': 'Convenience Store',
            'supermarket': 'Supermarket',
            'pharmacy': 'Pharmacy',
            'hardware_store': 'Hardware Store'
        }
        
        recommendations = {}
        recommended_stores = set()
        
        for item in items:
            category = item.get('category', 'Other')
            item_name = item.get('name', '')
            
            if category in category_store_mapping:
                store_types = category_store_mapping[category]
                store_names = [store_type_names[store_type] for store_type in store_types if store_type in store_type_names]
                recommendations[item_name] = store_names
                recommended_stores.update(store_types)
        
        return {
            'item_recommendations': recommendations,
            'recommended_store_types': list(recommended_stores),
            'store_type_names': store_type_names
        }

def create_places_service(api_key: str = None) -> PlacesService:
    """建立 Places 服務實例"""
    return PlacesService(api_key)