# rdom — 랜덤다이스2 자동 플레이 프로젝트 사전조사

- 작성일: 2026-09-15
- 대상: 랜덤다이스2 (111퍼센트, 2026-08-13 출시, `com.percent.aos.randomdice2`)
- 목표: 모바일 게임을 PC에서 구동 → 플레이 데이터 학습 → 학습 기반 자동 플레이
- 현 상태: `C:\dev\rdom` 빈 디렉터리 (그린필드)

---

## 0. 한 줄 결론

> **기술적으로 충분히 가능하지만, 병목은 "학습"이 아니라 "인식 레이어의 라벨 비용"과 "실클라이언트의 느린 스텝 속도"다.**
> 권장 경로는 `룰기반 자동화(1단계) → 모방학습 BC(2단계) → 자체 시뮬레이터 RL(3단계)`이며,
> **자체 시뮬레이터 구현이 ROI가 가장 높은 투자**다. 실클라이언트 온라인 RL은 사실상 불가능(아래 §4.2).
> 단, 약관상 **외부 자동화 프로그램은 명백한 금지 대상**이므로 운용 범위를 먼저 결정해야 한다(§6).

---

## 1. 게임 분석 — 자동화 대상 정의

### 1.1 확인된 사실

| 항목 | 내용 |
| --- | --- |
| 장르 | 주사위 소환 → 동일 주사위 병합(눈금 상승) → 웨이브 방어 (머지 타워디펜스) |
| 메인 모드 | **협동(코옵)** — 전작과 달리 PvP(아레나)는 부수 콘텐츠 |
| 자원 | SP(소환 코스트). 게임 시작 시 지급, 소환할수록 비용 상승 |
| 주사위 체계 | 등급 없음. **5가지 테마** — 자연 / 공학 / 마법 / 질서 / 혼돈 + 조커·폭탄. 눈금(pip) 수준으로 강화 |
| 성장 | "다이스 트리" 노드 해금 방식 (상점·상자 → 트리로 변경). 가챠 제거 |
| 서포터 | 청, 릭, 에코, 디키, 이안 — 5명, 고유 능력 |
| UI | 3D 리뉴얼. **"가시성이 떨어진다"는 평가 다수** → CV 인식 난이도가 전작보다 높을 가능성 |

### 1.2 ⚠️ 직접 측정이 필요한 미확인 사항

공개 자료로 확인되지 않아 **1회차 작업으로 반드시 실측해야 하는 항목**:

- [ ] **보드 그리드 크기** — 전작은 5×3(15칸). RD2도 동일한지 미확인. 3D 리뉴얼로 원근 왜곡이 있는지가 핵심
- [ ] SP 초기값 / 소환 비용 증가 공식
- [ ] 웨이브 스폰 규칙(결정론적인지, 시드 기반인지)
- [ ] 승패 조건 (기지 HP? 웨이브 도달?)
- [ ] 액션 공간 — 소환 / 병합(드래그) / 업그레이드 / 서포터 스킬의 정확한 목록
- [ ] 협동 모드에서 팀원 보드가 화면에 동시 표시되는지

> 이 6개가 정해지기 전에는 인식 모델도 액션 스페이스도 설계할 수 없다. **다음 세션 1순위.**

---

## 2. 권장 아키텍처 — 4레이어 완전 분리

MAA(명일방주), KataCR(클래시로얄), ClashRoyaleBuildABot 모두 공통으로 채택한 구조. 게임 업데이트 대응 비용을 낮추는 핵심.

```
┌─────────────┐  캡처   ┌─────────────┐  상태   ┌─────────────┐  액션  ┌─────────────┐
│  Capture    │ ──────▶ │ Perception  │ ──────▶ │  Policy     │ ─────▶ │  Input      │
│  dxcam /    │  frame  │ CNN/템플릿   │  state  │ 룰 → BC →RL │ cell#  │ MaaTouch /  │
│  scrcpy     │         │ + 숫자 OCR   │         │             │        │ scrcpy ctrl │
└─────────────┘         └─────────────┘         └─────────────┘        └─────────────┘
```

**핵심 설계 원칙**

1. **액션은 픽셀 좌표가 아니라 셀 인덱스(0~N)로 정규화**해서 저장·학습한다. 해상도 변경·UI 이동에 강해지고, 액션 공간이 작아져 BC 난이도가 급감한다.
2. Policy는 화면을 모르고, Perception은 게임 룰을 모른다. 세 좌표계(데스크톱 픽셀 / 스트림 픽셀 / 안드로이드 논리 픽셀)를 명시적으로 분리 관리.
3. MAA식 **JSON 선언형 태스크 파이프라인**을 초기부터 채택 — 메뉴 네비게이션 같은 비전투 로직을 코드가 아닌 데이터로.

---

## 3. 실행·캡처·입력 스택

### 3.1 실행 환경 비교

| 환경 | ADB | 해상도 고정 | 자동화 API | 탐지 위험 |
| --- | --- | --- | --- | --- |
| **LDPlayer 9** | `127.0.0.1:5555`(인스턴스별 +2) | `ldconsole modify --resolution 1600,900,240` CLI | **ldconsole.exe** (launch/quit/installapp/setprop) | 중 |
| BlueStacks 5 | 수동 활성화 필요 | GUI만 | 내장 매크로 레코더뿐 | **높음** (freeRASP 등이 기본 시그니처로 탐지) |
| MuMu Player 12 | `127.0.0.1:16384~` | MuMuManager.exe | MuMuManager + 백그라운드 터치 | 중 |
| Google Play Games on PC | 소비자판 사실상 차단 | 창 고정 | 없음 | **매우 높음** |
| WSA | — | — | — | **2025-03-05 지원 종료. 채택 불가** |
| **실기기 + scrcpy** | 네이티브 | `wm size` | scrcpy 프로토콜 | **가장 낮음** |

> RD2는 BlueStacks 전용 페이지가 존재 → **에뮬 구동 자체는 차단되지 않는 것으로 보임**(제3자 마케팅 페이지이므로 보증은 아님).

### 3.2 화면 캡처 실측 (1080p 기준)

| 방법 | FPS | 지연 | 판정 |
| --- | --- | --- | --- |
| **dxcam (DXGI Desktop Duplication)** | **239 fps** (σ=1.25) | ~4ms/frame | ✅ **에뮬 경로 1순위** |
| D3DShot | 118 fps | — | 유지보수 중단 |
| mss | 76 fps | ~13ms | 크로스플랫폼이나 느림 |
| win32 BitBlt | 60~80 fps | — | 하드웨어 가속 창에서 검은 화면 위험 |
| OBS Virtual Cam | 30~60 fps | **100ms+** | 부적합 |
| **ADB `screencap`** | **1~2 fps** | **500~1500ms** | ❌ **루프 캡처에 사용 불가** |
| **scrcpy 비디오 스트림** | 30~120 fps | **<50ms** (공식 35~70ms) | ✅ **실기기 경로 1순위** |

### 3.3 입력 주입

| 방법 | 지연 | 비고 |
| --- | --- | --- |
| `adb shell input tap` | **200~400ms/탭** | 매번 JVM 신규 기동. 연속 드래그 불가 수준 |
| minitouch | 수 ms | **Android 10+ SELinux에서 동작 불가** |
| **MaaTouch** | 수 ms | `app_process` Java 구현 → Android 10+ 호환. ✅ **현재 권장** |
| **scrcpy control** | <10ms | `ControlSender.touch()` 멀티터치, `swipe()` 지원 |
| win32 PostMessage | ~0ms | DirectX/OpenGL 렌더 창이 무시하는 경우 많음. 비신뢰 |
| win32 SendInput | ~1ms | 전역 커서 독점 → PC 병행 사용 불가 |

### 3.4 좌표계 함정 (실무 체크리스트)

- `GetClientRect`/`ClientToScreen`으로 클라이언트 영역만 크롭 — LDPlayer 우측 툴바 ~40px 제외 필수
- **Windows DPI 스케일링 125/150%에서 클릭이 빗나감** → `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` 선언
- 템플릿은 **정규화 [0,1] 좌표**로 저장 (픽셀 반올림 누적 오차 회피)
- 레터박스 여백 폭을 먼저 검출해 오프셋 제거 후 선형 스케일
- **DPI를 해상도와 함께 고정** — DPI가 바뀌면 UI 크기가 바뀌어 템플릿이 전부 실패

### 3.5 파이썬 라이브러리 현황 (2026-09 기준)

| 라이브러리 | 상태 | 판정 |
| --- | --- | --- |
| **dxcam** 0.3.0 (2026-03) | 활발, Py3.10~3.14 휠 | ✅ 캡처 1순위 |
| **adbutils** 2.12.0 (2025-11) | 활발 | ✅ ADB 표준 |
| **uiautomator2** 3.7.0 (2026-06) | 활발 | Unity 캔버스엔 무용 — 앱 실행/복구 용도만 |
| py-scrcpy-client 0.5.0 (2024-06) | **정체** (scrcpy 2.4 번들, 본체는 v4.1) | 쓰려면 서버 2.4로 핀 고정 |
| pure-python-adb | 방치 | ❌ adbutils로 대체 |
| MaaFramework (`MaaFw`) | 활발 | 밑바닥 구현이 싫으면 유력 후보 |

### 3.6 권장 조합

- **A안 (성능 우선)** — LDPlayer 9 (1600×900 고정, 60fps) + **dxcam** + **MaaTouch** + adbutils(앱 관리)
- **B안 (탐지 회피 우선)** — 구형 안드로이드 실기기 + **scrcpy 스트림** + scrcpy control 채널

> 두 안 모두 탭 좌표에 **±3px**, 간격에 **±50ms 랜덤 지터** 필수. 행동 패턴 탐지가 에뮬레이터 탐지보다 현실적 위험이다.

---

## 4. 인식 · 학습 파이프라인

### 4.1 화면 → 상태(state) 추출

**권장: YOLO 전체화면 탐지가 아니라 "고정 그리드 크롭 + 소형 CNN"**

랜덤다이스류는 고정 그리드 + 고정 해상도라 `matchTemplate`의 스케일/회전 불변성 문제가 대부분 무력화된다. 셀을 고정 크롭하면:

- **주사위 종류** = 32×32 셀 크롭 → 소형 CNN 분류기 (수천 파라미터, 추론 <1ms)
- **눈금(pip)** = pip 영역 별도 크롭 분류
- **SP / 웨이브 / HP** = 고정 위치 + 고정 폰트 + 10클래스 → **자체 숫자 CNN**

> 숫자는 PaddleOCR/Tesseract보다 **자체 CNN이 압도적으로 유리**하다. 폰트 에셋에서 0~9를 렌더링해 수천 장 자동 생성 → 99%+ 달성, 추론 <1ms, OCR 엔진 로딩 오버헤드(수십~수백ms) 회피.
> (참고: Tesseract는 게임 폰트·짧은 문자열에 약함. PaddleOCR은 정확하나 무겁다. MAA는 PaddleOCR+onnxruntime 채택.)

**템플릿 매칭이 실패하는 지점** — 이때만 YOLO 추가:
(a) 이펙트/투사체가 주사위를 가릴 때, (b) 반투명 오버레이가 pip에 겹칠 때, (c) 스킨/신규 주사위 추가 시 템플릿 수동 갱신 비용

**YOLO 레퍼런스 수치 (KataCR, 클래시로얄)**
- YOLOv8-l ×2, 150 클래스, 합성 20,000장 학습 / 실제 6,939장·116,878박스 검증
- **mAP50 = 84.3%**, RTX 4060 Laptop + ByteTrack **34 FPS**
- → 병목은 GPU가 아니라 **화면캡처·ADB 왕복**

### 4.2 라벨링 자동화 — 이 프로젝트 최대 절약 포인트

게임 에셋에서 스프라이트를 추출해 **빈 보드 배경 위에 합성 → 라벨 자동 생성**(비용 0).

YARDS 논문 실측 (레트로 게임 스프라이트 합성 + YOLOv5):

| 데이터 구성 | mAP@0.5 |
| --- | --- |
| 합성 750장 | 0.677 |
| 합성 3,750장 | 0.816 |
| 실제 750장 (수동 라벨) | 0.856 |
| 합성 10,000장 | 0.935 |
| **실제 500장 + 합성 9,500장** | **0.963** ← 최적 |

> **합성 대량 + 실제 소량(수백 장) 파인튜닝**이 최적 비용/성능. RD2는 고정 그리드 + 에셋 추출이 쉬워 적합도가 매우 높다.

### 4.3 학습 방식 비교

**(a) Behavior Cloning (모방학습)** — 1차 목표로 권장

- 구조: 화면(상태) + 터치(액션) 로그 → 지도학습. 구현 난이도 최저, 결과가 가장 빨리 나옴
- **실패모드: compounding error / covariate shift** — 학습 분포를 벗어나면 오차가 O(T²)로 누적 발산. 해법은 **DAgger**(에이전트가 방문한 상태에 전문가 라벨 추가 → 재학습)
- 데이터 실측(KataCR): 전문가 **105 에피소드 / 113,981 프레임**. 이 중 **액션이 있는 프레임은 4.01%뿐** → **액션:비액션 24.92:1 리샘플링 필수**
- 확장 경로(OpenAI VPT): 계약자 라벨 1,962시간으로 IDM 학습(키 정확도 90.6%) → **70,000시간 무라벨 영상 자동 라벨링**. **IDM은 같은 데이터의 BC보다 데이터 효율이 100배**. IDM은 10시간부터 동작, 100시간에서 포화
- **현실적 목표 규모: 10~30시간(수십만 프레임)이면 사람 평균 수준 모방 가능**

**(b) 실클라이언트 온라인 RL — ❌ 사실상 불가능**

- 모바일 퍼즐게임 PPO 논문: 안정 성능까지 **4M~14M 스텝** 필요
- 실기기 5 FPS로 환산하면 **1,000시간 이상**
- 추가 문제: 에피소드 리셋 자동화 곤란, 400k 스텝에서 무효 액션 반복으로 붕괴(catastrophic failure) 사례

**(c) 자체 시뮬레이터 + RL — ✅ ROI 최고**

- RD2는 고정 그리드·이산 액션·결정론에 가까운 웨이브 스폰 → **시뮬레이터 구현 난이도가 낮고 초당 수만 스텝 가능**
- PPO 4M 스텝이 실기기에선 1,000시간, 시뮬레이터에선 **수십 분~수 시간**
- 논문의 유용한 교훈: **소프트 액션 마스크**(유효/무효 정보를 관측에 포함)가 하드 마스킹보다 우수하며 4M 스텝으로 최속 수렴 / 100스텝마다 리셋해 나쁜 샘플 누적 방지
- 남는 문제: sim-to-real 갭 → 시뮬레이터 정책을 실클라이언트 로그로 **BC 파인튜닝**하는 2단계로 보정

### 4.4 데이터 수집 — 프레임/액션 동기화

**방법**: py-scrcpy의 `on_frame` 콜백 + 제어 이벤트를 같은 프로세스에서 한 타임라인에 기록. 또는 `adb shell getevent -lt`(커널 타임스탬프, 정밀도 높음).

**4대 정렬 문제와 대책**

| 문제 | 대책 |
| --- | --- |
| ① 인코딩·전송 지연 (수십~100ms) | 고정 오프셋 보정. 버튼 눌림 효과로 1회 캘리브레이션 |
| ② **인간 반응 지연 150~250ms** — 터치 시각의 프레임은 이미 상황이 바뀐 프레임 | 액션을 **N프레임 과거의 프레임에 할당** |
| ③ 희소 액션 (4.01%) | 액션 프레임 중심 리샘플링(24.92:1) + **지연 액션 예측**(최대 T_delay=20프레임) |
| ④ 에피소드 분할 | 웨이브 숫자/결과화면 OCR로 자동 분할 |

**기록 포맷**: `(frame_idx, monotonic_ts, jpg, action_type, cell_index)` — **픽셀 좌표가 아니라 셀 인덱스로 정규화**

### 4.5 참고할 오픈소스

| 프로젝트 | 아키텍처 | 참고 포인트 |
| --- | --- | --- |
| **MAA** (명일방주) | C++ 코어, OpenCV 템플릿 + PaddleOCR + onnxruntime, **JSON 태스크 파이프라인**, MaaTouch | ✅ **룰기반+부분학습 프로덕션 설계의 교과서** |
| **KataCR** (클래시로얄) | YOLOv8-l×2 + PaddleOCR + **오프라인 RL(StARformer/DT)** | ✅ **본 프로젝트와 구조적으로 가장 유사.** 수치 전부 공개 |
| ClashRoyaleBuildABot | YOLOv10 + ADB/BlueStacks, 인식/전략 플러그인 분리 | 액션 추상화 설계 |
| arknights-mower | Python, WebUI 스케줄러, 템플릿 매칭 | 파이썬 구현 참고 |
| Random-Dice-OpenCV / random_dice_bot | 순수 템플릿 매칭 (전작 기준, 학습 없음) | **보드 파싱 좌표계 직접 참고 가능** |

### 4.6 기대치 설정 (중요)

> KataCR의 최종 성적: 총보상 -4.7±3.1, **내장 AI 상대 승률 10%** (실제 랭크전 8000점대·12연승 기록은 있음)
>
> **화면만 보고 플레이하는 에이전트가 사람 상위권을 이기는 사례는 아직 없다.**
> 현실적 목표는 "사람 평균 이상 + 반복 파밍 자동화"로 잡는 게 맞다.

---

## 5. 단계별 로드맵

| 단계 | 산출물 | 검증 기준 | 예상 난이도 |
| --- | --- | --- | --- |
| **M0. 환경 실측** | 보드 그리드·해상도·액션 스페이스 확정 문서, 캡처 FPS 실측 | dxcam으로 60fps 안정 캡처, 클릭 좌표 오차 <3px | 낮음 |
| **M1. 인식 레이어** | 셀 크롭 CNN(주사위/pip) + 숫자 CNN(SP/웨이브/HP) | 실제 프레임 200장에서 셀 분류 정확도 **>98%** | 중 |
| **M2. 입력 레이어** | MaaTouch/scrcpy 래퍼, 지터 포함 탭·드래그 | 100회 반복 탭 성공률 100%, 지연 <20ms | 낮음 |
| **M3. 룰기반 봇** | JSON 태스크 파이프라인, 단순 휴리스틱(항상 최저 눈금 병합 등) | 협동 모드 1스테이지 완주 | 중 |
| **M4. 데이터 수집** | 프레임+셀인덱스 액션 로거, 10~30시간 로그 | 동기화 오프셋 캘리브레이션 완료, 액션 라벨 오류율 <2% | 중 |
| **M5. BC 정책** | 모방학습 모델 | 룰기반 봇 대비 웨이브 도달 우위 | 중~높음 |
| **M6. 시뮬레이터** | RD2 룰 재구현 (초당 수만 스텝) | 실제 게임과 웨이브별 DPS 오차 <10% | **높음** |
| **M7. RL + 파인튜닝** | PPO(소프트 액션 마스크) → 실로그 BC 파인튜닝 | BC 정책 대비 우위 | 높음 |

> **M0~M3까지가 실질적 "자동 플레이 달성" 지점**이고, M4 이후가 "학습 기반"이다. M6(시뮬레이터)에서 멈춰도 프로젝트는 성립한다.

---

## 6. ⚠️ 약관 · 탐지 리스크 (실행 전 결정 필요)

### 6.1 약관 — 금지 조항이 명시적으로 존재

111퍼센트 이용약관 **제10조 1항**:

> "회사가 제공 또는 승인하지 아니한 **컴퓨터 프로그램이나 기기 또는 장치를 제작, 배포, 이용, 광고하는 행위**"
> "…기술적 보호조치를 무력화하거나 정상적인 운영을 방해할 목적으로 …승인하지 아니한 프로그램을 이용하는 행위"
> "…정상적인 질서, 밸런스, 규칙 등을 회피 또는 우회하여 비정상적인 기록·점수·게임머니·아이템을 획득하는 행위"

"매크로/봇"이라는 단어는 없지만 **외부 자동화 프로그램은 그대로 포섭**된다.
제재 근거는 **제19조 1항**(기간제/영구 이용 제한), **제24조 2항**은 중과실 시 **사전 통보 없는 이용계약 해지**.

> **약관은 PvE/PvP 모드를 구분하지 않는다.** 아래는 위험을 0으로 만드는 방법이 아니라 상대적 크기 비교다.

### 6.2 상대적 위험 비교

| 접근 | 위험 | 근거 |
| --- | --- | --- |
| **읽기 전용 로그 수집** (캡처만, 입력 주입 없음) | **가장 낮음** | 게임에 입력이 들어가지 않아 입력 패턴·행동 이상치 양쪽에 신호를 남기지 않음. 사실상 화면 녹화와 동등 |
| 싱글/PvE 자동화 | 중 | 보복 신고 벡터 제거. 단 서버측 행동 분석은 그대로 적용 |
| **협동(코옵) 자동화** | 중~높음 | **팀원이 있으므로 신고 벡터가 살아 있음.** RD2는 협동이 메인이라 이 구분이 중요 |
| 아레나(PvP) 자동화 | **가장 높음** | 신고 + 승률/반응시간 이상치 + 경쟁 무결성 위반 |
| 부계정 | **오해 항목** | 기기 지문·네트워크·결제로 **계정 군집이 묶이면 본계정까지 연쇄 제재**. 본계정 보호 수단으로 신뢰 불가 |

> 커뮤니티 보고상 111%는 **이용자 신고가 제재 트리거로 작동**하는 정황이 있고(Change.org 청원), 문의 응대 부실 불만이 반복 제기된 개발사다. **소명·복구 가능성은 낮게 잡는 게 안전.**

### 6.3 탐지 기법 — "외부 봇이라 안 걸린다"는 성립하지 않음

| 층위 | 내용 | 외부 봇 회피 가능? |
| --- | --- | --- |
| (a) 입력 패턴 분석 | 실제 손가락은 압력·접촉면적·좌표 지터·지속시간에 분산이 있음. 주입형은 **완벽히 일정한 간격, 직선 드래그** | ❌ 불가 (지터로 완화만) |
| (b) **서버측 행동 분석** | 비인간적으로 낮은 반응시간 분산, 24시간 연속 플레이, 활동 다양성 부족, 시간당 자원 획득 상한 초과 | ❌ **입력 방식과 무관. 결과 로그만으로 작동** |
| (c) 에뮬레이터 핑거프린팅 | `ro.hardware=goldfish`, `/dev/qemu_pipe`, 하드웨어 키스토어 부재, 센서 무변동, 배터리 100% 고정 | 실기기로 회피 가능 |
| (d) 기기 무결성 | Play Integrity API / App Attest + 디바이스 지문 → **계정 군집 추적** | 부분적 |
| (e) 메모리 스캔/안티디버깅 | 외부 화면인식 봇엔 상대적으로 무관. 단 접근성 서비스·오버레이·후킹은 별도 감시 가능 | 대체로 무관 |

### 6.4 확인 안 된 항목 (추정 금지)

- 랜덤다이스2의 안티치트 SDK 채택 여부/종류 — **확인 안 됨** (자매작 *Random Dice: Wars*는 AppGuard 충돌 FAQ가 존재 → 111%에 AppGuard 적용 이력은 있음)
- 넷마블 하이브 사용 — **근거 없음**
- 에뮬레이터 정책적 차단 여부 — **확인 안 됨** (설치·구동 자체는 가능해 보임)
- Google Play Games on PC 공식 지원 — **확인 안 됨**
- RD2 전용 약관/운영정책 문서 — **미발견** (111% 공통 약관으로 갈음)
- 매크로 사유로 **명시된** 제재 공지 — **미발견** (신고 기반 밴 불만만 확인)

---

## 7. 제안 리포 구조

```
C:\dev\rdom\
├─ CLAUDE_CODE_TODO.md          # Cowork에서 불가능한 작업 핸드오프
├─ docs\
│  ├─ 00_PRE_RESEARCH.md        # ← 이 문서
│  ├─ 01_GAME_SPEC.md           # M0 실측 결과 (보드/액션/UI 좌표)
│  └─ 02_ARCHITECTURE.md
├─ src\rdom\
│  ├─ capture\                  # dxcam / scrcpy 백엔드
│  ├─ perception\               # 셀 크롭 + CNN + 숫자 인식
│  ├─ input\                    # MaaTouch / scrcpy control + 지터
│  ├─ policy\                   # rules(JSON) / bc / rl
│  ├─ sim\                      # 자체 시뮬레이터 (M6)
│  └─ recorder\                 # 데이터 수집기
├─ assets\templates\            # 셀 템플릿·스프라이트
└─ data\                        # 플레이 로그 (git 제외)
```

---

## 8. 즉시 결정이 필요한 3가지

1. **운용 범위** — 읽기 전용 로그 수집 / PvE 자동화 / 협동·아레나 포함 중 어디까지? (§6.2)
2. **실행 경로** — A안 LDPlayer+dxcam(성능) vs B안 실기기+scrcpy(탐지 회피)
3. **최종 목표점** — M3(룰기반 자동 플레이)까지인가, M7(RL)까지인가? 학습 자체가 목적이면 M6 시뮬레이터가 핵심이 된다

---

## 출처

**게임**
- [나무위키 — 랜덤 다이스2](https://namu.wiki/w/%EB%9E%9C%EB%8D%A4%20%EB%8B%A4%EC%9D%B4%EC%8A%A42)
- [나무위키 — 랜덤 다이스2/주사위](https://namu.wiki/w/%EB%9E%9C%EB%8D%A4%20%EB%8B%A4%EC%9D%B4%EC%8A%A42/%EC%A3%BC%EC%82%AC%EC%9C%84)
- [Random Dice 2 Beginner Guide](https://www.oslink.io/blog/guide/random-dice-2-beginner-guide.html)
- [디지털투데이 — 랜덤다이스2 출시](https://www.digitaltoday.co.kr/en/view/92655/111percent-launches-random-dice-2-removes-gacha-system)
- [구글플레이](https://play.google.com/store/apps/details?id=com.percent.aos.randomdice2)

**캡처·입력**
- [dxcam](https://github.com/ra1nty/DXcam) · [PyPI](https://pypi.org/project/dxcam/)
- [scrcpy](https://github.com/Genymobile/scrcpy) · [py-scrcpy-client](https://github.com/leng-yue/py-scrcpy-client)
- [MaaTouch](https://github.com/MaaAssistantArknights/MaaTouch) · [minitouch](https://github.com/openstf/minitouch) · [MAA 연결 문서](https://docs.maa.plus/en-us/manual/connection.html)
- [LDPlayer CLI](https://www.ldplayer.net/blog/introduction-to-ldplayer-command-line-interface.html) · [MuMu ADB](https://www.mumuplayer.com/help/win/connect-adb.html)
- [WSA 지원 종료](https://github.com/microsoft/WSA/discussions/536)
- [adbutils](https://pypi.org/project/adbutils/) · [uiautomator2](https://pypi.org/project/uiautomator2/)
- [Win32 DPI](https://learn.microsoft.com/en-us/windows/win32/learnwin32/dpi-and-device-independent-pixels)

**인식·학습**
- [KataCR](https://github.com/wty-yy/KataCR) · [논문 arXiv:2504.04783](https://arxiv.org/abs/2504.04783) · [데이터셋](https://github.com/wty-yy/Clash-Royale-Dataset)
- [MAA](https://github.com/maaassistantarknights/maaassistantarknights) · [MaaAI](https://github.com/MaaAssistantArknights/MaaAI)
- [ClashRoyaleBuildABot](https://github.com/Pbatch/ClashRoyaleBuildABot) · [arknights-mower](https://github.com/ArkMowers/arknights-mower/)
- [Random-Dice-OpenCV](https://github.com/CasperKristiansson/Random-Dice-OpenCV) · [random_dice_bot](https://github.com/slavi010/random_dice_bot)
- [YARDS — 합성 데이터 논문](https://ceur-ws.org/Vol-2862/paper8.pdf)
- [OpenAI VPT](https://openai.com/index/vpt/) · [논문](https://ar5iv.labs.arxiv.org/html/2206.11795)
- [모바일 퍼즐게임 PPO (arXiv:2007.01542)](https://ar5iv.labs.arxiv.org/html/2007.01542)
- [PaddleOCR vs Tesseract](https://www.codesota.com/ocr/paddleocr-vs-tesseract)
- [멀티스케일 템플릿 매칭](https://pyimagesearch.com/2015/01/26/multi-scale-template-matching-using-python-opencv/)

**약관·탐지**
- [111퍼센트 이용약관](https://111percent.helpshift.com/hc/ko/3-random-dice-pvp-defense/faq/207-terms-of-service-1624542526/)
- [계정 밴 FAQ](https://111percent.helpshift.com/hc/en/18-random-dice-go/faq/593-my-account-has-been-banned/)
- [Change.org 청원 — 무차별 계정 차단](https://www.change.org/p/111-company-random-dice-blocked-accounts-indiscriminately)
- [Talsec — Emulators in Gaming: Threats and Detections](https://docs.talsec.app/appsec-articles/articles/emulators-in-gaming-threats-and-detections)
- [ClickPatrol — Mobile Game Bot Detection 2025](https://clickpatrol.com/mobile-game-bot-detection-in-2025-how-to-detect/)
- [Game Bot Detection (arXiv:1606.01426)](https://ar5iv.labs.arxiv.org/html/1606.01426)
- [NHN AppGuard](https://appguard.toast.com/)
- [BlueStacks 랜덤다이스2](https://www.bluestacks.com/ko/apps/strategy/random-dice-2-on-pc.html)
