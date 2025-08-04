import os
import logging
from typing import List, Dict
import re

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SMSService:
    """簡訊服務類別（模擬模式）"""
    
    def __init__(self):
        self.provider = 'mock'
        logger.info("簡訊服務初始化（模擬模式）")
    
    def _format_phone_number(self, phone: str) -> str:
        """格式化電話號碼"""
        # 移除所有非數字字符
        phone_clean = re.sub(r'[^\d]', '', phone)
        
        # 處理台灣手機號碼
        if phone_clean.startswith('09') and len(phone_clean) == 10:
            return f"+886{phone_clean[1:]}"
        elif phone_clean.startswith('886') and len(phone_clean) == 11:
            return f"+{phone_clean}"
        elif phone_clean.startswith('+886'):
            return phone_clean
        else:
            return phone_clean
    
    def send_sms(self, to_phone: str, message: str) -> Dict[str, any]:
        """
        發送簡訊（模擬模式）
        
        Args:
            to_phone: 收件人電話號碼
            message: 簡訊內容
            
        Returns:
            發送結果字典
        """
        formatted_phone = self._format_phone_number(to_phone)
        
        logger.info(f"[MOCK SMS] 發送簡訊給 {formatted_phone}")
        logger.info(f"[MOCK SMS] 內容: {message}")
        
        return {
            'success': True,
            'message_id': f'mock_sms_{formatted_phone}_{hash(message)}',
            'status': 'sent',
            'provider': 'mock',
            'to': formatted_phone,
            'message': message
        }
    
    def send_bulk_sms(self, contacts: List[Dict], message_template: str) -> List[Dict]:
        """
        批量發送簡訊
        
        Args:
            contacts: 聯絡人列表，每個聯絡人應包含 '電話' 和 '姓名' 欄位
            message_template: 簡訊模板，可使用 {name} 作為聯絡人姓名佔位符
            
        Returns:
            發送結果列表
        """
        results = []
        
        for contact in contacts:
            phone = contact.get('電話', '')
            name = contact.get('姓名', '')
            
            if not phone:
                results.append({
                    'contact': contact,
                    'success': False,
                    'error': '缺少電話號碼'
                })
                continue
            
            # 替換模板中的佔位符
            personalized_message = message_template.format(name=name)
            
            # 發送簡訊
            result = self.send_sms(phone, personalized_message)
            result['contact'] = contact
            results.append(result)
        
        return results

# 預設簡訊模板
DEFAULT_SMS_TEMPLATES = {
    'emergency': '緊急通知：{name}，目前發生緊急狀況，請立即前往最近的避難所。請保持冷靜並注意安全。'
}

def create_sms_service() -> SMSService:
    """建立簡訊服務實例"""
    return SMSService() 