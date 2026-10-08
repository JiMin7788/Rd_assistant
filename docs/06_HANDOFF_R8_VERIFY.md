# 06 — Claude Code 핸드오프 2차: 크롬 수정 + R8 동기화 검증

- 대상: Claude Code (로컬 Windows, `C:\dev\rdom`)
- 선행: `docs/04_HANDOFF_R1_R5_VERIFY.md` G0~G9 통과 (2026-09-15)
- 필독: **`docs/05_AMENDMENTS.md`** — 이번 변경 6건의 근거. 04 문서와 충돌하면 05가 우선

---

## 0. 무엇이 왜 바뀌었나

1차 게이트는 통과했지만, 저장된 캡처 프레임을 분석해 보니 결함 2건이 있었다.

- **A1**: LDPlayer 상단 탭바 40px가 "게임 콘텐츠"에 포함돼 있었다. 모든 `(u,v)`가 게임이 아니라 창 기준이었다
- **A2**: 출력 해상도가 소스 종횡비와 무관하게 고정돼 영상이 가로로 21% 눌렸다

둘 다 **자기모순이 없어서 어떤 검증에도 걸리지 않는** 종류다. 1차 세션 5개는 이 상태로 기록됐으므로 **학습에 쓰지 말고 폐기**한다.

Cowork에서 108개 테스트를 통과시켰다 (기존 76 + 신규 32). Windows 부분만 미검증이다.

### 하지 말 것

- 기존 `data/sessions/*`를 학습 데이터로 쓰지 말 것. 참고용으로만 남긴다
- R6(캘리브레이션)·dataset builder를 새로 구현하지 말 것
- **장시간 수집을 아직 시작하지 말 것.** H4까지 통과해야 한다
- 게이트 기준값을 낮춰 통과시키지 말 것

---

## 1. 게이트

### H0 — 재설치 및 오프라인 테스트 `[자동]`

```powershell
cd C:\dev\rdom
.\.venv\Scripts\activate
pip install -e .            # rdom-replay 진입점이 새로 생겼다
python -m unittest discover -s tests -v
```

**합격**: `Ran 108 tests ... OK`, **skip 0건**.

새로 추가된 것 중 다음 3개가 반드시 통과해야 한다:

- `test_replay_overlay.TestPlanOutRes.test_portrait_capture_keeps_its_aspect` (A2)
- `test_replay_overlay.TestChromeProbe.test_ldplayer_shaped_frame` (A1, 실제 프레임 구조 회귀)
- `test_replay_overlay.TestRenderEndToEnd.test_renders_the_requested_window` (R8)

---

### H1 — 가로 스트레치 확정 `[사람]` ★ 최우선

**이게 먼저다.** 답에 따라 수집 환경 자체가 달라진다 (`05_AMENDMENTS.md` A6).

```powershell
adb connect 127.0.0.1:5555     # LDPlayer 설정에서 ADB 디버깅을 먼저 켤 것
adb shell wm size
adb shell wm density
```

**기록할 것**: `Physical size` / `Override size` 값.

판정:

| `wm size` 결과 | 의미 | 조치 |
| --- | --- | --- |
| 창 렌더 영역과 같은 비율 (~0.705) | 스트레치 없음 | 그대로 진행 |
| 1440x2560 (0.5625) | **가로 25% 스트레치 중** | LDPlayer 창/해상도를 9:16에 맞춰 스트레치 제거 후 H2부터 다시 |

**왜 중요한가**: 스트레치가 있으면 APK에서 추출한 스프라이트로 합성 학습 데이터를 만드는 계획이 깨진다. 합성 이미지는 원본 비율인데 캡처는 늘어나 있어 맞지 않는다. 라벨 비용 최대 절감 수단이라 타협 대상이 아니다.

ADB를 못 켜면 그 사실을 보고하고 H2로 진행하되, **수집 시작 전에는 반드시 해결**한다.

---

### H2 — 크롬 인셋 실측 `[사람]`

게임을 홈화면이 아니라 **실제 전투 화면**에 두고 (배경이 화면 끝까지 차야 판단이 쉽다):

```powershell
python tools/verify/g2b_chrome.py --title "^LDPlayer" --out chrome_check.png
```

1. 출력된 edge 프로파일에서 색이 바뀌는 지점을 직접 확인한다
2. 제안값과 비교한다. `0`이 나온 항목은 "경계를 못 찾음"이므로 프로파일을 보고 직접 정한다
3. `chrome_check.png`를 열어 **초록 테두리가 게임에 딱 붙고 에뮬레이터 픽셀이 하나도 안 들어갔는지** 확인한다
4. 확정값을 `config/recorder.toml`의 `[target.chrome]`에 쓴다

현재 config에 들어 있는 `{left=1, top=40, right=40, bottom=0}`은 2026-09-15 프레임에서 뽑은 값이다. **창 크기나 LDPlayer 설정이 그때와 다르면 반드시 다시 재야 한다.**

**합격**: PNG의 초록 테두리가 게임 영역과 정확히 일치. 출력되는 `content aspect`를 H1의 `wm size` 비율과 비교해 기록.

---

### H3 — 짧은 실주행 `[사람]`

```powershell
python -m rdom.recorder.record --config config/recorder.toml `
  --emulator-name LDPlayer --emulator-version 14.0.25.2 --instance LDPlayer-0 `
  --android-res <H1에서 확인한 값> --android-dpi <wm density> `
  --game-version 1.1.1 --gfx-preset <실제값>
```

60초 플레이, F9로 에피소드 한 번, F12 종료.

**합격**

- 시작 로그에 `content ... -> encoding ...`이 뜨고, **인코딩 해상도 종횡비가 content와 같다**
- `[warn] chrome insets are all zero` 경고가 **뜨지 않는다**
- `session.json`: `schema_version: 2`, `capture.covers: "content"`, `result.status: "OK"`
- `env.chrome`이 H2에서 정한 값과 일치
- `video/seg_00000.mp4`를 열어 **에뮬레이터 탭바와 사이드바가 안 보인다**

마지막 항목이 이번 수정의 핵심이다. 영상에 탭바가 보이면 크롬 인셋이 틀린 것이다.

---

### H4 — R8 동기화 육안 검증 `[사람]` ★ 수집 전 마지막 관문

H3 세션에 대해:

```powershell
$s = (Get-ChildItem data\sessions | Sort-Object Name | Select-Object -Last 1).FullName
rdom-replay --session $s --start-sec 10 --duration 20 --offset-ms 40
```

R6이 아직 없으므로 `--offset-ms`는 임시값이다. 40 / 80 / 120으로 3회 돌려 비교한다.

출력된 mp4를 보고 판정:

| 관찰 | 의미 |
| --- | --- |
| 초록 마커가 실제로 반응하는 UI 위에 있고, 빨강이 살짝 뒤처짐 | **정상** |
| 둘 다 아무 데도 안 걸침 | 좌표 변환이 틀림 (크롬 인셋 의심) → H2로 |
| 위치는 맞는데 둘 다 반응보다 이름 | 오프셋을 키워서 재시도 |
| 마커가 세로로만 어긋남 | top 인셋이 틀림 |
| 마커가 가로로만 어긋남 | left/right 인셋 또는 스트레치(H1) |

**합격**: 서로 다른 구간 3곳에서 초록 마커가 눌린 대상 위에 있다. 어느 `--offset-ms`가 가장 맞았는지 기록 — R6의 초기 추정값이 된다.

> 이 게이트를 통과하기 전에는 장시간 수집을 시작하지 않는다. 30시간을 모은 뒤 동기화가 틀렸다는 걸 알면 전부 버려야 한다.

---

### H5 — 용량 결정 `[자동+판단]`

`05_AMENDMENTS.md` A5: 실측 1.71GB/h로 산정치(1.3)보다 32% 크다. nvenc `-cq`는 x264 `-crf`와 스케일이 다르다.

H3 세션의 실제 비트레이트를 확인하고, 30시간 추정치를 계산해 디스크 여유와 비교한다.

```powershell
ffprobe -v error -show_entries format=bit_rate,duration -of json "$s\video\seg_00000.mp4"
```

선택지는 둘이다 — **결정만 하고 보고**할 것:

- `crf`를 26~28로 올려 용량을 줄인다 (인식 정확도 영향 가능, M1 전에 비교 필요)
- 51GB를 받아들인다 (디스크가 여유롭다면 이쪽이 안전)

---

## 2. 통과 후

1. `CLAUDE_CODE_TODO.md`에서 통과 항목만 제거
2. `docs/01_GAME_SPEC.md` 갱신: `wm size` 결과, 확정 크롬 인셋, content 해상도·종횡비, H4에서 가장 잘 맞은 offset, 실측 비트레이트
3. 기존 `data/sessions/*` 5개를 `data/_deprecated_v1/`로 옮긴다 (삭제하지 말 것 — 비교용)

## 3. 보고 형식

`docs/04` §5와 동일. 게이트별 한 줄, 실패는 상세히. 마지막에 다음 할 일 하나를 제안하고 끝낸다.
