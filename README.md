# 임원 장내매수 모니터링 시스템

한국거래소 KIND 시스템에서 임원·주요주주 특정증권등 소유상황보고서를 실시간으로 모니터링하고, 장내매수 정보를 텔레그램으로 알림받는 자동화 시스템입니다.

## 🎯 주요 기능

- **실시간 모니터링**: KIND 시스템의 오늘의 공시를 자동으로 확인
- **스마트 필터링**: "임원ㆍ주요주주특정증권등소유상황보고서" 공시만 추출
- **장내매수 감지**: 보고사유가 "장내매수"인 경우만 알림
- **텔레그램 알림**: 구조화된 메시지로 즉시 알림 전송
- **자동 실행**: GitHub Actions를 통한 정기 자동 실행
- **한국 시간대**: 모든 시간 표시를 KST(한국표준시)로 처리

## 📅 실행 스케줄

**평일(월-금) 하루 5회 자동 실행:**
- 🕘 **09:00** (오전 9시)
- 🕐 **11:00** (오전 11시)  
- 🕐 **13:00** (오후 1시)
- 🕒 **15:00** (오후 3시)
- 🕔 **17:00** (오후 5시)

*모든 시간은 한국표준시(KST) 기준입니다.*

## 🛠️ 시스템 요구사항

### Python 패키지
- Python 3.11+
- requests >= 2.31.0
- beautifulsoup4 >= 4.12.0
- selenium >= 4.15.0
- python-telegram-bot >= 20.0
- pytz >= 2023.3 (한국 시간대 처리)

### 시스템 요구사항
- Chrome 브라우저
- ChromeDriver (webdriver-manager가 자동 관리)
- 인터넷 연결

## 🚀 설치 및 설정

### 1. 저장소 클론
```bash
git clone <your-repository-url>
cd executive-purchase-monitor
```

### 2. 의존성 설치
```bash
pip install -r requirements.txt
```

### 3. 환경 변수 설정
```bash
# .env.example을 .env로 복사
cp .env.example .env

# .env 파일 편집
nano .env
```

### 4. 텔레그램 봇 설정

#### 4.1 봇 생성
1. 텔레그램에서 [@BotFather](https://t.me/botfather)와 대화 시작
2. `/newbot` 명령어 입력
3. 봇 이름과 사용자명 설정
4. 받은 토큰을 복사

#### 4.2 채팅 ID 확인
1. 생성한 봇과 대화 시작 (메시지 하나 전송)
2. 브라우저에서 다음 URL 접속:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
3. 응답에서 `chat.id` 값 확인

### 5. GitHub Secrets 설정
GitHub 저장소 → Settings → Secrets and variables → Actions에서 추가:

- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: 텔레그램 채팅 ID

## 🏃‍♂️ 실행 방법

### 로컬 실행
```bash
# 시스템 테스트 (권장)
python test_system.py

# 메인 모니터링 실행
python monitor_executive_purchases.py
```

### GitHub Actions 자동 실행
- 평일 9시, 11시, 13시, 15시, 17시에 자동 실행
- Actions 탭에서 수동 실행 가능

## 📱 알림 메시지 형식

```
🏢 임원 장내매수 알림

📊 회사명: 삼성전자
👤 보고자: 홍길동
💼 직위: 대표이사
💰 매수금액: 1,000,000,000원
📅 보고일자: 2025-01-18 14:30
📋 공시번호: 20250118001234

⏰ 알림시간: 2025-01-18 14:35:22 KST

#임원매수 #KIND
```

## 📁 프로젝트 구조

```
executive-purchase-monitor/
├── monitor_executive_purchases.py  # 메인 모니터링 스크립트
├── test_system.py                 # 시스템 테스트 스크립트
├── requirements.txt               # Python 의존성
├── .env.example                   # 환경 변수 예시
├── .gitignore                     # Git 무시 파일
├── README.md                      # 프로젝트 문서
├── .github/
│   └── workflows/
│       └── monitor-executive-purchases.yml  # GitHub Actions 워크플로우
├── logs/                          # 실행 로그 (자동 생성)
└── results/                       # 결과 파일 (자동 생성)
```

## 🔧 주요 구성 요소

### KindMonitor 클래스
- KIND 웹사이트 모니터링
- Selenium을 통한 동적 페이지 처리
- 공시 상세 정보 추출

### TelegramNotifier 클래스
- 텔레그램 메시지 전송
- 메시지 포맷팅
- 오류 처리

### 시간대 처리
- **KSTFormatter**: 모든 로그를 한국 시간으로 표시
- **pytz 라이브러리**: 정확한 시간대 변환
- **환경 변수**: GitHub Actions에서 TZ=Asia/Seoul 설정

## 📊 로그 및 모니터링

### 로그 파일
- 위치: `logs/executive_monitor_YYYYMMDD.log`
- 형식: `YYYY-MM-DD HH:MM:SS KST - LEVEL - MESSAGE`
- 보관: 자동으로 날짜별 파일 생성

### 결과 파일
- JSON: `results/executive_purchases_YYYYMMDD_HHMMSS.json`
- CSV: `results/executive_purchases_YYYYMMDD_HHMMSS.csv`
- 인코딩: UTF-8 (한글 지원)

## ⚠️ 주의사항

### 시간대 설정
- **중요**: 모든 시간은 한국표준시(KST)로 처리됩니다
- GitHub Actions에서 `TZ=Asia/Seoul` 환경 변수 설정
- 로그와 알림 메시지 모두 KST로 표시

### 웹 스크래핑 제한
- KIND 시스템의 접근 정책을 준수
- 과도한 요청 방지를 위한 지연 시간 설정
- 로봇 차단 방지를 위한 User-Agent 설정

### 텔레그램 API 제한
- 메시지 전송 간격 조절 (1초 지연)
- API 호출 제한 준수
- 오류 발생 시 재시도 로직

## 🐛 문제 해결

### 일반적인 문제

#### 1. 시간이 잘못 표시되는 경우
```bash
# 시스템 시간대 확인
date
timedatectl

# Python에서 시간대 확인
python -c "import datetime, pytz; print(datetime.datetime.now(pytz.timezone('Asia/Seoul')))"
```

#### 2. Chrome WebDriver 오류
```bash
# Chrome 버전 확인
google-chrome --version

# ChromeDriver 재설치
pip uninstall webdriver-manager
pip install webdriver-manager
```

#### 3. 텔레그램 연결 실패
- 봇 토큰 재확인
- 채팅 ID 재확인
- 봇이 차단되지 않았는지 확인

#### 4. KIND 웹사이트 접근 실패
- 네트워크 연결 확인
- VPN 사용 시 한국 서버로 연결
- User-Agent 설정 확인

### 로그 확인
```bash
# 최신 로그 확인
tail -f logs/executive_monitor_$(date +%Y%m%d).log

# 오류 로그만 확인
grep -i error logs/executive_monitor_*.log
```

## 🔄 업데이트 내역

### v2.0.0 (2025-01-18)
- **시간대 수정**: 모든 시간 표시를 한국표준시(KST)로 변경
- **스케줄 변경**: 9시, 11시, 13시, 15시, 17시로 실행 시간 조정
- **pytz 라이브러리 추가**: 정확한 시간대 처리
- **KSTFormatter 클래스 추가**: 로그 시간을 KST로 표시
- **GitHub Actions 환경 변수 추가**: TZ=Asia/Seoul 설정

### v1.0.0 (2025-01-17)
- 초기 버전 릴리스
- 기본 모니터링 기능 구현
- 텔레그램 알림 기능 구현

## 🤝 기여하기

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.

## 📞 지원

문제가 발생하거나 질문이 있으시면:

1. **Issues**: GitHub Issues에 문제 보고
2. **테스트**: `python test_system.py` 실행하여 시스템 상태 확인
3. **로그**: `logs/` 디렉토리의 로그 파일 확인

---

**⏰ 현재 시간대**: 한국표준시(KST, UTC+9)  
**🔄 마지막 업데이트**: 2025-01-18  
**📅 실행 스케줄**: 평일 09:00, 11:00, 13:00, 15:00, 17:00 (KST)
