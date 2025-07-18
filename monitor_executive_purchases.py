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
    log_filename = f"./logs/executive_monitor_all_{current_time.strftime('%Y%m%d_%H%M%S')}.log"
    
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
    
    # 최근 3일 데이터 수집 (더 좁은 범위로 집중)
    end_date = datetime.now(KST)
    start_date = end_date - timedelta(days=3)
    
    bgn_de = start_date.strftime('%Y%m%d')
    end_de = end_date.strftime('%Y%m%d')
    
    logging.info(f"📅 조회 기간: {bgn_de} ~ {end_de}")
    
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

def filter_executive_disclosures(data):
    """임원 관련 공시 모두 포함 (내용 확인 필요)"""
    if not data:
        return []
    
    executive_disclosures = []
    
    logging.info("🔍 임원 관련 공시 필터링 시작...")
    
    for item in data:
        report_nm = item.get('report_nm', '').lower()
        corp_name = item.get('corp_name', '')
        
        # 임원 관련 공시 모두 포함
        if '임원' in report_nm:
            # 명확히 제외할 것들만 제외
            exclude_keywords = [
                '신규선임',
                '해임',
                '사임',
                '퇴임',
                '변경',
                '정정',
                '취소',
                '임원현황',
                '의결권'
            ]
            
            # 제외 키워드 체크
            if any(keyword in report_nm for keyword in exclude_keywords):
                continue
            
            executive_disclosures.append(item)
            logging.info(f"🎯 임원 관련 공시: {corp_name} - {item.get('report_nm')}")
    
    logging.info(f"📋 필터링 완료: {len(executive_disclosures)}건의 임원 관련 공시 발견")
    return executive_disclosures

def send_telegram_notification(disclosures):
    """텔레그램 알림 전송 (수정됨)"""
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not bot_token or not chat_id:
            logging.warning("⚠️ 텔레그램 설정이 없습니다.")
            return False
        
        if not disclosures:
            logging.info("📭 알림할 공시가 없습니다.")
            return False
        
        # 메시지 생성
        message = f"🚨 *임원 관련 공시 알림*\n\n"
        message += f"📅 조회시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}\n"
        message += f"📊 발견 건수: {len(disclosures)}건\n\n"
        message += f"⚠️ *수동 확인 필요*\n"
        message += f"각 공시를 KIND에서 확인하여 장내매수 여부를 판단하세요.\n\n"
        
        for i, item in enumerate(disclosures[:10], 1):  # 최대 10건 표시
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
            
            message += f"{i}. *{corp_name}*\n"
            message += f"   📄 {report_nm}\n"
            message += f"   👤 제출인: {flr_nm}\n"
            message += f"   📅 {formatted_date}\n"
            message += f"   🔗 [KIND에서 확인](https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno={rcept_no})\n\n"
        
        if len(disclosures) > 10:
            message += f"... 외 {len(disclosures) - 10}건 더\n\n"
        
        message += "🔍 각 링크를 클릭하여 실제 장내매수 여부를 확인하세요."
        
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
    
    logging.info("=== 임원 공시 모니터링 시작 (전체 포함 버전) ===")
    logging.info(f"실행 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}")
    logging.info(f"로그 파일: {log_file}")
    
    # 1. DART 데이터 수집
    dart_data = collect_extended_dart_data()
    
    if dart_data:
        logging.info(f"✅ 총 {len(dart_data)}건의 공시 수집")
        
        # 2. 임원 관련 공시 필터링
        executive_disclosures = filter_executive_disclosures(dart_data)
        
        if executive_disclosures:
            logging.info(f"🎉 {len(executive_disclosures)}건의 임원 관련 공시 발견!")
            
            # 3. 상세 정보 출력
            logging.info("📊 발견된 임원 관련 공시 상세:")
            for i, item in enumerate(executive_disclosures, 1):
                corp_name = item.get('corp_name', '')
                report_nm = item.get('report_nm', '')
                rcept_dt = item.get('rcept_dt', '')
                flr_nm = item.get('flr_nm', '')
                rcept_no = item.get('rcept_no', '')
                
                logging.info(f"  {i}. {corp_name} ({rcept_dt})")
                logging.info(f"     📄 {report_nm}")
                logging.info(f"     👤 제출인: {flr_nm}")
                logging.info(f"     🔗 https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno={rcept_no}")
            
            # 4. 텔레그램 알림 전송
            send_telegram_notification(executive_disclosures)
            
        else:
            logging.info("📭 임원 관련 공시를 찾을 수 없습니다.")
    else:
        logging.error("❌ DART 데이터 수집 실패")
    
    logging.info("=== 모니터링 완료 ===")

if __name__ == "__main__":
    main()
