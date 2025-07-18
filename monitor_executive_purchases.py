#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenDart API 공시서류 원본 분석 기반 임원 장내매수 모니터링 시스템 V2
- 공시서류 원본파일 다운로드 및 분석
- HTML/XML 파싱을 통한 정확한 장내매수 탐지
- 다중 패턴 매칭으로 누락 방지
- 상세한 매수 정보 추출 (매수량, 매수일자, 보고자 등)
"""

import os
import sys
import json
import time
import logging
import requests
import zipfile
import tempfile
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import pytz
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

# 한국 시간대 설정
KST = pytz.timezone('Asia/Seoul')

@dataclass
class ExecutivePurchase:
    """임원 매수 정보 데이터 클래스"""
    company_name: str
    company_code: str
    reporter_name: str
    position: str
    purchase_date: str
    purchase_amount: str
    purchase_shares: str
    report_date: str
    disclosure_number: str
    purchase_reason: str
    ownership_before: str
    ownership_after: str

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
    """로깅 설정 - GitHub Actions 환경 호환"""
    try:
        log_dir = Path('./logs')
        log_dir.mkdir(exist_ok=True)
        file_logging_enabled = True
    except (PermissionError, OSError):
        print("Warning: Cannot create log directory, using console logging only")
        file_logging_enabled = False

    # 로거 설정
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 기존 핸들러 제거
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 콘솔 핸들러 (항상 활성화)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 포맷터 설정
    formatter = KSTFormatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러 (가능한 경우만)
    if file_logging_enabled:
        try:
            current_time = datetime.now(KST)
            log_filename = f"executive_monitor_v2_{current_time.strftime('%Y%m%d_%H%M%S')}.log"
            log_path = log_dir / log_filename

            file_handler = logging.FileHandler(log_path, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

            logging.info(f"로그 파일: {log_path}")
        except Exception as e:
            logging.warning(f"파일 로깅 설정 실패: {e}")

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

    def format_purchase_message(self, purchase: ExecutivePurchase) -> str:
        """장내매수 정보를 텔레그램 메시지 형식으로 포맷팅"""
        current_time = datetime.now(KST)

        message = f"""🏢 <b>임원 장내매수 발견!</b>

📊 <b>회사명:</b> {purchase.company_name}({purchase.company_code})
👤 <b>보고자:</b> {purchase.reporter_name}
💼 <b>직위:</b> {purchase.position}
📅 <b>매수일자:</b> {purchase.purchase_date}
💰 <b>매수주식수:</b> {purchase.purchase_shares}주
💵 <b>매수금액:</b> {purchase.purchase_amount}
📋 <b>매수사유:</b> {purchase.purchase_reason}
📈 <b>소유비율:</b> {purchase.ownership_before} → {purchase.ownership_after}
📄 <b>공시번호:</b> {purchase.disclosure_number}
📅 <b>보고일자:</b> {purchase.report_date}

⏰ <b>탐지시간:</b> {current_time.strftime('%Y-%m-%d %H:%M:%S KST')}

#임원매수 #장내매수 #OpenDart #원본분석"""

        return message

class OpenDartDocumentAnalyzer:
    """OpenDart API 공시서류 원본 분석 클래스"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://opendart.fss.or.kr/api"
        self.session = requests.Session()

        # 장내매수 탐지 패턴들
        self.purchase_patterns = [
            r'장내매수',
            r'장내\s*매수',
            r'거래소\s*매수',
            r'시장\s*매수',
            r'매수\s*거래',
            r'취득\s*\(매수\)',
            r'매수\s*취득',
            r'보통주\s*매수',
            r'주식\s*매수',
            r'증권\s*매수'
        ]

        # 매수 관련 키워드들
        self.purchase_keywords = [
            '장내매수', '거래소매수', '시장매수', '매수거래', '매수취득',
            '보통주매수', '주식매수', '증권매수', '취득(매수)', '매수(+)'
        ]

    def get_executive_disclosures(self, start_date: str, end_date: str) -> List[Dict]:
        """임원 공시 목록 조회"""
        try:
            url = f"{self.base_url}/list.json"
            params = {
                'crtfc_key': self.api_key,
                'bgn_de': start_date.replace('-', ''),
                'end_de': end_date.replace('-', ''),
                'pblntf_ty': 'A',  # 정기공시
                'corp_cls': 'Y',   # 유가증권
                'page_no': 1,
                'page_count': 100
            }

            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            if data.get('status') != '000':
                logging.error(f"API 오류: {data.get('message', 'Unknown error')}")
                return []

            # 임원 관련 공시 필터링
            executive_disclosures = []
            for item in data.get('list', []):
                report_name = item.get('report_nm', '')
                if any(keyword in report_name for keyword in ['임원', '주요주주', '소유상황보고서']):
                    executive_disclosures.append(item)
                    logging.info(f"임원 공시 발견: {item.get('corp_name')} - {report_name}")

            logging.info(f"임원 관련 공시 {len(executive_disclosures)}건 발견")
            return executive_disclosures

        except Exception as e:
            logging.error(f"공시 목록 조회 실패: {e}")
            return []

    def download_document(self, rcept_no: str) -> Optional[str]:
        """공시서류 원본파일 다운로드"""
        try:
            url = f"{self.base_url}/document.json"
            params = {
                'crtfc_key': self.api_key,
                'rcept_no': rcept_no
            }

            logging.info(f"공시서류 다운로드 시작: {rcept_no}")

            response = self.session.get(url, params=params, timeout=60)
            response.raise_for_status()

            # ZIP 파일을 임시 디렉토리에 저장
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
                temp_file.write(response.content)
                temp_zip_path = temp_file.name

            # ZIP 파일 압축 해제
            extract_dir = tempfile.mkdtemp()

            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            # 압축 해제된 파일들에서 HTML/XML 파일 찾기
            document_content = ""
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    if file.endswith(('.html', '.htm', '.xml')):
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                document_content += content + "\n"
                        except UnicodeDecodeError:
                            try:
                                with open(file_path, 'r', encoding='euc-kr') as f:
                                    content = f.read()
                                    document_content += content + "\n"
                            except Exception as e:
                                logging.warning(f"파일 읽기 실패: {file_path} - {e}")

            # 임시 파일들 정리
            os.unlink(temp_zip_path)
            import shutil
            shutil.rmtree(extract_dir)

            if document_content:
                logging.info(f"공시서류 다운로드 완료: {len(document_content)} 문자")
                return document_content
            else:
                logging.warning(f"공시서류에서 내용을 찾을 수 없음: {rcept_no}")
                return None

        except Exception as e:
            logging.error(f"공시서류 다운로드 실패 {rcept_no}: {e}")
            return None

    def analyze_document_for_purchases(self, document_content: str, disclosure_info: Dict) -> List[ExecutivePurchase]:
        """공시서류에서 장내매수 정보 분석"""
        try:
            purchases = []

            # HTML 파싱
            soup = BeautifulSoup(document_content, 'html.parser')
            text_content = soup.get_text()

            # 장내매수 패턴 탐지
            purchase_found = False
            purchase_reason = ""

            for pattern in self.purchase_patterns:
                if re.search(pattern, text_content, re.IGNORECASE):
                    purchase_found = True
                    purchase_reason = pattern
                    logging.info(f"장내매수 패턴 발견: {pattern}")
                    break

            if not purchase_found:
                # 키워드 기반 탐지
                for keyword in self.purchase_keywords:
                    if keyword in text_content:
                        purchase_found = True
                        purchase_reason = keyword
                        logging.info(f"장내매수 키워드 발견: {keyword}")
                        break

            if purchase_found:
                # 상세 정보 추출
                purchase_info = self.extract_purchase_details(text_content, soup, disclosure_info)
                purchase_info['purchase_reason'] = purchase_reason

                purchase = ExecutivePurchase(
                    company_name=purchase_info.get('company_name', disclosure_info.get('corp_name', 'N/A')),
                    company_code=purchase_info.get('company_code', disclosure_info.get('stock_code', 'N/A')),
                    reporter_name=purchase_info.get('reporter_name', 'N/A'),
                    position=purchase_info.get('position', 'N/A'),
                    purchase_date=purchase_info.get('purchase_date', 'N/A'),
                    purchase_amount=purchase_info.get('purchase_amount', 'N/A'),
                    purchase_shares=purchase_info.get('purchase_shares', 'N/A'),
                    report_date=disclosure_info.get('rcept_dt', 'N/A'),
                    disclosure_number=disclosure_info.get('rcept_no', 'N/A'),
                    purchase_reason=purchase_reason,
                    ownership_before=purchase_info.get('ownership_before', 'N/A'),
                    ownership_after=purchase_info.get('ownership_after', 'N/A')
                )

                purchases.append(purchase)
                logging.info(f"장내매수 정보 추출 완료: {purchase.company_name} - {purchase.reporter_name}")

            return purchases

        except Exception as e:
            logging.error(f"공시서류 분석 실패: {e}")
            return []

    def extract_purchase_details(self, text_content: str, soup: BeautifulSoup, disclosure_info: Dict) -> Dict:
        """공시서류에서 상세 매수 정보 추출"""
        details = {}

        try:
            # 테이블에서 정보 추출
            tables = soup.find_all('table')

            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        header = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)

                        # 보고자 정보
                        if any(keyword in header for keyword in ['보고자', '성명', '이름']):
                            details['reporter_name'] = value

                        # 직위 정보
                        elif any(keyword in header for keyword in ['직위', '관계', '지위']):
                            details['position'] = value

                        # 매수일자
                        elif any(keyword in header for keyword in ['매수일', '취득일', '거래일']):
                            details['purchase_date'] = value

                        # 매수주식수
                        elif any(keyword in header for keyword in ['매수주식수', '취득주식수', '거래주식수', '주식수']):
                            details['purchase_shares'] = value

                        # 매수금액
                        elif any(keyword in header for keyword in ['매수금액', '취득금액', '거래금액']):
                            details['purchase_amount'] = value

                        # 소유비율
                        elif '소유비율' in header or '지분율' in header:
                            if '변동전' in header or '이전' in header:
                                details['ownership_before'] = value
                            elif '변동후' in header or '이후' in header:
                                details['ownership_after'] = value

            # 정규식을 사용한 추가 정보 추출

            # 날짜 패턴 추출 (YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD)
            date_patterns = [
                r'(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})',
                r'(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)'
            ]

            for pattern in date_patterns:
                matches = re.findall(pattern, text_content)
                if matches and 'purchase_date' not in details:
                    details['purchase_date'] = matches[0]
                    break

            # 주식수 패턴 추출
            share_patterns = [
                r'(\d{1,3}(?:,\d{3})*)\s*주',
                r'(\d+)\s*주식',
                r'주식수[:\s]*(\d{1,3}(?:,\d{3})*)'
            ]

            for pattern in share_patterns:
                matches = re.findall(pattern, text_content)
                if matches and 'purchase_shares' not in details:
                    details['purchase_shares'] = matches[0]
                    break

            # 금액 패턴 추출
            amount_patterns = [
                r'(\d{1,3}(?:,\d{3})*)\s*원',
                r'금액[:\s]*(\d{1,3}(?:,\d{3})*)',
                r'(\d+)\s*백만원',
                r'(\d+)\s*억원'
            ]

            for pattern in amount_patterns:
                matches = re.findall(pattern, text_content)
                if matches and 'purchase_amount' not in details:
                    details['purchase_amount'] = matches[0] + '원'
                    break

            # 비율 패턴 추출
            ratio_patterns = [
                r'(\d+\.\d+)%',
                r'(\d+)%'
            ]

            for pattern in ratio_patterns:
                matches = re.findall(pattern, text_content)
                if matches:
                    if 'ownership_before' not in details:
                        details['ownership_before'] = matches[0] + '%'
                    elif 'ownership_after' not in details and len(matches) > 1:
                        details['ownership_after'] = matches[1] + '%'

        except Exception as e:
            logging.error(f"상세 정보 추출 실패: {e}")

        return details

    def monitor_executive_purchases(self, days_back: int = 3) -> List[ExecutivePurchase]:
        """임원 장내매수 모니터링 메인 함수"""
        try:
            # 날짜 범위 설정
            end_date = datetime.now(KST).date()
            start_date = end_date - timedelta(days=days_back)

            start_date_str = start_date.strftime('%Y-%m-%d')
            end_date_str = end_date.strftime('%Y-%m-%d')

            logging.info(f"임원 매수 모니터링 시작: {start_date_str} ~ {end_date_str}")

            # 임원 공시 목록 조회
            disclosures = self.get_executive_disclosures(start_date_str, end_date_str)

            if not disclosures:
                logging.info("임원 관련 공시가 없습니다.")
                return []

            all_purchases = []

            # 각 공시에 대해 원본 분석
            for disclosure in disclosures:
                rcept_no = disclosure.get('rcept_no')
                corp_name = disclosure.get('corp_name')

                logging.info(f"공시 분석 중: {corp_name} ({rcept_no})")

                # 공시서류 원본 다운로드
                document_content = self.download_document(rcept_no)

                if document_content:
                    # 장내매수 분석
                    purchases = self.analyze_document_for_purchases(document_content, disclosure)
                    all_purchases.extend(purchases)

                    if purchases:
                        logging.info(f"장내매수 발견: {corp_name} - {len(purchases)}건")

                # API 호출 제한 고려 (1초 대기)
                time.sleep(1)

            logging.info(f"총 {len(all_purchases)}건의 장내매수 발견")
            return all_purchases

        except Exception as e:
            logging.error(f"모니터링 실행 실패: {e}")
            return []

def save_results(purchases: List[ExecutivePurchase]):
    """결과를 파일로 저장"""
    try:
        results_dir = Path('./results')
        results_dir.mkdir(exist_ok=True)

        current_time = datetime.now(KST)
        filename = f"executive_purchases_v2_{current_time.strftime('%Y%m%d_%H%M%S')}.json"
        filepath = results_dir / filename

        # ExecutivePurchase 객체를 딕셔너리로 변환
        results_data = []
        for purchase in purchases:
            results_data.append({
                'company_name': purchase.company_name,
                'company_code': purchase.company_code,
                'reporter_name': purchase.reporter_name,
                'position': purchase.position,
                'purchase_date': purchase.purchase_date,
                'purchase_amount': purchase.purchase_amount,
                'purchase_shares': purchase.purchase_shares,
                'report_date': purchase.report_date,
                'disclosure_number': purchase.disclosure_number,
                'purchase_reason': purchase.purchase_reason,
                'ownership_before': purchase.ownership_before,
                'ownership_after': purchase.ownership_after
            })

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results_data, f, ensure_ascii=False, indent=2)

        logging.info(f"결과 저장 완료: {filepath}")

    except Exception as e:
        logging.error(f"결과 저장 실패: {e}")

def main():
    """메인 실행 함수"""
    try:
        # 로깅 설정
        logger = setup_logging()

        current_time = datetime.now(KST)
        logging.info("=== 임원 장내매수 모니터링 V2 시작 ===")
        logging.info(f"실행 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S KST')}")

        # 환경 변수 확인
        dart_api_key = os.getenv('DART_API_KEY')
        telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

        logging.info(f"DART API 키: {'설정됨' if dart_api_key else '없음'}")
        logging.info(f"텔레그램 토큰: {'설정됨' if telegram_token else '없음'}")
        logging.info(f"텔레그램 채팅ID: {'설정됨' if telegram_chat_id else '없음'}")

        # OpenDart 분석기 초기화
        analyzer = OpenDartDocumentAnalyzer(dart_api_key)

        # 텔레그램 알림 초기화
        notifier = None
        if telegram_token and telegram_chat_id:
            notifier = TelegramNotifier(telegram_token, telegram_chat_id)
            logging.info("텔레그램 알림 활성화")
        else:
            logging.warning("텔레그램 설정이 없어 알림이 비활성화됩니다")

        # 임원 매수 모니터링 실행
        purchases = analyzer.monitor_executive_purchases(days_back=3)

        # 결과 처리
        if purchases:
            logging.info(f"총 {len(purchases)}건의 장내매수 발견!")

            # 결과 저장
            save_results(purchases)

            # 텔레그램 알림 전송
            if notifier:
                for purchase in purchases:
                    message = notifier.format_purchase_message(purchase)
                    success = notifier.send_message(message)
                    if success:
                        logging.info(f"알림 전송 완료: {purchase.company_name} - {purchase.reporter_name}")
                    else:
                        logging.error(f"알림 전송 실패: {purchase.company_name} - {purchase.reporter_name}")

                    # 알림 간격 (1초)
                    time.sleep(1)

            # 완료 알림
            if notifier:
                summary_message = f"""📊 <b>모니터링 완료 (V2)</b>

📅 <b>조회 기간:</b> 최근 3일
📋 <b>임원 공시:</b> 원본 분석 완료
💰 <b>장내매수:</b> {len(purchases)}건 발견
⏰ <b>완료 시간:</b> {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}

🔍 <b>분석 방식:</b> 공시서류 원본 분석
✅ <b>탐지 정확도:</b> 대폭 향상

#모니터링완료 #OpenDart #원본분석"""

                notifier.send_message(summary_message)

        else:
            logging.info("장내매수가 발견되지 않았습니다.")

            # 완료 알림 (매수 없음)
            if notifier:
                no_purchase_message = f"""📊 <b>모니터링 완료 (V2)</b>

📅 <b>조회 기간:</b> 최근 3일
📋 <b>분석 방식:</b> 공시서류 원본 분석
💰 <b>장내매수:</b> 0건
⏰ <b>완료 시간:</b> {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}

🔍 <b>개선사항:</b> 원본 분석으로 정확도 향상

#모니터링완료 #OpenDart #원본분석"""

                notifier.send_message(no_purchase_message)

        logging.info("=== 모니터링 완료 ===")

    except Exception as e:
        logging.error(f"실행 중 오류 발생: {e}")

        # 오류 알림
        if 'notifier' in locals() and notifier:
            error_message = f"""❌ <b>시스템 오류 (V2)</b>

🚨 <b>오류 내용:</b> {str(e)[:200]}...
⏰ <b>발생 시간:</b> {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}

#시스템오류 #OpenDart #원본분석"""
            notifier.send_message(error_message)

        sys.exit(1)

if __name__ == "__main__":
    main()
