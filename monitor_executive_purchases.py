#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenDart API 기반 임원 장내매수 모니터링 시스템 (보안 강화 버전)
하드코딩된 API 키 제거 및 개선된 필터링 로직 적용

주요 개선사항:
- 하드코딩된 API 키 완전 제거 (환경 변수만 사용)
- pblntf_detail_ty="D002" 기반 정확한 필터링
- 공시서류 원본 분석으로 장내매수 탐지
- 강화된 디버깅 및 로깅
- 환경 변수 검증 강화
"""

import os
import sys
import json
import time
import logging
import requests
import zipfile
import io
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import pytz
from bs4 import BeautifulSoup
import pandas as pd

# 한국 시간대 설정
KST = pytz.timezone('Asia/Seoul')

@dataclass
class ExecutivePurchase:
    """임원 매수 정보 데이터 클래스"""
    company_name: str
    reporter_name: str
    position: str
    purchase_date: str
    purchase_amount: str
    purchase_shares: str
    report_date: str
    rcept_no: str
    reason: str

class KSTFormatter(logging.Formatter):
    """한국 시간대로 로그 포맷팅"""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, KST)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime('%Y-%m-%d %H:%M:%S KST')
        return s

def setup_logging() -> logging.Logger:
    """로깅 설정"""
    log_dir = './logs'
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_logging_enabled = True
    except PermissionError:
        print("Warning: Cannot create log directory, using console logging only")
        file_logging_enabled = False

    current_time = datetime.now(KST)
    log_filename = f"executive_monitor_secure_{current_time.strftime('%Y%m%d_%H%M%S')}.log"

    # 로거 설정
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 기존 핸들러 제거
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 포맷터 설정
    formatter = KSTFormatter('%(asctime)s - %(levelname)s - %(message)s')

    # 콘솔 핸들러 (항상 활성화)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러 (권한이 있을 때만)
    if file_logging_enabled:
        log_path = os.path.join(log_dir, log_filename)
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info(f"로그 파일: {log_path}")

    return logger

def validate_environment_variables() -> Tuple[str, str, str]:
    """환경 변수 검증"""
    logger = logging.getLogger()

    # 필수 환경 변수 확인
    dart_api_key = os.getenv('DART_API_KEY')
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

    # API 키 검증
    if not dart_api_key:
        logger.error("❌ DART_API_KEY 환경 변수가 설정되지 않았습니다!")
        logger.error("GitHub Secrets에서 DART_API_KEY를 설정해주세요.")
        raise ValueError("DART_API_KEY 환경 변수 필수")

    if len(dart_api_key) != 40:
        logger.error(f"❌ DART_API_KEY 형식이 올바르지 않습니다. (길이: {len(dart_api_key)}, 필요: 40)")
        raise ValueError("DART_API_KEY 형식 오류")

    # 텔레그램 설정 확인
    if not telegram_token:
        logger.error("❌ TELEGRAM_BOT_TOKEN 환경 변수가 설정되지 않았습니다!")
        raise ValueError("TELEGRAM_BOT_TOKEN 환경 변수 필수")

    if not telegram_chat_id:
        logger.error("❌ TELEGRAM_CHAT_ID 환경 변수가 설정되지 않았습니다!")
        raise ValueError("TELEGRAM_CHAT_ID 환경 변수 필수")

    # 마스킹된 키 정보 로그
    masked_key = dart_api_key[:8] + "*" * 24 + dart_api_key[-8:]
    logger.info(f"✅ DART API 키: {masked_key}")
    logger.info(f"✅ 텔레그램 토큰: {telegram_token[:10]}***")
    logger.info(f"✅ 텔레그램 채팅ID: {telegram_chat_id}")

    return dart_api_key, telegram_token, telegram_chat_id

class TelegramNotifier:
    """텔레그램 알림 클래스"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.logger = logging.getLogger()

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

            self.logger.info("✅ 텔레그램 메시지 전송 성공")
            return True

        except Exception as e:
            self.logger.error(f"❌ 텔레그램 메시지 전송 실패: {e}")
            return False

    def format_purchase_message(self, purchase: ExecutivePurchase) -> str:
        """장내매수 정보를 텔레그램 메시지 형식으로 포맷팅"""
        current_time = datetime.now(KST)

        message = f"""🏢 <b>임원 장내매수 탐지!</b>

📊 <b>회사명:</b> {purchase.company_name}
👤 <b>보고자:</b> {purchase.reporter_name}
💼 <b>직위:</b> {purchase.position}
📅 <b>매수일자:</b> {purchase.purchase_date}
💰 <b>매수주식수:</b> {purchase.purchase_shares}
💵 <b>매수금액:</b> {purchase.purchase_amount}
📋 <b>보고사유:</b> {purchase.reason}
📋 <b>공시번호:</b> {purchase.rcept_no}

⏰ <b>탐지시간:</b> {current_time.strftime('%Y-%m-%d %H:%M:%S KST')}

#임원매수 #장내매수 #OpenDart"""

        return message

    def send_completion_message(self, total_disclosures: int, executive_disclosures: int, purchases: int) -> bool:
        """모니터링 완료 메시지 전송"""
        current_time = datetime.now(KST)

        message = f"""📊 <b>모니터링 완료 (보안 강화 버전)</b>

📅 <b>조회 기간:</b> 최근 3일
📋 <b>전체 공시:</b> {total_disclosures}건
👥 <b>임원 공시:</b> {executive_disclosures}건
💰 <b>장내매수:</b> {purchases}건
⏰ <b>완료 시간:</b> {current_time.strftime('%Y-%m-%d %H:%M:%S KST')}

🔒 <b>보안 개선:</b> API 키 하드코딩 제거
🎯 <b>정확도 개선:</b> D002 분류 코드 기반 필터링

#모니터링완료 #OpenDart #보안강화"""

        return self.send_message(message)

class OpenDartClient:
    """OpenDart API 클라이언트"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://opendart.fss.or.kr/api"
        self.logger = logging.getLogger()

    def test_api_key(self) -> bool:
        """API 키 유효성 테스트"""
        try:
            url = f"{self.base_url}/list.json"
            params = {
                'crtfc_key': self.api_key,
                'bgn_de': '20250101',
                'end_de': '20250101',
                'page_no': 1,
                'page_count': 1
            }

            response = requests.get(url, params=params, timeout=30)
            data = response.json()

            if data.get('status') == '000':
                self.logger.info("✅ API 키 유효성 확인 완료")
                return True
            else:
                self.logger.error(f"❌ API 키 오류: {data.get('message', 'Unknown error')}")
                return False

        except Exception as e:
            self.logger.error(f"❌ API 키 테스트 실패: {e}")
            return False

    def get_disclosures(self, start_date: str, end_date: str) -> List[Dict]:
        """공시 목록 조회"""
        try:
            url = f"{self.base_url}/list.json"
            params = {
                'crtfc_key': self.api_key,
                'bgn_de': start_date,
                'end_de': end_date,
                'page_no': 1,
                'page_count': 100
            }

            self.logger.info(f"📡 공시 목록 조회: {start_date} ~ {end_date}")
            response = requests.get(url, params=params, timeout=30)

            self.logger.info(f"📊 API 응답 상태: {response.status_code}")

            if response.status_code != 200:
                self.logger.error(f"❌ API 호출 실패: HTTP {response.status_code}")
                return []

            data = response.json()
            status = data.get('status', 'unknown')
            message = data.get('message', 'No message')

            self.logger.info(f"📊 API 응답 상태 코드: {status}")
            self.logger.info(f"📊 API 응답 메시지: {message}")

            if status != '000':
                self.logger.error(f"❌ API 오류: {message}")
                return []

            disclosures = data.get('list', [])
            self.logger.info(f"📊 전체 공시 건수: {len(disclosures)}건")

            return disclosures

        except Exception as e:
            self.logger.error(f"❌ 공시 목록 조회 실패: {e}")
            return []

    def filter_executive_disclosures(self, disclosures: List[Dict]) -> List[Dict]:
        """임원 관련 공시 필터링 (개선된 로직)"""
        executive_disclosures = []

        for disclosure in disclosures:
            # 방법 1: 공시 분류 코드 확인 (우선순위)
            pblntf_detail_ty = disclosure.get('pblntf_detail_ty', '')
            if pblntf_detail_ty == 'D002':  # 임원ㆍ주요주주특정증권등소유상황보고서
                executive_disclosures.append(disclosure)
                self.logger.debug(f"✅ D002 분류로 탐지: {disclosure.get('corp_name', 'N/A')}")
                continue

            # 방법 2: 공시명 키워드 확인 (보조)
            report_nm = disclosure.get('report_nm', '')
            executive_keywords = [
                '임원', '주요주주', '특정증권등', '소유상황보고서',
                '임원ㆍ주요주주', '특정증권등소유상황'
            ]

            if any(keyword in report_nm for keyword in executive_keywords):
                executive_disclosures.append(disclosure)
                self.logger.debug(f"✅ 키워드로 탐지: {disclosure.get('corp_name', 'N/A')} - {report_nm}")

        self.logger.info(f"👥 임원 관련 공시: {len(executive_disclosures)}건")

        # 상위 5건 로그 출력
        for i, disclosure in enumerate(executive_disclosures[:5]):
            corp_name = disclosure.get('corp_name', 'N/A')
            report_nm = disclosure.get('report_nm', 'N/A')
            rcept_dt = disclosure.get('rcept_dt', 'N/A')
            self.logger.info(f"  {i+1}. {corp_name} - {report_nm} ({rcept_dt})")

        if len(executive_disclosures) > 5:
            self.logger.info(f"  ... 외 {len(executive_disclosures) - 5}건")

        return executive_disclosures

    def download_document(self, rcept_no: str) -> Optional[bytes]:
        """공시서류 원본파일 다운로드"""
        try:
            url = f"{self.base_url}/document.json"
            params = {
                'crtfc_key': self.api_key,
                'rcept_no': rcept_no
            }

            self.logger.debug(f"📄 공시서류 다운로드: {rcept_no}")
            response = requests.get(url, params=params, timeout=60)

            if response.status_code == 200:
                return response.content
            else:
                self.logger.warning(f"⚠️ 공시서류 다운로드 실패: {rcept_no} (HTTP {response.status_code})")
                return None

        except Exception as e:
            self.logger.error(f"❌ 공시서류 다운로드 오류: {rcept_no} - {e}")
            return None

    def analyze_document_for_purchases(self, document_content: bytes, corp_name: str, rcept_no: str) -> List[ExecutivePurchase]:
        """공시서류에서 장내매수 정보 분석"""
        purchases = []

        try:
            # ZIP 파일 압축 해제
            with zipfile.ZipFile(io.BytesIO(document_content), 'r') as zip_ref:
                for file_name in zip_ref.namelist():
                    if file_name.endswith(('.html', '.xml')):
                        try:
                            # 다양한 인코딩으로 시도
                            file_content = None
                            for encoding in ['utf-8', 'euc-kr', 'cp949']:
                                try:
                                    file_content = zip_ref.read(file_name).decode(encoding)
                                    break
                                except UnicodeDecodeError:
                                    continue

                            if not file_content:
                                self.logger.warning(f"⚠️ 파일 인코딩 실패: {file_name}")
                                continue

                            # HTML/XML 파싱
                            soup = BeautifulSoup(file_content, 'html.parser')
                            text = soup.get_text()

                            # 장내매수 패턴 탐지
                            purchase_patterns = [
                                r'장내매수\s*\(?\+?\)?',
                                r'장내\s*매수',
                                r'매수\s*\(?\+?\)?',
                                r'취득.*장내',
                                r'매매.*매수',
                                r'거래.*매수'
                            ]

                            purchase_found = False
                            for pattern in purchase_patterns:
                                if re.search(pattern, text, re.IGNORECASE):
                                    purchase_found = True
                                    break

                            if purchase_found:
                                self.logger.info(f"💰 장내매수 탐지: {corp_name}")

                                # 상세 정보 추출
                                purchase = self.extract_purchase_details(text, corp_name, rcept_no)
                                if purchase:
                                    purchases.append(purchase)

                        except Exception as e:
                            self.logger.error(f"❌ 파일 분석 오류: {file_name} - {e}")
                            continue

        except Exception as e:
            self.logger.error(f"❌ 문서 분석 실패: {rcept_no} - {e}")

        return purchases

    def extract_purchase_details(self, text: str, corp_name: str, rcept_no: str) -> Optional[ExecutivePurchase]:
        """텍스트에서 매수 상세 정보 추출"""
        try:
            # 보고자명 추출
            reporter_patterns = [
                r'보고자.*?성명.*?([가-힣]+)',
                r'성명.*?([가-힣]{2,4})',
                r'보고자.*?([가-힣]{2,4})'
            ]

            reporter_name = "N/A"
            for pattern in reporter_patterns:
                match = re.search(pattern, text)
                if match:
                    reporter_name = match.group(1)
                    break

            # 직위 추출
            position_patterns = [
                r'직위.*?([가-힣]+(?:이사|임원|대표|사장|부장|차장))',
                r'관계.*?([가-힣]+(?:이사|임원|대표|사장))',
                r'(등기임원|비등기임원|사내이사|사외이사)'
            ]

            position = "N/A"
            for pattern in position_patterns:
                match = re.search(pattern, text)
                if match:
                    position = match.group(1)
                    break

            # 매수일자 추출
            date_patterns = [
                r'(\d{4})[.-](\d{1,2})[.-](\d{1,2})',
                r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일'
            ]

            purchase_date = "N/A"
            for pattern in date_patterns:
                match = re.search(pattern, text)
                if match:
                    year, month, day = match.groups()
                    purchase_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    break

            # 매수주식수 추출
            shares_patterns = [
                r'(\d{1,3}(?:,\d{3})*)\s*주',
                r'주식수.*?(\d{1,3}(?:,\d{3})*)',
                r'(\d+)\s*주식'
            ]

            purchase_shares = "N/A"
            for pattern in shares_patterns:
                match = re.search(pattern, text)
                if match:
                    purchase_shares = match.group(1) + "주"
                    break

            # 매수금액 추출
            amount_patterns = [
                r'(\d{1,3}(?:,\d{3})*)\s*원',
                r'금액.*?(\d{1,3}(?:,\d{3})*)',
                r'(\d+)\s*백만원'
            ]

            purchase_amount = "N/A"
            for pattern in amount_patterns:
                match = re.search(pattern, text)
                if match:
                    purchase_amount = match.group(1) + "원"
                    break

            # 보고사유 추출
            reason_patterns = [
                r'보고사유.*?([가-힣\(\)\+\-\s]+)',
                r'변동사유.*?([가-힣\(\)\+\-\s]+)',
                r'취득사유.*?([가-힣\(\)\+\-\s]+)'
            ]

            reason = "장내매수"
            for pattern in reason_patterns:
                match = re.search(pattern, text)
                if match:
                    reason = match.group(1).strip()
                    break

            return ExecutivePurchase(
                company_name=corp_name,
                reporter_name=reporter_name,
                position=position,
                purchase_date=purchase_date,
                purchase_amount=purchase_amount,
                purchase_shares=purchase_shares,
                report_date=datetime.now(KST).strftime('%Y-%m-%d'),
                rcept_no=rcept_no,
                reason=reason
            )

        except Exception as e:
            self.logger.error(f"❌ 상세 정보 추출 실패: {e}")
            return None

def save_results(purchases: List[ExecutivePurchase]) -> None:
    """결과를 파일로 저장"""
    try:
        results_dir = './results'
        os.makedirs(results_dir, exist_ok=True)

        current_time = datetime.now(KST)
        filename = f"executive_purchases_{current_time.strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(results_dir, filename)

        # JSON 직렬화 가능한 형태로 변환
        results = []
        for purchase in purchases:
            results.append({
                'company_name': purchase.company_name,
                'reporter_name': purchase.reporter_name,
                'position': purchase.position,
                'purchase_date': purchase.purchase_date,
                'purchase_amount': purchase.purchase_amount,
                'purchase_shares': purchase.purchase_shares,
                'report_date': purchase.report_date,
                'rcept_no': purchase.rcept_no,
                'reason': purchase.reason
            })

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        logging.getLogger().info(f"💾 결과 저장 완료: {filepath}")

    except Exception as e:
        logging.getLogger().error(f"❌ 결과 저장 실패: {e}")

def main():
    """메인 실행 함수"""
    # 로깅 설정
    logger = setup_logging()

    try:
        logger.info("=== 임원 장내매수 모니터링 시작 (보안 강화 버전) ===")
        logger.info(f"실행 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}")

        # 환경 변수 검증
        dart_api_key, telegram_token, telegram_chat_id = validate_environment_variables()

        # OpenDart 클라이언트 초기화
        dart_client = OpenDartClient(dart_api_key)

        # API 키 유효성 테스트
        if not dart_client.test_api_key():
            logger.error("❌ API 키가 유효하지 않습니다. 새로운 키를 발급받아 주세요.")
            return

        # 텔레그램 알림 초기화
        notifier = TelegramNotifier(telegram_token, telegram_chat_id)

        # 날짜 범위 설정 (최근 3일)
        end_date = datetime.now(KST).date()
        start_date = end_date - timedelta(days=2)

        start_date_str = start_date.strftime('%Y%m%d')
        end_date_str = end_date.strftime('%Y%m%d')

        logger.info(f"📅 조회 기간: {start_date_str} ~ {end_date_str}")

        # 공시 목록 조회
        disclosures = dart_client.get_disclosures(start_date_str, end_date_str)

        if not disclosures:
            logger.warning("⚠️ 조회된 공시가 없습니다.")
            notifier.send_completion_message(0, 0, 0)
            return

        # 임원 관련 공시 필터링
        executive_disclosures = dart_client.filter_executive_disclosures(disclosures)

        if not executive_disclosures:
            logger.info("📋 임원 관련 공시가 없습니다.")
            notifier.send_completion_message(len(disclosures), 0, 0)
            return

        # 각 공시에서 장내매수 분석
        all_purchases = []

        for disclosure in executive_disclosures:
            corp_name = disclosure.get('corp_name', 'N/A')
            rcept_no = disclosure.get('rcept_no', '')

            logger.info(f"🔍 분석 중: {corp_name} ({rcept_no})")

            # 공시서류 다운로드
            document_content = dart_client.download_document(rcept_no)

            if document_content:
                # 장내매수 분석
                purchases = dart_client.analyze_document_for_purchases(
                    document_content, corp_name, rcept_no
                )

                if purchases:
                    all_purchases.extend(purchases)

                    # 텔레그램 알림 전송
                    for purchase in purchases:
                        message = notifier.format_purchase_message(purchase)
                        notifier.send_message(message)
                        time.sleep(1)  # API 제한 방지

        # 결과 저장
        if all_purchases:
            save_results(all_purchases)
            logger.info(f"🎉 총 {len(all_purchases)}건의 장내매수 탐지!")
        else:
            logger.info("💰 장내매수가 발견되지 않았습니다.")

        # 완료 알림
        notifier.send_completion_message(
            len(disclosures), 
            len(executive_disclosures), 
            len(all_purchases)
        )

        logger.info("=== 모니터링 완료 ===")

    except Exception as e:
        logger.error(f"❌ 실행 중 오류 발생: {e}")

        # 오류 발생 시 텔레그램 알림
        if 'notifier' in locals():
            error_message = f"""❌ <b>시스템 오류 (보안 강화 버전)</b>

🚨 <b>오류 내용:</b> {str(e)[:200]}...
⏰ <b>발생 시간:</b> {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}

🔧 <b>해결 방안:</b>
1. DART_API_KEY 환경 변수 확인
2. 텔레그램 토큰 및 채팅ID 확인
3. 네트워크 연결 상태 확인

#시스템오류 #보안강화"""
            notifier.send_message(error_message)

if __name__ == "__main__":
    main()
