# 01 — 게임/환경 실측값

- 1차: 2026-09-15, docs/04 게이트 G0~G9 (세션은 `data/_deprecated_v1/`로 격리 — A1/A2 결함 상태 기록)
- 2차: 2026-09-16, docs/06 게이트 H0~H5. 기준 세션: `data/sessions/2026-09-16_0151_9d89` (schema v2)

## 에뮬레이터

- **2026-10-16부터 Google Play Games (PC)** — 창 제목 `랜덤 다이스 2 - <계정>` (`^랜덤 다이스 2` 매칭), 2번 모니터(dxcam output 1)
- 크롬(창 장식): 왼쪽 사이드바 132px, 타이틀바 72px. 게임 화면 = 렌더 자식창 `CROSVM_1`
- adb 없음 → 입력은 `CROSVM_1`에 PostMessage(마우스/Esc=BACK). 커서 안 움직이고 포커스 불필요
- 게임 재실행: `googleplaygames://launch/?id=com.percent.aos.randomdice2&lid=2&pid=1` (바탕화면 바로가기와 동일)
- (이전) LDPlayer 14.0.25.2, adb `127.0.0.1:5555`, `wm size` 1440x2560
- **rdF04부터 두 에뮬레이터를 동시에 사용**: GPG = 서폿봇(배속봇 계정), 입력은 위의 PostMessage / LDPlayer = 기어봇(대변먹는자 계정), 입력은 adb, 설정 `config/recorder_ld.toml`. 위 GPG 설명은 그대로이며, 두 봇이 같은 협동방에서 함께 플레이한다

## 게임

- 랜덤다이스2 v1.1.1, 세로고정, 패키지 `com.percent.aos.randomdice2`
- 홈/전투 화면 모두 서피스 전체 렌더 — 레터박스 없음 (insets 0/0/0/0)
- **가로 스트레치 (A6, 해소됨)**: LDPlayer는 android 서피스(0.5625)를 렌더 영역에 맞춰 늘린다.
  1차 검증 당시 렌더 영역 0.705 → 가로 ~25% 스트레치 상태로 기록됐음(구세션 폐기 사유 중 하나).
  **창을 9:16에 맞춰 재조정해 제거** — APK 스프라이트 합성 계획 유효

## 창 기하 — 수집 표준 (Windows 배율 100%, 주 모니터 3840x2160)

- **client 1200x2104** (2026-09-16 리사이즈 고정; 예: (1887,29)-(3087,2133)). **창 크기 변경 금지** — env fingerprint가 깨진다
- **chrome insets (H2 확정, g2b_chrome.py 실측)**: `{left=0, top=40, right=39, bottom=0}`
  - top 40 = 테두리 1px + 타이틀/탭바 (row 39까지 RGB(36,36,47)계, row 40부터 게임)
  - right 39 = 아이콘 사이드바 (col 1161부터 RGB(31,31,41))
  - left 0 / bottom 0 — 이 창 위치에선 경계 없음
  - 100% 배율 기준. 배율을 바꾸면 재실측 필수
- **content = 1161x2064, aspect 0.56250 == android 1440x2560** (스트레치 0)
- DPI 재현성(1차 G3): 100/125/150% 모두 (u,v) spread ≤ 0.00086 (기준 0.002)

## 캡처/인코딩 실측 (schema v2: capture.covers = "content")

- effective FPS 30.0, dup ratio 0.0012~0.0024, stalls 0
- 코덱 h264_nvenc (`-preset p4 -rc vbr -cq 23`), 출력 720x1280 (`plan_out_res`, content 비율 유지)
- 프레임 정합: frames.jsonl == ffprobe 디코딩 수 (전 세션 1:1, 세그먼트 회전 포함)
- **비트레이트 실측 (H5)**: 2.91Mbps = **1.31GB/h** (v2, 콘텐츠만 캡처). v1(크롬 포함 1499x2108→720x1280)은 1.71GB/h였음
- 30시간 추정 39~51GB, 디스크 여유 423GB → **cq 23 유지 결정** (CRF 26~28 비교는 M1 전 과제)

## 동기화 (H4, R8 rdom-replay)

- 좌표 변환 정확: 3개 구간(0~30/35~55/58~78초)에서 초록 마커가 눌린 대상 위
- **오프셋 초기 추정값: 80ms** — 40ms와 120ms가 육안으로 구분 불가(30fps에서 2~3프레임)라 중간값 채택. R6 캘리브레이션의 초기값
- 드래그 트래킹 (2026-09-16 `2026-09-16_0248_a1ad` 138개 전수 검증): `to` == 실제 release 좌표 138/138,
  `path_n` == 기록된 move 수 138/138, 경로 샘플 최대 간격 median 0.018 / max 0.075 (norm) — **끝까지 트래킹됨**

## R6 캘리브레이션 후보

- 1차 G3 기준점 `(u,v) ≈ (0.100, 0.775)`는 **구 좌표계(크롬 포함) 기준 — v2에선 재실측 필요**
- `calib.button_uv = [0.93, 0.05]`는 여전히 플레이스홀더

## M0 — 보드 그리드 / 조작 좌표 (2026-09-16 실측)

모든 좌표는 **content 정규화 (u,v)** — schema v2 세션의 액션 좌표와 동일계.
그리드는 3세션 드래그 pickup 259개를 5×3 클러스터링해 도출(밝기 프로파일보다 신뢰도 높음),
전투 프레임(`data/sessions/2026-09-16_0449_1b5f` seg1 f900)과 육안 교차검증.

**내 필드 = 하단 보드 5열 × 3행 = 15칸** (소환 버튼 바로 위, "투 페어" 바 영역).
상단 보드는 협동 상대(TOP)이며 조작 대상 아님 — 파싱하지 않음.

- 열 중심 u: **0.284 / 0.390 / 0.499 / 0.610 / 0.717** (간격 균일 ~0.108)
- 행 중심 v: **0.551 / 0.621 / 0.690** (간격 균일 ~0.069)
- **원근 왜곡 없음** — 행·열 간격이 전 구간 균일(3D 리뉴얼에도 보드는 평면 격자). 셀 인덱스 = row*5 + col
- content 픽셀(1161×2064) 환산 — 열 x: 330/453/579/708/833, 행 y: 1137/1282/1424

**조작 어휘 (탭 1701개 핫스팟 클러스터링):**
| 조작 | 좌표 (u,v) | 근거 |
| --- | --- | --- |
| 소환 (summon) | **0.50, 0.855** | 최다 탭 ~550회. 녹색 버튼 |
| 병합 (merge) | 셀 A→셀 B 드래그 | 위 15칸 좌표 |
| 주사위 강화 | ~0.20, 0.94 (좌하단) | 탭 n=28, "주사위 강화" 버튼 |
| 청 서포터(파괴) | **0.19, 0.867** (소환 왼쪽 노란버튼) | 파괴 드래그 종점 2건 + 육안 확정. 셀→여기 드래그, 쿨90s |
| (미확인) 상단영역 탭 | ~0.40–0.60, 0.22 | 탭 n=116. 상단 보드/보스 타겟 추정 — **의미는 사용자 플레이 지침에서 정의** |

숫자 UI 위치 (인식 대상, M1): SP/골드 ~(0.50,0.80), 소환코스트 ~(0.50,0.885),
타이머 좌하단 ~(0.18,0.86), 웨이브 ~(0.16,0.72). 정밀 크롭 박스는 M1에서 확정.

## 미니게임 — 군밀 대청소 (rdF05)

- Flow: event screen -> `대청소 시작!` (costs a ticket; x1 or x10) -> 2 gauges per run -> reel (stops by itself) -> flight and distance. The user presses `대청소 시작!` by hand; the bot only plays the gauges.
- Gauge layout: a horizontal bar made of colored segments, a triangle that sweeps along the bar, and a `멈춰` button.
- Zones and the text shown for a stop: yellow = `완벽해!`, purple = `쿨`, blue = `나이스`. The goal is yellow.
- The stop registers on UP (finger release), not on DOWN: the bot holds `멈춰` and releases at the planned moment.
- Speed and the position of the yellow segment are random for every gauge. There is no time limit.
- On the recording one end-to-end sweep takes 0.38-0.64 s depending on the gauge speed.

## 열린 항목

1. 상단영역 탭(u~0.4-0.6, v~0.22)의 게임적 의미 — 사용자 플레이 지침에서 정의 예정
2. 숫자 UI 정밀 크롭 박스 — M1 인식 레이어에서 확정
