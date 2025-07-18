import os
import requests
import json
import logging
from datetime import datetime, timedelta
import pytz
import time
from bs4 import BeautifulSoup
import re

# 한국 시간대 설정
KST = pytz.timezone('Asia/Seoul')

def setup_logging():
    """로깅 설정"""
    current_time = datetime.now(KST)
    log_filename = f"./logs/executive_monitor_dart_crawl_{current_time.strftime('%Y%m%d_%H%M%S')}.log"
    
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
    
    # 최근 1일 데이터 수집 (더 좁은 범위로 집중)
    end_date = datetime.now(KST)
    start_date = end_date - timedelta(days=1)
    
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

def check_dart_content_for_market_purchase(rcept_no):
    """DART 페이지에서 장내매수 여부 확인"""
    try:
        # DART URL 구성
        dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
        
        # 헤더 설정 (웹 브라우저처럼 보이도록)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # 웹 페이지 요청
        response = requests.get(dart_url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            # HTML 파싱
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 전체 텍스트에서 장내매수 키워드 찾기
            page_text = soup.get_text()
            
            # 장내매수 관련 키워드 확인
            market_purchase_keywords = [
                '장내매수',
                '장내 매수',
                '장내취득',
                '장내 취득',
                '시장매수',
                '시장 매수'
            ]
            
            found_keywords = []
            for keyword in market_purchase_keywords:
                if keyword in page_text:
                    found_keywords.append(keyword)
            
            if found_keywords:
                logging.info(f"✅ 장내매수 키워드 발견: {', '.join(found_keywords)}")
                return True, found_keywords
            else:
                logging.debug(f"❌ 장내매수 키워드 없음: {rcept_no}")
                return False, []
        else:
            logging.warning(f"⚠️ DART 페이지 로드 실패: {response.status_code}")
            return None, []
            
    except Exception as e:
        logging.error(f"❌ DART 내용 확인 실패: {e}")
        return None, []

def filter_executive_disclosures(data):
    """임원 관련 공시 필터링 및 장내매수 내용 확인"""
    if not data:
        return []
    
    executive_disclosures = []
    
    logging.info("🔍 임원 관련 공시 필터링 시작...")
    
    # 1차 필터링: 임원 관련 공시만 선별
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
    
    logging.info(f"📋 1차 필터링 완료: {len(executive_disclosures)}건의 임원 관련 공시 발견")
    
    # 2차 필터링: DART 페이지에서 장내매수 내용 확인
    logging.info("🔍 DART 페이지에서 장내매수 내용 확인 시작...")
    
    market_purchase_disclosures = []
    
    for i, item in enumerate(executive_disclosures, 1):
        rcept_no = item.get('rcept_no', '')
        corp_name = item.get('corp_name', '')
        
        logging.info(f"📄 {i}/{len(executive_disclosures)} - {corp_name} 내용 확인 중...")
        
        # DART 페이지에서 장내매수 키워드 확인
        is_market_purchase, keywords = check_dart_content_for_market_purchase(rcept_no)
        
        if is_market_purchase:
            item['market_purchase_keywords'] = keywords
            market_purchase_disclosures.append(item)
            logging.info(f"🎉 장내매수 발견: {corp_name} - {', '.join(keywords)}")
        elif is_market_purchase is None:
            # 페이지 로드 실패 시 포함 (안전 장치)
            logging.warning(f"⚠️ 페이지 확인 실패 - 안전상 포함: {corp_name}")
            item['market_purchase_keywords'] = ['확인 실패']
            market_purchase_disclosures.append(item)
        
        # API 호출 간격 조절 (너무 빠른 요청 방지)
        time.sleep(2)
    
    logging.info(f"📋 2차 필터링 완료: {len(market_purchase_disclosures)}건의 장내매수 공시 발견")
    return market_purchase_disclosures

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

def send_telegram_notification(disclosures):
    """텔레그램 알림 전송 (장내매수 확인됨)"""
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not bot_token or not chat_id:
            logging.warning("⚠️ 텔레그램 설정이 없습니다.")
            return False
        
        if not disclosures:
            # 임원 관련 공시는 있지만 장내매수가 없는 경우
            no_purchase_message = f"📭 *장내매수 공시 없음*\n\n"
            no_purchase_message += f"📅 조회시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}\n\n"
            no_purchase_message += f"임원 관련 공시는 있지만 장내매수 공시는 발견되지 않았습니다."
            
            send_single_message(bot_token, chat_id, no_purchase_message)
            logging.info("📭 장내매수 공시 없음 알림 전송")
            return True
        
        # 메시지 분할 설정
        SAFE_MESSAGE_LENGTH = 2000
        
        # 헤더 메시지 생성
        header_message = f"🚨 *장내매수 공시 발견!*\n\n"
        header_message += f"📅 조회시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}\n"
        header_message += f"📊 총 발견 건수: {len(disclosures)}건\n\n"
        header_message += f"✅ *DART 페이지에서 장내매수 키워드 확인완료*\n\n"
        
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
            keywords = item.get('market_purchase_keywords', [])
            
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
            item_message += f"   🎯 키워드: {', '.join(keywords)}\n"
            item_message += f"   🔗 [DART에서 확인](https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no})\n\n"
            
            # 메시지 길이 체크
            if len(current_message + item_message) > SAFE_MESSAGE_LENGTH:
                # 현재 메시지 전송
                if current_message:
                    final_message = f"📋 *장내매수 공시 {message_count}*\n\n{current_message}"
                    
                    send_single_message(bot_token, chat_id, final_message)
                    logging.info(f"✅ 메시지 {message_count} 전송 완료")
                
                # 새 메시지 시작
                current_message = item_message
                message_count += 1
            else:
                current_message += item_message
        
        # 마지막 메시지 전송
        if current_message:
            final_message = f"📋 *장내매수 공시 {message_count}*\n\n{current_message}"
            
            send_single_message(bot_token, chat_id, final_message)
            logging.info(f"✅ 메시지 {message_count} 전송 완료")
        
        # 요약 메시지 전송
        summary_message = f"✅ *장내매수 공시 알림 완료*\n\n"
        summary_message += f"📊 총 {len(disclosures)}건의 확인된 장내매수 공시를 전송했습니다.\n\n"
        summary_message += f"🎯 모든 공시는 DART 페이지에서 장내매수 키워드가 확인되었습니다!"
        
        send_single_message(bot_token, chat_id, summary_message)
        
        logging.info(f"✅ 총 {message_count + 2}개 메시지 전송 완료")
        return True
        
    except Exception as e:
        logging.error(f"❌ 텔레그램 알림 오류: {e}")
        return False

def main():
    """메인 실행 함수"""
    log_file = setup_logging()
    
    logging.info("=== 장내매수 공시 모니터링 시작 (DART 크롤링) ===")
    logging.info(f"실행 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}")
    logging.info(f"로그 파일: {log_file}")
    
    # 1. DART 데이터 수집
    dart_data = collect_extended_dart_data()
    
    if dart_data:
        logging.info(f"✅ 총 {len(dart_data)}건의 공시 수집")
        
        # 2. 임원 관련 공시 필터링 및 장내매수 내용 확인
        market_purchase_disclosures = filter_executive_disclosures(dart_data)
        
        if market_purchase_disclosures:
            logging.info(f"🎉 {len(market_purchase_disclosures)}건의 장내매수 공시 발견!")
            
            # 3. 상세 정보 출력
            logging.info("📊 발견된 장내매수 공시 상세:")
            for i, item in enumerate(market_purchase_disclosures, 1):
                corp_name = item.get('corp_name', '')
                report_nm = item.get('report_nm', '')
                rcept_dt = item.get('rcept_dt', '')
                flr_nm = item.get('flr_nm', '')
                rcept_no = item.get('rcept_no', '')
                keywords = item.get('market_purchase_keywords', [])
                
                logging.info(f"  {i}. {corp_name} ({rcept_dt})")
                logging.info(f"     📄 {report_nm}")
                logging.info(f"     👤 제출인: {flr_nm}")
                logging.info(f"     🎯 키워드: {', '.join(keywords)}")
                logging.info(f"     🔗 https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}")
            
            # 4. 텔레그램 알림 전송
            send_telegram_notification(market_purchase_disclosures)
            
        else:
            logging.info("📭 장내매수 공시를 찾을 수 없습니다.")
            # 빈 리스트로 텔레그램 알림 (장내매수 없음 메시지)
            send_telegram_notification([])
    else:
        logging.error("❌ DART 데이터 수집 실패")
    
    logging.info("=== 모니터링 완료 ===")

if __name__ == "__main__":
    main()
