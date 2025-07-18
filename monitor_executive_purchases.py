import os
import requests
import json
import logging
from datetime import datetime, timedelta
import pytz

# 한국 시간대 설정
KST = pytz.timezone('Asia/Seoul')

# 로그 설정
def setup_logging():
    """로깅 설정"""
    current_time = datetime.now(KST)
    log_filename = f"./logs/executive_monitor_fixed_{current_time.strftime('%Y%m%d_%H%M%S')}.log"
    
    # logs 디렉토리 생성
    os.makedirs('./logs', exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s KST - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    # 한국 시간으로 로그 시간 설정
    logging.Formatter.converter = lambda *args: datetime.now(KST).timetuple()
    
    return log_filename

def get_dart_data():
    """DART API에서 데이터 조회 (수정된 버전)"""
    
    # 환경변수에서 API 키 가져오기
    api_key = os.getenv('DART_API_KEY')
    if not api_key:
        logging.error("❌ DART_API_KEY 환경변수가 설정되지 않았습니다.")
        return None
    
    # API 키 마스킹하여 로그 출력
    masked_key = f"{api_key[:8]}{'*' * 24}{api_key[-8:]}"
    logging.info(f"✅ DART API 키: {masked_key}")
    
    # 날짜 설정 (한국 시간 기준)
    now = datetime.now(KST)
    
    # 어제부터 오늘까지 조회 (YYYYMMDD 형식)
    yesterday = now - timedelta(days=1)
    bgn_de = yesterday.strftime('%Y%m%d')  # 시작일
    end_de = now.strftime('%Y%m%d')       # 종료일
    
    logging.info(f"📅 조회 기간: {bgn_de} ~ {end_de}")
    
    # API URL 구성 (curl 테스트와 동일한 방식)
    base_url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        'crtfc_key': api_key,
        'bgn_de': bgn_de,
        'end_de': end_de,
        'page_no': 1,
        'page_count': 100
    }
    
    # 실제 요청 URL 로그 출력
    url_with_params = f"{base_url}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
    masked_url = url_with_params.replace(api_key, f"{api_key[:8]}{'*' * 24}{api_key[-8:]}")
    logging.info(f"🌐 요청 URL: {masked_url}")
    
    try:
        # requests를 사용하여 API 호출 (curl과 동일한 방식)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        logging.info("📡 API 요청 시작...")
        response = requests.get(base_url, params=params, headers=headers, timeout=30)
        
        # 응답 상태 코드 확인
        logging.info(f"📊 응답 상태 코드: {response.status_code}")
        
        if response.status_code != 200:
            logging.error(f"❌ HTTP 오류: {response.status_code}")
            return None
        
        # JSON 응답 파싱
        try:
            data = response.json()
            logging.info(f"✅ JSON 파싱 성공")
        except json.JSONDecodeError as e:
            logging.error(f"❌ JSON 파싱 오류: {e}")
            logging.error(f"응답 내용: {response.text[:500]}")
            return None
        
        # API 응답 상태 확인
        status = data.get('status', '')
        message = data.get('message', '')
        
        logging.info(f"📋 API 상태: {status}")
        logging.info(f"📋 API 메시지: {message}")
        
        if status == '000':
            # 성공
            total_count = data.get('total_count', 0)
            logging.info(f"✅ 조회 성공! 총 {total_count}건의 공시 발견")
            return data
            
        elif status == '013':
            logging.warning("⚠️ 조회된 데이터가 없습니다.")
            return None
        elif status == '020':
            logging.error("❌ API 키가 유효하지 않습니다.")
            return None
        else:
            logging.error(f"❌ API 오류: {status} - {message}")
            return None
            
    except requests.exceptions.Timeout:
        logging.error("❌ 요청 시간 초과")
        return None
    except requests.exceptions.ConnectionError:
        logging.error("❌ 연결 오류")
        return None
    except Exception as e:
        logging.error(f"❌ 예상치 못한 오류: {e}")
        return None

def filter_executive_purchases(data):
    """임원 장내매수 공시 필터링"""
    if not data or 'list' not in data:
        return []
    
    executive_purchases = []
    target_keywords = ['임원', '장내매수', '자기주식', '취득']
    
    for item in data['list']:
        report_nm = item.get('report_nm', '').lower()
        
        # 임원 관련 키워드 검색
        if any(keyword in report_nm for keyword in target_keywords):
            executive_purchases.append(item)
            logging.info(f"🎯 발견: {item.get('corp_name')} - {item.get('report_nm')}")
    
    return executive_purchases

def send_telegram_notification(message):
    """텔레그램 알림 전송"""
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not bot_token or not chat_id:
            logging.warning("⚠️ 텔레그램 설정이 없습니다.")
            return False
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            logging.info("✅ 텔레그램 알림 전송 성공")
            return True
        else:
            logging.error(f"❌ 텔레그램 알림 전송 실패: {response.status_code}")
            return False
            
    except Exception as e:
        logging.error(f"❌ 텔레그램 알림 오류: {e}")
        return False

def main():
    """메인 실행 함수"""
    log_file = setup_logging()
    
    logging.info("=== 임원 장내매수 모니터링 시작 (수정된 버전) ===")
    logging.info(f"실행 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}")
    logging.info(f"로그 파일: {log_file}")
    
    # DART API에서 데이터 조회
    dart_data = get_dart_data()
    
    if dart_data:
        # 임원 장내매수 공시 필터링
        executive_purchases = filter_executive_purchases(dart_data)
        
        if executive_purchases:
            logging.info(f"🎉 {len(executive_purchases)}건의 임원 장내매수 공시 발견!")
            
            # 텔레그램 알림 메시지 생성
            message = f"🚨 *임원 장내매수 공시 알림*\n\n"
            message += f"📅 조회일: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}\n"
            message += f"📊 발견 건수: {len(executive_purchases)}건\n\n"
            
            for i, item in enumerate(executive_purchases[:5], 1):  # 최대 5건만 표시
                corp_name = item.get('corp_name', '')
                report_nm = item.get('report_nm', '')
                message += f"{i}. *{corp_name}*\n   `{report_nm}`\n\n"
            
            if len(executive_purchases) > 5:
                message += f"... 외 {len(executive_purchases) - 5}건 더\n\n"
            
            message += "🔍 자세한 내용은 로그를 확인하세요."
            
            # 텔레그램 알림 전송
            send_telegram_notification(message)
            
        else:
            logging.info("📭 임원 장내매수 공시가 없습니다.")
    else:
        logging.error("❌ DART 데이터 조회 실패")
    
    logging.info("=== 모니터링 완료 ===")

if __name__ == "__main__":
    main()
