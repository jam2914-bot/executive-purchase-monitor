#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KIND 임원 장내매수 모니터링 시스템 (개선 버전)
한국거래소 KIND 시스템에서 임원·주요주주 특정증권등 소유상황보고서를 모니터링하고
장내매수 정보를 텔레그램으로 알림

개선사항:
- 텔레그램 테스트 메시지 전송
- 공시 조회를 어제-오늘로 제한
- 상세한 디버깅 로그
- 웹 스크래핑 로직 개선
- 강화된 에러 처리
"""

import os
import sys
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import pandas as pd
import re

# 한국 시간대 설정
KST = pytz.timezone('Asia/Seoul')

class KSTFormatter(logging.Formatter):
    """한국 시간대로 로그 포맷팅"""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, KST)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime('%Y-%m-%d %H:%M:%S KST')
        return s

def setup_logging():
    """로깅 설정"""
    # 현재 작업 디렉토리 기준으로 logs 디렉토리 생성
    log_dir = './logs'
    os.makedirs(log_dir, exist_ok=True)

    current_time = datetime.now(KST)
    log_filename = f"executive_monitor_{current_time.strftime('%Y%m%d_%H%M%S')}.log"
    log_path = os.path.join(log_dir, log_filename)

    # 로거 설정
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 기존 핸들러 제거 (중복 방지)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 파일 핸들러
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(logging.INFO)

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 포맷터 설정 (KST 시간 사용)
    formatter = KSTFormatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )

    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

class TelegramNotifier:
    """텔레그램 알림 클래스"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def send_message(self, message: str) -> bool:
        """텔레그램 메시지 전송"""
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }

            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()

            logging.info("텔레그램 메시지 전송 성공")
            return True

        except Exception as e:
            logging.error(f"텔레그램 메시지 전송 실패: {e}")
            return False

    def send_test_message(self) -> bool:
        """시스템 시작 테스트 메시지 전송"""
        current_time = datetime.now(KST)

        test_message = f"""🧪 <b>테스트 메시지</b>

📅 <b>테스트 시간:</b> {current_time.strftime('%Y-%m-%d %H:%M:%S KST')}
🤖 <b>상태:</b> 임원 매수 모니터링 봇 정상 작동

#테스트 #KIND #모니터링"""

        return self.send_message(test_message)

    def format_purchase_message(self, purchase_info: Dict) -> str:
        """장내매수 정보를 텔레그램 메시지 형식으로 포맷팅"""
        current_time = datetime.now(KST)

        message = f"""🏢 <b>임원 장내매수 알림</b>

📊 <b>회사명:</b> {purchase_info.get('company_name', 'N/A')}
👤 <b>보고자:</b> {purchase_info.get('reporter', 'N/A')}
💼 <b>직위:</b> {purchase_info.get('position', 'N/A')}
💰 <b>매수금액:</b> {purchase_info.get('purchase_amount', 'N/A')}
📅 <b>보고일자:</b> {purchase_info.get('report_date', 'N/A')}
📋 <b>공시번호:</b> {purchase_info.get('disclosure_number', 'N/A')}

⏰ <b>알림시간:</b> {current_time.strftime('%Y-%m-%d %H:%M:%S KST')}

#임원매수 #KIND #장내매수"""

        return message

class KindMonitor:
    """KIND 모니터링 클래스 (개선 버전)"""

    def __init__(self):
        self.driver = None
        self.base_url = "https://kind.krx.co.kr"
        self.disclosure_url = f"{self.base_url}/disclosure/todaydisclosure.do?method=searchTodayDisclosureMain&marketType=0"

    def setup_driver(self) -> bool:
        """Chrome WebDriver 설정"""
        try:
            # Chrome 옵션 설정
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-plugins')
            chrome_options.add_argument('--memory-pressure-off')
            chrome_options.add_argument('--max_old_space_size=4096')

            # User-Agent 설정
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

            # 시스템 ChromeDriver 사용 시도
            try:
                service = Service('/usr/local/bin/chromedriver')
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                logging.info("시스템 ChromeDriver 사용 성공")
                return True
            except Exception as e:
                logging.warning(f"시스템 ChromeDriver 사용 실패: {e}")

            # webdriver-manager 사용
            try:
                logging.info("webdriver-manager를 사용하여 ChromeDriver 설치 중...")
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                logging.info("webdriver-manager ChromeDriver 사용 성공")
                return True
            except Exception as e:
                logging.error(f"webdriver-manager ChromeDriver 설치 실패: {e}")

            # 기본 ChromeDriver 사용
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
                logging.info("기본 ChromeDriver 사용 성공")
                return True
            except Exception as e:
                logging.error(f"모든 ChromeDriver 설정 방법 실패: {e}")
                return False

        except Exception as e:
            logging.error(f"ChromeDriver 설정 중 오류 발생: {e}")
            return False

    def get_date_range(self) -> tuple:
        """어제-오늘 날짜 범위 반환"""
        today = datetime.now(KST).date()
        yesterday = today - timedelta(days=1)

        logging.info(f"공시 조회 기간: {yesterday} ~ {today}")
        return yesterday, today

    def get_disclosures_with_date_filter(self) -> List[Dict]:
        """어제-오늘 공시 목록 가져오기 (날짜 필터링)"""
        try:
            if not self.driver:
                logging.error("WebDriver가 초기화되지 않았습니다")
                return []

            yesterday, today = self.get_date_range()

            logging.info("KIND 웹사이트 접속 중...")
            self.driver.get(self.disclosure_url)

            # 페이지 로딩 대기
            wait = WebDriverWait(self.driver, 30)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            # 추가 로딩 시간
            time.sleep(5)

            # 페이지 소스 저장 (디버깅용)
            page_source = self.driver.page_source

            # HTML 구조 분석을 위한 로그
            soup = BeautifulSoup(page_source, 'html.parser')

            # 테이블 찾기 시도
            tables = soup.find_all('table')
            logging.info(f"페이지에서 발견된 테이블 수: {len(tables)}")

            # 공시 목록 찾기 (여러 방법 시도)
            disclosures = []

            # 방법 1: 일반적인 테이블 구조
            for i, table in enumerate(tables):
                rows = table.find_all('tr')
                logging.info(f"테이블 {i+1}: {len(rows)}개 행 발견")

                for j, row in enumerate(rows):
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 3:  # 최소 3개 컬럼
                        row_text = ' '.join([cell.get_text(strip=True) for cell in cells])

                        # 임원 관련 공시 찾기
                        if any(keyword in row_text for keyword in ['임원', '주요주주', '소유상황보고서', '특정증권']):
                            logging.info(f"임원 관련 공시 발견 (테이블 {i+1}, 행 {j+1}): {row_text[:100]}...")

                            disclosure_info = self.parse_disclosure_row(cells, row)
                            if disclosure_info and self.is_within_date_range(disclosure_info.get('report_date', ''), yesterday, today):
                                disclosures.append(disclosure_info)

            # 방법 2: CSS 셀렉터 사용
            if not disclosures:
                logging.info("CSS 셀렉터를 사용한 공시 검색 시도...")
                disclosure_elements = soup.select('tr, .disclosure-row, .list-row')

                for element in disclosure_elements:
                    text = element.get_text(strip=True)
                    if any(keyword in text for keyword in ['임원', '주요주주', '소유상황보고서']):
                        logging.info(f"CSS 셀렉터로 임원 공시 발견: {text[:100]}...")

                        cells = element.find_all(['td', 'th'])
                        disclosure_info = self.parse_disclosure_row(cells, element)
                        if disclosure_info and self.is_within_date_range(disclosure_info.get('report_date', ''), yesterday, today):
                            disclosures.append(disclosure_info)

            # 방법 3: 텍스트 기반 검색
            if not disclosures:
                logging.info("텍스트 기반 공시 검색 시도...")
                all_text = soup.get_text()

                # 임원 관련 키워드가 있는지 확인
                if any(keyword in all_text for keyword in ['임원', '주요주주', '소유상황보고서']):
                    logging.info("페이지에 임원 관련 키워드 발견됨")

                    # 모든 링크 요소 검사
                    links = soup.find_all('a')
                    for link in links:
                        link_text = link.get_text(strip=True)
                        if any(keyword in link_text for keyword in ['임원', '주요주주', '소유상황보고서']):
                            logging.info(f"링크에서 임원 공시 발견: {link_text}")

                            disclosure_info = {
                                'title': link_text,
                                'company_name': 'N/A',
                                'disclosure_number': 'N/A',
                                'report_date': datetime.now(KST).strftime('%Y-%m-%d'),
                                'link': self.base_url + link.get('href', '') if link.get('href') else ''
                            }
                            disclosures.append(disclosure_info)

            logging.info(f"날짜 필터링 후 임원 소유상황보고서 {len(disclosures)}건 발견")

            # 디버깅을 위한 HTML 저장
            if not disclosures:
                debug_file = f"./logs/debug_html_{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(page_source)
                logging.info(f"디버깅용 HTML 파일 저장: {debug_file}")

            return disclosures

        except Exception as e:
            logging.error(f"공시 목록 가져오기 실패: {e}")
            return []

    def parse_disclosure_row(self, cells: List, row_element) -> Optional[Dict]:
        """공시 행 파싱"""
        try:
            if len(cells) < 3:
                return None

            disclosure_info = {
                'title': '',
                'company_name': '',
                'disclosure_number': '',
                'report_date': '',
                'link': ''
            }

            # 셀 내용 추출
            for i, cell in enumerate(cells):
                text = cell.get_text(strip=True)

                if i == 0:  # 첫 번째 컬럼 (보통 회사명)
                    disclosure_info['company_name'] = text
                elif '임원' in text or '소유상황보고서' in text:
                    disclosure_info['title'] = text
                elif re.match(r'\d{4}-\d{2}-\d{2}', text) or '/' in text:  # 날짜 패턴
                    disclosure_info['report_date'] = text
                elif len(text) == 8 and text.isdigit():  # 공시번호 패턴
                    disclosure_info['disclosure_number'] = text

            # 링크 찾기
            link_element = row_element.find('a')
            if link_element and link_element.get('href'):
                href = link_element.get('href')
                if href.startswith('http'):
                    disclosure_info['link'] = href
                else:
                    disclosure_info['link'] = self.base_url + href

            return disclosure_info if disclosure_info['title'] else None

        except Exception as e:
            logging.error(f"공시 행 파싱 실패: {e}")
            return None

    def is_within_date_range(self, date_str: str, start_date, end_date) -> bool:
        """날짜가 범위 내에 있는지 확인"""
        try:
            if not date_str:
                return True  # 날짜 정보가 없으면 포함

            # 다양한 날짜 형식 처리
            date_formats = ['%Y-%m-%d', '%Y/%m/%d', '%m/%d', '%m-%d']

            for fmt in date_formats:
                try:
                    if fmt in ['%m/%d', '%m-%d']:
                        # 월/일 형식인 경우 현재 연도 추가
                        date_str_with_year = f"{datetime.now(KST).year}/{date_str}" if '/' in date_str else f"{datetime.now(KST).year}-{date_str}"
                        parsed_date = datetime.strptime(date_str_with_year, f"%Y/{fmt}" if '/' in date_str else f"%Y-{fmt}").date()
                    else:
                        parsed_date = datetime.strptime(date_str, fmt).date()

                    return start_date <= parsed_date <= end_date
                except ValueError:
                    continue

            logging.warning(f"날짜 파싱 실패: {date_str}")
            return True  # 파싱 실패 시 포함

        except Exception as e:
            logging.error(f"날짜 범위 확인 실패: {e}")
            return True

    def check_purchase_reason(self, disclosure_link: str) -> Optional[Dict]:
        """공시 상세 페이지에서 장내매수 여부 확인"""
        try:
            if not disclosure_link:
                return None

            logging.info(f"공시 상세 페이지 확인: {disclosure_link}")
            self.driver.get(disclosure_link)

            # 페이지 로딩 대기
            time.sleep(3)

            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')

            # 보고사유에서 '장내매수' 찾기
            page_text = soup.get_text()

            if '장내매수' in page_text:
                logging.info("장내매수 발견!")

                # 상세 정보 추출
                purchase_info = {
                    'company_name': '',
                    'reporter': '',
                    'position': '',
                    'purchase_amount': '',
                    'report_date': '',
                    'disclosure_number': ''
                }

                # 테이블에서 정보 추출
                tables = soup.find_all('table')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            header = cells[0].get_text(strip=True)
                            value = cells[1].get_text(strip=True)

                            if '회사명' in header or '법인명' in header:
                                purchase_info['company_name'] = value
                            elif '보고자' in header or '성명' in header:
                                purchase_info['reporter'] = value
                            elif '직위' in header or '관계' in header:
                                purchase_info['position'] = value
                            elif '매수금액' in header or '취득금액' in header:
                                purchase_info['purchase_amount'] = value
                            elif '보고일' in header or '제출일' in header:
                                purchase_info['report_date'] = value
                            elif '공시번호' in header:
                                purchase_info['disclosure_number'] = value

                return purchase_info

            return None

        except Exception as e:
            logging.error(f"공시 상세 확인 실패: {e}")
            return None

    def close_driver(self):
        """WebDriver 종료"""
        if self.driver:
            try:
                self.driver.quit()
                logging.info("WebDriver 종료 완료")
            except Exception as e:
                logging.error(f"WebDriver 종료 중 오류: {e}")

def save_results(results: List[Dict]):
    """결과를 파일로 저장"""
    try:
        # 현재 작업 디렉토리 기준으로 results 디렉토리 생성
        results_dir = './results'
        os.makedirs(results_dir, exist_ok=True)

        current_time = datetime.now(KST)
        filename = f"executive_purchases_{current_time.strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(results_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        logging.info(f"결과 저장 완료: {filepath}")

    except Exception as e:
        logging.error(f"결과 저장 실패: {e}")

def main():
    """메인 실행 함수"""
    # 로깅 설정
    logger = setup_logging()

    try:
        # 환경 변수 확인
        telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

        if not telegram_token or not telegram_chat_id:
            logging.error("텔레그램 설정이 없습니다. 환경 변수를 확인하세요.")
            return

        # 텔레그램 알림 초기화
        notifier = TelegramNotifier(telegram_token, telegram_chat_id)

        # 텔레그램 테스트 메시지 전송
        logging.info("텔레그램 테스트 메시지 전송 중...")
        if notifier.send_test_message():
            logging.info("텔레그램 테스트 메시지 전송 성공")
        else:
            logging.error("텔레그램 테스트 메시지 전송 실패")

        # KIND 모니터 초기화
        monitor = KindMonitor()

        # WebDriver 설정
        if not monitor.setup_driver():
            logging.error("WebDriver 설정 실패")
            return

        logging.info("임원 장내매수 모니터링 시작 (어제-오늘 범위)")

        # 어제-오늘 공시 가져오기
        disclosures = monitor.get_disclosures_with_date_filter()

        if not disclosures:
            logging.info("임원 소유상황보고서 공시가 없습니다.")
            # 공시가 없어도 시스템이 정상 작동했음을 알림
            no_disclosure_message = f"""📊 <b>모니터링 완료</b>

📅 <b>조회 기간:</b> 어제-오늘
📋 <b>결과:</b> 임원 소유상황보고서 공시 없음
⏰ <b>완료 시간:</b> {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}

#모니터링완료 #KIND"""
            notifier.send_message(no_disclosure_message)
            return

        # 각 공시에서 장내매수 확인
        purchase_results = []

        for disclosure in disclosures:
            if disclosure.get('link'):
                purchase_info = monitor.check_purchase_reason(disclosure['link'])
                if purchase_info:
                    purchase_results.append(purchase_info)

                    # 텔레그램 알림 전송
                    message = notifier.format_purchase_message(purchase_info)
                    notifier.send_message(message)

                    logging.info(f"장내매수 발견 및 알림 전송: {purchase_info.get('company_name', 'N/A')}")

        # 결과 저장
        if purchase_results:
            save_results(purchase_results)
            logging.info(f"총 {len(purchase_results)}건의 장내매수 발견")
        else:
            logging.info("장내매수 공시가 없습니다.")
            # 공시는 있지만 장내매수가 없는 경우 알림
            no_purchase_message = f"""📊 <b>모니터링 완료</b>

📅 <b>조회 기간:</b> 어제-오늘
📋 <b>임원 공시:</b> {len(disclosures)}건 발견
💰 <b>장내매수:</b> 없음
⏰ <b>완료 시간:</b> {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}

#모니터링완료 #KIND"""
            notifier.send_message(no_purchase_message)

    except Exception as e:
        logging.error(f"실행 중 오류 발생: {e}")

        # 오류 발생 시 텔레그램 알림
        if 'notifier' in locals():
            error_message = f"""❌ <b>시스템 오류</b>

🚨 <b>오류 내용:</b> {str(e)[:200]}...
⏰ <b>발생 시간:</b> {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}

#시스템오류 #KIND"""
            notifier.send_message(error_message)

    finally:
        # WebDriver 종료
        if 'monitor' in locals():
            monitor.close_driver()

        logging.info("모니터링 완료")

if __name__ == "__main__":
    main()
