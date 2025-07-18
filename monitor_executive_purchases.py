#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenDart API 기반 임원 장내매수 모니터링 시스템 (GitHub Actions 최적화 버전)
"""

import os
import sys
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import pytz
from pathlib import Path

# 한국 시간대 설정
KST = pytz.timezone('Asia/Seoul')

@dataclass
class ExecutiveDisclosure:
    """임원 공시 정보"""
    corp_name: str
    corp_code: str
    stock_code: str
    report_nm: str
    rcept_no: str
    flr_nm: str
    rcept_dt: str
    rm: str = ""

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
    """로깅 설정 - GitHub Actions 환경 최적화"""
    # 현재 작업 디렉토리 확인
    current_dir = Path.cwd()
    print(f"현재 작업 디렉토리: {current_dir}")

    # 로그 디렉토리 설정 (권한 문제 방지)
    log_dir = current_dir

    # GitHub Actions 환경에서는 logs 디렉토리 생성 시도
    if os.getenv('GITHUB_ACTIONS'):
        try:
            logs_dir = current_dir / 'logs'
            logs_dir.mkdir(exist_ok=True)
            log_dir = logs_dir
            print(f"로그 디렉토리 생성 성공: {log_dir}")
        except Exception as e:
            print(f"로그 디렉토리 생성 실패, 현재 디렉토리 사용: {e}")
            log_dir = current_dir

    current_time = datetime.now(KST)
    log_filename = f"dart_executive_monitor_{current_time.strftime('%Y%m%d_%H%M%S')}.log"
    log_path = log_dir / log_filename

    # 로거 설정
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 기존 핸들러 제거
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 콘솔 핸들러 (항상 설정)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = KSTFormatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러 (가능한 경우에만)
    try:
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        print(f"로그 파일 생성: {log_path}")
    except Exception as e:
        print(f"파일 로깅 설정 실패 (콘솔 로깅만 사용): {e}")

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

class OpenDartClient:
    """OpenDart API 클라이언트"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://opendart.fss.or.kr/api"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def get_disclosure_list(self, bgn_de: str, end_de: str, page_no: int = 1) -> List[Dict]:
        """공시 목록 조회"""
        url = f"{self.base_url}/list.json"
        params = {
            'crtfc_key': self.api_key,
            'bgn_de': bgn_de,
            'end_de': end_de,
            'page_no': page_no,
            'page_count': 100,
            'corp_cls': 'Y',  # 유가증권
            'sort': 'date',
            'sort_mth': 'desc'
        }

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            if data.get('status') == '000':
                return data.get('list', [])
            else:
                logging.error(f"OpenDart API 오류: {data.get('message', 'Unknown error')}")
                return []

        except Exception as e:
            logging.error(f"공시 목록 조회 실패: {e}")
            return []

    def get_executive_disclosures(self, start_date: str, end_date: str) -> List[ExecutiveDisclosure]:
        """임원 관련 공시 필터링"""
        all_disclosures = []
        page_no = 1
        max_pages = 10  # 최대 페이지 수 제한

        # 임원 관련 키워드
        executive_keywords = [
            '임원', '주요주주', '특정증권등', '소유상황보고서',
            '임원등의특정증권등소유상황보고서',
            '임원ㆍ주요주주특정증권등소유상황보고서'
        ]

        while page_no <= max_pages:
            logging.info(f"공시 목록 조회 중... 페이지 {page_no}")
            disclosures = self.get_disclosure_list(start_date, end_date, page_no)

            if not disclosures:
                break

            # 임원 관련 공시 필터링
            executive_disclosures = []
            for disclosure in disclosures:
                report_nm = disclosure.get('report_nm', '')

                if any(keyword in report_nm for keyword in executive_keywords):
                    executive_disclosures.append(ExecutiveDisclosure(
                        corp_name=disclosure.get('corp_name', ''),
                        corp_code=disclosure.get('corp_code', ''),
                        stock_code=disclosure.get('stock_code', ''),
                        report_nm=report_nm,
                        rcept_no=disclosure.get('rcept_no', ''),
                        flr_nm=disclosure.get('flr_nm', ''),
                        rcept_dt=disclosure.get('rcept_dt', ''),
                        rm=disclosure.get('rm', '')
                    ))

            all_disclosures.extend(executive_disclosures)
            logging.info(f"페이지 {page_no}: {len(executive_disclosures)}건 임원 공시 발견")

            # 다음 페이지가 없으면 중단
            if len(disclosures) < 100:
                break

            page_no += 1

        logging.info(f"총 임원 관련 공시 {len(all_disclosures)}건 발견")
        return all_disclosures

    def get_document_content(self, rcept_no: str) -> str:
        """공시 문서 내용 조회"""
        url = f"{self.base_url}/document.json"
        params = {
            'crtfc_key': self.api_key,
            'rcept_no': rcept_no
        }

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            if data.get('status') == '000':
                return data.get('body', '')
            else:
                logging.warning(f"문서 내용 조회 실패: {data.get('message', '')}")
                return ''

        except Exception as e:
            logging.error(f"문서 내용 조회 오류: {e}")
            return ''

class ExecutiveMonitor:
    """임원 매수 모니터링 메인 클래스"""

    def __init__(self, dart_client: OpenDartClient, telegram_notifier: TelegramNotifier):
        self.dart_client = dart_client
        self.telegram_notifier = telegram_notifier
        self.processed_disclosures = set()
        self.load_processed_disclosures()

    def load_processed_disclosures(self):
        """처리된 공시 목록 로드"""
        try:
            processed_file = Path.cwd() / 'processed_disclosures.json'
            if processed_file.exists():
                with open(processed_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.processed_disclosures = set(data)
                    logging.info(f"처리된 공시 {len(self.processed_disclosures)}건 로드")
        except Exception as e:
            logging.error(f"처리된 공시 목록 로드 실패: {e}")
            self.processed_disclosures = set()

    def save_processed_disclosures(self):
        """처리된 공시 목록 저장"""
        try:
            processed_file = Path.cwd() / 'processed_disclosures.json'
            with open(processed_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.processed_disclosures), f, ensure_ascii=False, indent=2)
            logging.info(f"처리된 공시 {len(self.processed_disclosures)}건 저장")
        except Exception as e:
            logging.error(f"처리된 공시 목록 저장 실패: {e}")

    def is_purchase_disclosure(self, disclosure: ExecutiveDisclosure) -> bool:
        """장내매수 공시인지 판단"""
        # 공시 제목에서 먼저 확인
        report_nm = disclosure.report_nm.lower()
        title_purchase_keywords = ['매수', '취득', '증가']

        if any(keyword in report_nm for keyword in title_purchase_keywords):
            logging.info(f"제목에서 매수 키워드 발견: {disclosure.report_nm}")
            return True

        # 공시 내용 확인 (시간이 오래 걸릴 수 있으므로 제한적으로 사용)
        try:
            content = self.dart_client.get_document_content(disclosure.rcept_no)
            if not content:
                return False

            # 장내매수 관련 키워드 확인
            purchase_keywords = [
                '장내매수', '장내취득', '시장매수', '매수거래',
                '주식매수', '증권매수', '보통주매수', '매수(+)'
            ]

            content_lower = content.lower()
            for keyword in purchase_keywords:
                if keyword.lower() in content_lower:
                    logging.info(f"내용에서 매수 키워드 발견: {keyword}")
                    return True

        except Exception as e:
            logging.error(f"문서 내용 확인 중 오류: {e}")

        return False

    def format_notification_message(self, disclosure: ExecutiveDisclosure) -> str:
        """알림 메시지 포맷팅"""
        current_time = datetime.now(KST)

        message = f"""🏢 임원 장내매수 알림

📊 회사명: {disclosure.corp_name}
📈 종목코드: {disclosure.stock_code}
👤 보고자: {disclosure.flr_nm}
📋 공시제목: {disclosure.report_nm}
📅 공시일자: {disclosure.rcept_dt}
🔗 공시번호: {disclosure.rcept_no}

⏰ 알림시간: {current_time.strftime('%Y-%m-%d %H:%M:%S KST')}

#임원매수 #DART #장내매수"""

        return message

    def process_disclosures(self, disclosures: List[ExecutiveDisclosure]) -> int:
        """공시 처리 및 알림 전송"""
        purchase_count = 0

        for i, disclosure in enumerate(disclosures, 1):
            rcept_no = disclosure.rcept_no

            # 이미 처리된 공시는 건너뛰기
            if rcept_no in self.processed_disclosures:
                logging.info(f"[{i}/{len(disclosures)}] 이미 처리된 공시: {disclosure.corp_name}")
                continue

            logging.info(f"[{i}/{len(disclosures)}] 공시 분석 중: {disclosure.corp_name} - {disclosure.report_nm}")

            # 장내매수 공시인지 확인
            if self.is_purchase_disclosure(disclosure):
                logging.info(f"장내매수 공시 발견: {disclosure.corp_name}")

                # 텔레그램 알림 전송
                message = self.format_notification_message(disclosure)
                if self.telegram_notifier.send_message(message):
                    purchase_count += 1
                    logging.info(f"알림 전송 성공: {disclosure.corp_name}")
                else:
                    logging.error(f"알림 전송 실패: {disclosure.corp_name}")

            # 처리된 공시로 표시
            self.processed_disclosures.add(rcept_no)

            # API 호출 제한을 위한 짧은 대기
            time.sleep(0.5)

        # 처리된 공시 목록 저장
        self.save_processed_disclosures()

        return purchase_count

    def run_monitoring(self, days_back: int = 2) -> Dict:
        """모니터링 실행"""
        end_date = datetime.now(KST).date()
        start_date = end_date - timedelta(days=days_back)

        start_date_str = start_date.strftime('%Y%m%d')
        end_date_str = end_date.strftime('%Y%m%d')

        logging.info(f"모니터링 시작: {start_date_str} ~ {end_date_str}")

        # 임원 관련 공시 조회
        disclosures = self.dart_client.get_executive_disclosures(start_date_str, end_date_str)

        if not disclosures:
            logging.info("임원 관련 공시가 없습니다.")
            return {
                'total_disclosures': 0,
                'purchase_disclosures': 0,
                'period': f"{start_date_str} ~ {end_date_str}"
            }

        # 공시 처리 및 알림 전송
        purchase_count = self.process_disclosures(disclosures)

        result = {
            'total_disclosures': len(disclosures),
            'purchase_disclosures': purchase_count,
            'period': f"{start_date_str} ~ {end_date_str}"
        }

        logging.info(f"모니터링 완료: 총 {len(disclosures)}건 중 {purchase_count}건 장내매수")

        return result

def main():
    """메인 실행 함수"""
    print("OpenDart API 기반 임원 매수 모니터링 시작")

    # 로깅 설정
    logger = setup_logging()

    try:
        # 환경 변수 확인
        dart_api_key = os.getenv('DART_API_KEY', '470c22abb7b7f515e219c78c7aa92b15fd5a80c0')  # 기본값 설정
        telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

        logging.info(f"환경 변수 확인:")
        logging.info(f"- DART_API_KEY: {'설정됨' if dart_api_key else '없음'}")
        logging.info(f"- TELEGRAM_BOT_TOKEN: {'설정됨' if telegram_token else '없음'}")
        logging.info(f"- TELEGRAM_CHAT_ID: {'설정됨' if telegram_chat_id else '없음'}")

        if not dart_api_key:
            logging.error("DART_API_KEY 환경 변수가 설정되지 않았습니다.")
            return

        if not telegram_token or not telegram_chat_id:
            logging.error("텔레그램 설정이 없습니다. 환경 변수를 확인하세요.")
            return

        # 클라이언트 초기화
        dart_client = OpenDartClient(dart_api_key)
        telegram_notifier = TelegramNotifier(telegram_token, telegram_chat_id)

        # 모니터링 실행
        monitor = ExecutiveMonitor(dart_client, telegram_notifier)
        result = monitor.run_monitoring(days_back=2)  # 2일간 모니터링

        # 결과 알림
        current_time = datetime.now(KST)
        summary_message = f"""📊 모니터링 완료

📅 조회 기간: {result['period']}
📋 임원 공시: {result['total_disclosures']}건
💰 장내매수: {result['purchase_disclosures']}건
⏰ 완료 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S KST')}

#모니터링완료 #DART"""

        telegram_notifier.send_message(summary_message)

        logging.info("모니터링 완료")

    except Exception as e:
        logging.error(f"실행 중 오류 발생: {e}")
        import traceback
        logging.error(f"상세 오류: {traceback.format_exc()}")

        # 오류 알림
        if 'telegram_notifier' in locals():
            error_message = f"""❌ 시스템 오류

🚨 오류 내용: {str(e)[:200]}...
⏰ 발생 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}

#시스템오류 #DART"""
            telegram_notifier.send_message(error_message)

if __name__ == "__main__":
    main()
