import os
import requests
import json
import logging
from datetime import datetime, timedelta
import pytz
import time

# 한국 시간대 설정
KST = pytz.timezone('Asia/Seoul')

def setup_logging():
    """로깅 설정"""
    # ... 기존 코드 유지 ...

def collect_extended_dart_data():
    """확장된 기간의 DART 데이터 수집"""
    # ... 기존 코드 유지 ...

def filter_executive_disclosures(data):
    """임원 관련 공시 모두 포함 (내용 확인 필요)"""
    # ... 기존 코드 유지 ...

# ✅ 새로 추가할 함수
def send_single_message(bot_token, chat_id, message):
    """단일 메시지 전송"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code != 200:
            logging.error(f"❌ 메시지 전송 실패: {response.status_code}")
            logging.error(f"응답: {response.text}")
            return False
        
        # 메시지 전송 간격 (텔레그램 API 제한 고려)
        time.sleep(1)
        return True
        
    except Exception as e:
        logging.error(f"❌ 단일 메시지 전송 오류: {e}")
        return False

# ✅ 기존 함수를 교체할 함수
def send_telegram_notification(disclosures):
    """텔레그램 알림 전송 (메시지 분할 기능 추가)"""
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not bot_token or not chat_id:
            logging.warning("⚠️ 텔레그램 설정이 없습니다.")
            return False
        
        if not disclosures:
            logging.info("📭 알림할 공시가 없습니다.")
            return False
        
        # 메시지 분할 설정
        MAX_MESSAGE_LENGTH = 4000  # 텔레그램 최대 4096자, 안전 마진 고려
        SAFE_MESSAGE_LENGTH = 600  # 사용자 요청 길이
        
        # 헤더 메시지 생성
        header_message = f"🚨 *임원 관련 공시 알림*\n\n"
        header_message += f"📅 조회시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}\n"
        header_message += f"📊 총 발견 건수: {len(disclosures)}건\n\n"
        header_message += f"⚠️ *수동 확인 필요*\n"
        header_message += f"각 공시를 KIND에서 확인하여 장내매수 여부를 판단하세요.\n\n"
        
        # 첫 번째 메시지 전송
        send_single_message(bot_token, chat_id, header_message)
        
        # 공시 목록을 메시지 길이에 따라 분할하여 전송
        current_message = ""
        message_count = 1
        item_count = 0
        
        for item in disclosures:
            item_count += 1
            corp_name = item.get('corp_name', '')
            report_nm = item.get('report_nm', '')
            rcept_dt = item.get('rcept_dt', '')
            rcept_no = item.get('rcept_no', '')
            flr_nm = item.get('flr_nm', '')
            
            # 날짜 포맷팅
            if rcept_dt and len(rcept_dt) == 8:
                formatted_date = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}"
            else:
                formatted_date = rcept_dt
            
            # 개별 공시 메시지 생성
            item_message = f"{item_count}. *{corp_name}*\n"
            item_message += f"   📄 {report_nm}\n"
            item_message += f"   👤 제출인: {flr_nm}\n"
            item_message += f"   📅 {formatted_date}\n"
            item_message += f"   🔗 [KIND에서 확인](https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno={rcept_no})\n\n"
            
            # 메시지 길이 체크
            if len(current_message + item_message) > SAFE_MESSAGE_LENGTH:
                # 현재 메시지 전송
                if current_message:
                    final_message = f"📋 *메시지 {message_count}*\n\n{current_message}"
                    final_message += f"🔍 각 링크를 클릭하여 실제 장내매수 여부를 확인하세요."
                    
                    send_single_message(bot_token, chat_id, final_message)
                    logging.info(f"✅ 메시지 {message_count} 전송 완료")
                
                # 새 메시지 시작
                current_message = item_message
                message_count += 1
            else:
                current_message += item_message
        
        # 마지막 메시지 전송
        if current_message:
            final_message = f"📋 *메시지 {message_count}*\n\n{current_message}"
            final_message += f"🔍 각 링크를 클릭하여 실제 장내매수 여부를 확인하세요."
            
            send_single_message(bot_token, chat_id, final_message)
            logging.info(f"✅ 메시지 {message_count} 전송 완료")
        
        # 요약 메시지 전송
        summary_message = f"✅ *전송 완료*\n\n"
        summary_message += f"📊 총 {len(disclosures)}건의 공시를 {message_count}개 메시지로 분할하여 전송했습니다.\n\n"
        summary_message += f"💡 *TIP*: 개인 제출인일 경우 장내매수 가능성이 높습니다."
        
        send_single_message(bot_token, chat_id, summary_message)
        
        logging.info(f"✅ 총 {message_count + 2}개 메시지 전송 완료 (헤더 + 공시 {message_count}개 + 요약)")
        return True
        
    except Exception as e:
        logging.error(f"❌ 텔레그램 알림 오류: {e}")
        return False

def main():
    """메인 실행 함수"""
    # ... 기존 코드 유지 ...

if __name__ == "__main__":
    main()
