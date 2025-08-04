import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
import requests

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EmailService:
    """Email 服務類別，支援多種 Email 服務提供商"""
    
    def __init__(self, provider: str = 'gmail', user_info: dict = None):
        """
        初始化 Email 服務
        
        Args:
            provider: Email 服務提供商 ('gmail', 'outlook', 'sendgrid', 'mock', 'user')
            user_info: 登入使用者的資訊（當 provider='user' 時使用）
        """
        self.provider = provider
        self.smtp_server = None
        self.smtp_port = None
        self.username = None
        self.password = None
        
        if provider == 'user' and user_info:
            self._init_user_account(user_info)
        elif provider == 'gmail':
            self._init_gmail()
        elif provider == 'outlook':
            self._init_outlook()
        elif provider == 'sendgrid':
            self._init_sendgrid()
    
    def _init_gmail(self):
        """初始化 Gmail 設定"""
        try:
            self.username = os.getenv('GMAIL_USERNAME')
            self.password = os.getenv('GMAIL_APP_PASSWORD')  # 使用 App Password
            self.smtp_server = 'smtp.gmail.com'
            self.smtp_port = 587
            
            if not all([self.username, self.password]):
                logger.warning("Gmail 環境變數未設定，將使用模擬模式")
                self.provider = 'mock'
                return
            
            logger.info("Gmail 設定初始化成功")
            
        except Exception as e:
            logger.error(f"Gmail 初始化失敗: {e}")
            self.provider = 'mock'
    
    def _init_outlook(self):
        """初始化 Outlook 設定"""
        try:
            self.username = os.getenv('OUTLOOK_USERNAME')
            self.password = os.getenv('OUTLOOK_PASSWORD')
            self.smtp_server = 'smtp-mail.outlook.com'
            self.smtp_port = 587
            
            if not all([self.username, self.password]):
                logger.warning("Outlook 環境變數未設定，將使用模擬模式")
                self.provider = 'mock'
                return
            
            logger.info("Outlook 設定初始化成功")
            
        except Exception as e:
            logger.error(f"Outlook 初始化失敗: {e}")
            self.provider = 'mock'
    
    def _init_user_account(self, user_info: dict):
        """初始化登入使用者的帳號設定"""
        try:
            self.username = user_info.get('email')
            self.password = user_info.get('password')
            self.smtp_server = user_info.get('smtp_server')
            self.smtp_port = user_info.get('smtp_port')
            self.provider = user_info.get('provider', 'user')
            
            if not all([self.username, self.password, self.smtp_server, self.smtp_port]):
                logger.warning("使用者帳號資訊不完整，將使用模擬模式")
                self.provider = 'mock'
                return
            
            logger.info(f"使用者帳號設定初始化成功: {self.username}")
            
        except Exception as e:
            logger.error(f"使用者帳號初始化失敗: {e}")
            self.provider = 'mock'
    
    def _init_sendgrid(self):
        """初始化 SendGrid 設定"""
        try:
            self.api_key = os.getenv('SENDGRID_API_KEY')
            self.from_email = os.getenv('SENDGRID_FROM_EMAIL')
            
            if not all([self.api_key, self.from_email]):
                logger.warning("SendGrid 環境變數未設定，將使用模擬模式")
                self.provider = 'mock'
                return
            
            logger.info("SendGrid 設定初始化成功")
            
        except Exception as e:
            logger.error(f"SendGrid 初始化失敗: {e}")
            self.provider = 'mock'
    
    def send_email(self, to_email: str, subject: str, message: str, html_message: str = None) -> Dict[str, any]:
        """
        發送 Email
        
        Args:
            to_email: 收件人 Email
            subject: 郵件主旨
            message: 純文字內容
            html_message: HTML 內容（可選）
            
        Returns:
            發送結果字典
        """
        if self.provider == 'sendgrid':
            return self._send_sendgrid_email(to_email, subject, message, html_message)
        elif self.provider in ['gmail', 'outlook'] and self.smtp_server:
            return self._send_smtp_email(to_email, subject, message, html_message)
        else:
            return self._send_mock_email(to_email, subject, message, html_message)
    
    def _send_smtp_email(self, to_email: str, subject: str, message: str, html_message: str = None) -> Dict[str, any]:
        """使用 SMTP 發送 Email"""
        try:
            # 建立郵件物件
            msg = MIMEMultipart('alternative')
            msg['From'] = self.username
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # 添加純文字內容
            text_part = MIMEText(message, 'plain', 'utf-8')
            msg.attach(text_part)
            
            # 添加 HTML 內容（如果有的話）
            if html_message:
                html_part = MIMEText(html_message, 'html', 'utf-8')
                msg.attach(html_part)
            
            # 連接到 SMTP 伺服器並發送
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            
            logger.info(f"Email 發送成功: {to_email}")
            return {
                'success': True,
                'message_id': f'email_{to_email}_{hash(subject)}',
                'status': 'sent',
                'provider': self.provider
            }
            
        except Exception as e:
            logger.error(f"Email 發送失敗: {e}")
            return {
                'success': False,
                'error': str(e),
                'provider': self.provider
            }
    
    def _send_sendgrid_email(self, to_email: str, subject: str, message: str, html_message: str = None) -> Dict[str, any]:
        """使用 SendGrid API 發送 Email"""
        try:
            url = "https://api.sendgrid.com/v3/mail/send"
            
            data = {
                "personalizations": [
                    {
                        "to": [{"email": to_email}]
                    }
                ],
                "from": {"email": self.from_email},
                "subject": subject,
                "content": [
                    {
                        "type": "text/plain",
                        "value": message
                    }
                ]
            }
            
            # 如果有 HTML 內容，添加到 content 中
            if html_message:
                data["content"].append({
                    "type": "text/html",
                    "value": html_message
                })
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(url, json=data, headers=headers)
            
            if response.status_code == 202:
                logger.info(f"SendGrid Email 發送成功: {to_email}")
                return {
                    'success': True,
                    'message_id': response.headers.get('X-Message-Id', 'unknown'),
                    'status': 'sent',
                    'provider': 'sendgrid'
                }
            else:
                logger.error(f"SendGrid Email 發送失敗: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'error': f"HTTP {response.status_code}: {response.text}",
                    'provider': 'sendgrid'
                }
                
        except Exception as e:
            logger.error(f"SendGrid Email 發送異常: {e}")
            return {
                'success': False,
                'error': str(e),
                'provider': 'sendgrid'
            }
    
    def _send_mock_email(self, to_email: str, subject: str, message: str, html_message: str = None) -> Dict[str, any]:
        """模擬發送 Email（用於測試）"""
        logger.info(f"[MOCK EMAIL] 發送 Email 給 {to_email}")
        logger.info(f"[MOCK EMAIL] 主旨: {subject}")
        logger.info(f"[MOCK EMAIL] 內容: {message}")
        if html_message:
            logger.info(f"[MOCK EMAIL] HTML 內容: {html_message}")
        
        return {
            'success': True,
            'message_id': f'mock_email_{to_email}_{hash(subject)}',
            'status': 'sent',
            'provider': 'mock'
        }
    
    def send_bulk_email(self, contacts: List[Dict], subject_template: str, message_template: str, html_template: str = None) -> List[Dict]:
        """
        批量發送 Email
        
        Args:
            contacts: 聯絡人列表，每個聯絡人應包含 '信箱' 和 '姓名' 欄位
            subject_template: 主旨模板，可使用 {name} 作為聯絡人姓名佔位符
            message_template: 純文字內容模板，可使用 {name} 作為聯絡人姓名佔位符
            html_template: HTML 內容模板（可選）
            
        Returns:
            發送結果列表
        """
        results = []
        
        for contact in contacts:
            email = contact.get('信箱', '')
            name = contact.get('姓名', '')
            
            if not email:
                results.append({
                    'contact': contact,
                    'success': False,
                    'error': '缺少 Email 地址'
                })
                continue
            
            # 替換模板中的佔位符
            personalized_subject = subject_template.format(name=name)
            personalized_message = message_template.format(name=name)
            personalized_html = html_template.format(name=name) if html_template else None
            
            # 發送 Email
            result = self.send_email(email, personalized_subject, personalized_message, personalized_html)
            result['contact'] = contact
            results.append(result)
        
        return results

# 預設 Email 模板
DEFAULT_EMAIL_TEMPLATES = {
    'emergency': {
        'subject': '緊急通知 - {name}',
        'message': '我現在人很平安 我現在人在{latlng} 現在要前往{nearest_shelter}避難所',
        'html': '<html><body><p>我現在人很平安<br>我現在人在{latlng}<br>現在要前往{nearest_shelter}避難所</p></body></html>'
    }
}

def create_email_service(provider: str = 'gmail', user_info: dict = None) -> EmailService:
    """建立 Email 服務實例"""
    return EmailService(provider, user_info) 