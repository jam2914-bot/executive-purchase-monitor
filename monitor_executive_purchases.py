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
    current_time = datetime.now(KST)
    log_filename = f"./logs/executive_monitor_improved_{current_time.strftime('%Y%m%d_%H%M%S')}.log"
    
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

def collect_extended_dart_data():
    """확장된 기간의 DART 데이터 수집"""
    api_key = os.getenv('DART_API_KEY')
    if not api_key:
        logging.error("❌ DART_API_KEY 환경변수가 설정되지 않았습니다.")
        return []
    
    # API 키 마스킹하여 로그 출력
    masked_key = f"{api_key[:8]}{'*' * 24}{api_key[-8:]}"
    logging.info(f"✅ DART API 키: {masked_key}")
    
    # 최근 1주일 데이터 수집
    end_date = datetime.now(KST)
    start_date = end_date - timedelta(days=7)
    
    bgn_de = start_date.strftime('%Y%m%d')
    end_de = end_date.strftime('%Y%m%d')
    
    logging.info(f"📅 확장된 조회 기간: {bgn_de} ~ {end_de}")
    
    all_data = []
    
    # 여러 페이지 수집
    for page in range(1, 6):  # 최대 5페이지
        params = {
            'crtfc_key': api_key,
            'bgn_de': bgn_de,
            'end_de': end_de,
            'page_no': page,
            'page_count': 100
        }
        
        try:
            logging.info(f"📡 페이지 {page} 데이터 수집 중...")
            response = requests.get(
                "https://opendart.fss.or.kr/api/list.json", 
                params=params, 
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('status', '')
                
                if status == '000':
                    page_data = data.get('list', [])
                    all_data.extend(page_data)
                    logging.info(f"✅ 페이지 {page}: {len(page_data)}건 수집")
                    
                    # 마지막 페이지 체크
                    if len(page_data) < 100:
                        logging.info(f"📄 마지막 페이지 {page} 도달")
                        break
                else:
                    logging.warning(f"⚠️ 페이지 {page} 조회 실패: {status}")
                    break
            else:
                logging.error(f"❌ 페이지 {page} HTTP 오류: {response.status_code}")
                break
                
        except Exception as e:
            logging.error(f"❌ 페이지 {page} 수집 실패: {e}")
            break
        
        # API 호출 간격 조절
        time.sleep(0.5)
    
    logging.info(f"📊 총 {len(all_data)}건의 공시 수집 완료")
    return all_data

def filter_real_market_purchases(data):
    """실제 장내매수 공시만 정확하게 필터링"""
    if not data:
        return []
    
    market_purchases = []
    
    # 장내매수 키워드 (우선순위 높음)
    purchase_keywords = [
        '장내매수',
        '장내취득', 
        '시장매수',
        '시장취득'
    ]
    
    # 제외할 키워드 (우선순위 높음)
    exclude_keywords = [
        '장내매도',
        '장외매수',
        '장외매도',
        '증여',
        '대여',
        '신규선임',
        '행사가액조정',
        '행사',
        '전환',
        '배당',
        '분할',
        '합병',
        '매도',
        '소각',
        '상속',
        '변경',
        '정정',
        '취소'
    ]
    
    logging.info("🔍 장내매수 공시 필터링 시작...")
    
    for item in data:
        report_nm = item.get('report_nm', '').lower()
        corp_name = item.get('corp_name', '')
        
        # 1. 먼저 제외할 키워드 체크
        if any(keyword in report_nm for keyword in exclude_keywords):
            continue
            
        # 2. 장내매수 키워드 체크
        if any(keyword in report_nm for keyword in purchase_keywords):
            market_purchases.append(item)
            logging.info(f"🎯 장내매수 발견: {corp_name} - {item.get('report_nm')}")
            
        # 3. 임원 관련 공시에서 추가 분석
        elif '임원' in report_nm and '매수' in report_nm:
            market_purchases.append(item)
            logging.info(f"🎯 임원 매수 발견: {corp_name} - {item.get('report_nm')}")
    
    logging.info(f"📋 필터링 완료: {len(market_purchases)}건의 장내매수 공시 발견")
    return market_purchases

def send_telegram_notification(purchases):
    """텔레그램 알림 전송"""
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not bot_token or not chat_id:
            logging.warning("⚠️ 텔레그램 설정이 없습니다.")
            return False
        
        if not purchases:
            logging.info("📭 알림할 장내매수 공시가 없습니다.")
            return False
        
        # 메시지 생성
        message = f"🚨 *임원 장내매수 공시 알림*\n\n"
        message += f"📅 조회시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}\n"
        message += f"📊 발견 건수: {len(purchases)}건\n\n"
        
        for i, item in enumerate(purchases[:5], 1):  # 최대 5건만 표시
            corp_name = item.get('corp_name', '')
            report_nm = item.get('report_nm', '')
            rcept_dt = item.get('rcept_dt', '')
            
            # 날짜 포맷팅
            if rcept_dt and len(rcept_dt) == 8:
                formatted_date = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}"
            else:
                formatted_date = rcept_dt
            
            message += f"{i}. *{corp_name}*\n"
            message += f"   📄 {report_nm}\n"
            message += f"   📅 {formatted_date}\n\n"
        
        if len(purchases) > 5:
            message += f"... 외 {len(purchases) - 5}건 더\n\n"
        
        message += "🔍 자세한 내용은 로그를 확인하세요."
        
        # 텔레그램 전송
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
    
    logging.info("=== 임원 장내매수 모니터링 시작 (개선된 버전) ===")
    logging.info(f"실행 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}")
    logging.info(f"로그 파일: {log_file}")
    
    # 1. 확장된 기간으로 DART 데이터 수집
    extended_data = collect_extended_dart_data()
    
    if extended_data:
        logging.info(f"✅ 총 {len(extended_data)}건의 공시 수집")
        
        # 2. 실제 장내매수 공시 필터링
        market_purchases = filter_real_market_purchases(extended_data)
        
        if market_purchases:
            logging.info(f"🎉 {len(market_purchases)}건의 실제 장내매수 공시 발견!")
            
            # 3. 상세 정보 출력
            logging.info("📊 발견된 장내매수 공시 상세:")
            for i, item in enumerate(market_purchases, 1):
                corp_name = item.get('corp_name', '')
                report_nm = item.get('report_nm', '')
                rcept_dt = item.get('rcept_dt', '')
                flr_nm = item.get('flr_nm', '')
                
                logging.info(f"  {i}. {corp_name} ({rcept_dt})")
                logging.info(f"     📄 {report_nm}")
                logging.info(f"     👤 제출인: {flr_nm}")
            
            # 4. 텔레그램 알림 전송
            send_telegram_notification(market_purchases)
            
        else:
            logging.info("📭 실제 장내매수 공시를 찾을 수 없습니다.")
            logging.info("💡 이는 정상적인 상황입니다. 임원 장내매수는 자주 발생하지 않습니다.")
    else:
        logging.error("❌ DART 데이터 수집 실패")
    
    logging.info("=== 모니터링 완료 ===")

if __name__ == "__main__":
    main()
