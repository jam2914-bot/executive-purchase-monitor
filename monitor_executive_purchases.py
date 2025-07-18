#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KIND 임원 장내매수 모니터링 시스템
한국거래소 KIND 시스템에서 임원·주요주주 특정증권등 소유상황보고서를 모니터링하고
장내매수 정보를 텔레그램으로 알림
"""

import os
import sys
import json
import time
import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional
import pytz
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import pandas as pd

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

# 로깅 설정
def setup_logging():
    """로깅 설정"""
    log_dir = '/home/user/output/logs'
    os.makedirs(log_dir, exist_ok=True)

    current_time = datetime.now(KST)
    log_filename = f"executive_monitor_{current_time.strftime('%Y%m%d_%H%M%S')}.log"
    log_path = os.path.join(log_dir, log_filename)

    # 로거 설정
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

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
    """KIND 모니터링 클래스"""

    def __init__(self):
        self.driver = None
        self.base_url = "https://kind.krx.co.kr"
        self.disclosure_url = f"{self.base_url}/disclosure/todaydisclosure.do?method=searchTodayDisclosureMain&marketType=0"

    def setup_driver(self) -> bool:
        """Chrome WebDriver 설정 (webdriver-manager 사용)"""
        try:
            # Chrome 옵션 설정
            chrome_options = Options()
            chrome_options.add_argument('--headless')  # 헤드리스 모드
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-plugins')
            chrome_options.add_argument('--disable-images')  # 이미지 로딩 비활성화
            chrome_options.add_argument('--disable-javascript')  # JavaScript 비활성화 (필요시)
            chrome_options.add_argument('--memory-pressure-off')
            chrome_options.add_argument('--max_old_space_size=4096')

            # User-Agent 설정
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

            # 먼저 시스템에 설치된 ChromeDriver 사용 시도
            try:
                service = Service('/usr/local/bin/chromedriver')
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                logging.info("시스템 ChromeDriver 사용 성공")
                return True
            except Exception as e:
                logging.warning(f"시스템 ChromeDriver 사용 실패: {e}")

            # webdriver-manager를 사용한 자동 ChromeDriver 관리
            try:
                logging.info("webdriver-manager를 사용하여 ChromeDriver 설치 중...")
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                logging.info("webdriver-manager ChromeDriver 사용 성공")
                return True
            except Exception as e:
                logging.error(f"webdriver-manager ChromeDriver 설치 실패: {e}")

            # 마지막 시도: 기본 ChromeDriver
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

    def get_today_disclosures(self) -> List[Dict]:
        """오늘의 공시 목록 가져오기"""
        try:
            if not self.driver:
                logging.error("WebDriver가 초기화되지 않았습니다")
                return []

            logging.info("KIND 웹사이트 접속 중...")
            self.driver.get(self.disclosure_url)

            # 페이지 로딩 대기
            wait = WebDriverWait(self.driver, 20)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            # 추가 로딩 시간
            time.sleep(3)

            # 페이지 소스 가져오기
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')

            # 공시 테이블 찾기
            disclosures = []

            # 공시 목록 테이블 찾기 (실제 KIND 사이트 구조에 맞게 조정 필요)
            disclosure_rows = soup.find_all('tr')

            for row in disclosure_rows:
                cells = row.find_all('td')
                if len(cells) >= 4:  # 최소 4개 컬럼이 있는 행만 처리
                    # 공시제목에서 임원·주요주주 특정증권등 소유상황보고서 찾기
                    title_cell = None
                    for cell in cells:
                        if cell.get_text(strip=True) and '임원' in cell.get_text() and '소유상황보고서' in cell.get_text():
                            title_cell = cell
                            break

                    if title_cell:
                        disclosure_info = {
                            'title': title_cell.get_text(strip=True),
                            'company_name': '',
                            'disclosure_number': '',
                            'report_date': '',
                            'link': ''
                        }

                        # 회사명, 공시번호 등 추출 (실제 구조에 맞게 조정)
                        for i, cell in enumerate(cells):
                            text = cell.get_text(strip=True)
                            if i == 0:  # 첫 번째 컬럼이 회사명이라고 가정
                                disclosure_info['company_name'] = text
                            elif '공시번호' in text or len(text) == 8:  # 공시번호 패턴
                                disclosure_info['disclosure_number'] = text
                            elif '/' in text and len(text) <= 10:  # 날짜 패턴
                                disclosure_info['report_date'] = text

                        # 상세 링크 찾기
                        link_element = row.find('a')
                        if link_element and link_element.get('href'):
                            disclosure_info['link'] = self.base_url + link_element.get('href')

                        disclosures.append(disclosure_info)

            logging.info(f"임원 소유상황보고서 {len(disclosures)}건 발견")
            return disclosures

        except Exception as e:
            logging.error(f"공시 목록 가져오기 실패: {e}")
            return []

    def check_purchase_reason(self, disclosure_link: str) -> Optional[Dict]:
        """공시 상세 페이지에서 장내매수 여부 확인"""
        try:
            if not disclosure_link:
                return None

            logging.info(f"공시 상세 페이지 확인: {disclosure_link}")
            self.driver.get(disclosure_link)

            # 페이지 로딩 대기
            time.sleep(2)

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

                # 테이블에서 정보 추출 (실제 구조에 맞게 조정 필요)
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
        results_dir = '/home/user/output/results'
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

        # KIND 모니터 초기화
        monitor = KindMonitor()

        # WebDriver 설정
        if not monitor.setup_driver():
            logging.error("WebDriver 설정 실패")
            return

        logging.info("임원 장내매수 모니터링 시작")

        # 오늘의 공시 가져오기
        disclosures = monitor.get_today_disclosures()

        if not disclosures:
            logging.info("임원 소유상황보고서 공시가 없습니다.")
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

    except Exception as e:
        logging.error(f"실행 중 오류 발생: {e}")

    finally:
        # WebDriver 종료
        if 'monitor' in locals():
            monitor.close_driver()

        logging.info("모니터링 완료")

if __name__ == "__main__":
    main()
