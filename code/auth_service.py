import os
import logging
import smtplib
from typing import Dict, Optional, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AuthService:
    """使用者認證服務，支援 Gmail 和 Outlook 登入"""
    
    def __init__(self):
        self.smtp_servers = {
            'gmail': {
                'server': 'smtp.gmail.com',
                'port': 587
            },
            'outlook': {
                'server': 'smtp-mail.outlook.com',
                'port': 587
            }
        }
    
    def detect_email_provider(self, email: str) -> str:
        """根據 Email 地址判斷服務提供商"""
        email_lower = email.lower()
        if '@gmail.com' in email_lower:
            return 'gmail'
        elif '@outlook.com' in email_lower or '@hotmail.com' in email_lower:
            return 'outlook'
        else:
            # 預設使用 Gmail
            return 'gmail'
    
    def verify_credentials(self, email: str, password: str) -> Tuple[bool, str, Dict]:
        """
        驗證使用者登入憑證
        
        Args:
            email: 使用者 Email
            password: 使用者密碼
            
        Returns:
            (是否成功, 錯誤訊息, 使用者資訊)
        """
        try:
            provider = self.detect_email_provider(email)
            smtp_config = self.smtp_servers[provider]
            
            # 嘗試連接到 SMTP 伺服器
            with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
                server.starttls()
                server.login(email, password)
                
                logger.info(f"使用者 {email} 登入成功")
                
                user_info = {
                    'email': email,
                    'provider': provider,
                    'smtp_server': smtp_config['server'],
                    'smtp_port': smtp_config['port'],
                    'password': password  # 注意：實際應用中應該加密儲存
                }
                
                return True, "登入成功", user_info
                
        except smtplib.SMTPAuthenticationError:
            error_msg = "帳號或密碼錯誤"
            logger.warning(f"使用者 {email} 登入失敗：{error_msg}")
            return False, error_msg, {}
            
        except smtplib.SMTPException as e:
            error_msg = f"SMTP 錯誤：{str(e)}"
            logger.error(f"使用者 {email} 登入失敗：{error_msg}")
            return False, error_msg, {}
            
        except Exception as e:
            error_msg = f"連線錯誤：{str(e)}"
            logger.error(f"使用者 {email} 登入失敗：{error_msg}")
            return False, error_msg, {}
    
    def test_email_sending(self, user_info: Dict) -> Tuple[bool, str]:
        """
        測試使用登入的帳號發送 Email
        
        Args:
            user_info: 使用者資訊
            
        Returns:
            (是否成功, 錯誤訊息)
        """
        try:
            with smtplib.SMTP(user_info['smtp_server'], user_info['smtp_port']) as server:
                server.starttls()
                server.login(user_info['email'], user_info['password'])
                
                # 建立測試郵件
                msg = MIMEMultipart('alternative')
                msg['From'] = user_info['email']
                msg['To'] = user_info['email']  # 發送給自己作為測試
                msg['Subject'] = '登入測試 - 緊急通知系統'
                
                text_content = "這是一封測試郵件，確認您的帳號可以正常發送通知。"
                html_content = """
                <html>
                <body>
                    <h2>登入測試成功</h2>
                    <p>這是一封測試郵件，確認您的帳號可以正常發送通知。</p>
                    <p>您的帳號：{email}</p>
                    <p>服務提供商：{provider}</p>
                </body>
                </html>
                """.format(email=user_info['email'], provider=user_info['provider'])
                
                msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
                msg.attach(MIMEText(html_content, 'html', 'utf-8'))
                
                server.send_message(msg)
                
                logger.info(f"測試郵件發送成功：{user_info['email']}")
                return True, "測試郵件發送成功"
                
        except Exception as e:
            error_msg = f"測試郵件發送失敗：{str(e)}"
            logger.error(f"測試郵件發送失敗：{error_msg}")
            return False, error_msg

# 全域認證服務實例
auth_service = AuthService() 