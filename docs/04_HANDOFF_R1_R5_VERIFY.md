# 04 — Claude Code 핸드오프: recorder R1~R5 로컬 검증

- 대상: Claude Code (로컬 Windows, `C:\dev\rdom`)
- 작성: Cowork 세션, 2026-09-15
- 선행 문서: `docs/03_RECORDER_SPEC.md` (설계 근거), `CLAUDE_CODE_TODO.md` (미해결 목록)

---

## 0. 이 작업의 범위

Cowork에서 recorder 1차 구현(R1~R5)을 마쳤고, **플랫폼 비의존 로직은 76개 테스트로 전부 검증됐다.**
Windows API가 필요한 4개 모듈(`window` / `capture` / `hook` / `record`)은 **한 번도 실행된 적이 없다.**

너의 일은 **아래 게이트를 순서대로 통과시키는 것**이다. 구현을 확장하는 게 아니다.

### 하지 말 것

- 테스트가 통과하는데 코드를 "개선"하지 말 것. 무관한 리팩터링·포매팅 금지
- `docs/03_RECORDER_SPEC.md`를 고치지 말 것. 명세가 틀렸다고 판단되면 고치지 말고 §5 형식으로 보고
- R6(캘리브레이션) / R8(replay_overlay) / dataset builder를 새로 구현하지 말 것. 이번 범위 밖이다
- **장시간(30분 초과) 데이터 수집을 시작하지 말 것.** R8이 없어 동기화가 맞는지 확인할 방법이 아직 없다
- 게이트가 실패했는데 기준값(`--min-fps`, `tap_radius_n`, `max_dup_ratio` 등)을 낮춰서 통과시키지 말 것

### 실패 시 원칙

게이트가 실패하면 **거기서 멈추고** §5 형식으로 보고한다. 다음 게이트로 넘어가지 않는다.
단 원인이 명백한 단순 버그(오타, import 누락, Windows 경로 처리)면 고치고 재실행한 뒤 무엇을 고쳤는지 보고에 남긴다.

---

## 1. 게이트 목록

`[자동]`은 네가 혼자 돌릴 수 있고, `[사람]`은 사람이 게임 창에서 직접 조작해야 한다.
`[사람]` 게이트에 도달하면 **무엇을 해야 하는지 알려주고 대기**한다.

### G0 — 환경 준비 `[자동]`

```powershell
cd C:\dev\rdom
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install -e .
ffmpeg -version
ffprobe -version
```

**합격**: `pip install -e .`가 성공하고 ffmpeg/ffprobe 둘 다 버전을 출력한다.
**실패 시**: ffmpeg가 없으면 설치(`winget install Gyan.FFmpeg`) 후 새 셸에서 PATH 재확인.
Python이 3.11 미만이면 중단하고 보고 — `tomllib`이 3.11+ 전용이다.

---

### G1 — 오프라인 테스트 재현 `[자동]`

```powershell
python -m unittest discover -s tests -v
```

**합격 기준 (전부 만족해야 함)**

- `Ran 76 tests` … `OK`
- **skip이 0건**. `test_encoder`가 skip되면 ffmpeg를 못 찾은 것이고, 그러면 가장 중요한 검증이 안 돈 것이다
- 특히 다음 3개가 통과해야 한다:
  - `test_encoder.TestSegmentEncoder.test_decoded_count_matches_log_across_segment_rotation` — 세그먼트 회전을 넘어 `frames.jsonl` 줄 수 == ffprobe 디코딩 프레임 수
  - `test_geometry.TestViewport.test_click_is_reproducible_across_window_moves`
  - `test_events.TestR5Acceptance.test_r5_acceptance_100_taps_and_drags`

skip 유무 확인:

```powershell
python -m unittest discover -s tests -v 2>&1 | Select-String -Pattern "skipped|OK|FAILED"
```

**실패 시**: Linux에서는 전부 통과했으므로, 실패하면 Windows 고유 문제다(경로 구분자, fd 처리, ffmpeg 빌드 차이). 원인을 특정해서 보고.

---

### G2 — `window.py` 최초 실행 `[자동]` (에뮬레이터 실행 필요)

LDPlayer를 띄우고 랜덤다이스2를 실행한 상태에서:

```powershell
python -c "from rdom.recorder.window import *; set_dpi_awareness(); h=find_window('^LDPlayer'); print('hwnd',h); s=WindowState.read(h); print(s); print('client', s.client.as_tuple(), s.client.width,'x',s.client.height)"
```

**합격**: 예외 없이 `WindowState`가 출력되고, `client` 폭·높이가 에뮬레이터 창 크기와 맞는다.
**주의**: 창 제목이 `LDPlayer`로 시작하지 않으면 `--title` 정규식과 `config/recorder.toml`의 `window_title_re`를 실제 제목에 맞게 고친다. 인스턴스가 2개 이상 떠 있으면 `find_window`가 일부러 에러를 낸다 — 하나만 남기거나 정규식을 좁힌다.

---

### G3 — R1 수용 기준: 창 이동 재현성 `[사람]`

```powershell
python tools/verify/g3_repro.py --title "^LDPlayer" --rounds 10
```

게임 화면에서 **작고 고정된 UI 요소 하나**(모서리 아이콘 등)를 정한다. 매 라운드마다 창을 새 위치로 옮기고, 그 요소에 커서를 올린 뒤 Enter.

**합격**: `spread u`, `spread v` 모두 **< 0.002**, `distinct window positions` ≥ 2, `PASS` 출력.

**이어서 DPI 검증**: Windows 디스플레이 배율을 **100% → 125% → 150%** 로 바꿔가며 같은 명령을 3회 반복한다. 배율을 바꾼 뒤에는 에뮬레이터와 셸을 모두 재시작할 것(프로세스 DPI 인식은 시작 시 결정된다).

**합격**: 세 배율 모두에서 PASS. 스크립트가 출력하는 `dpi scale(s) seen` 값이 배율과 일치해야 한다(125% → 1.25).
**실패 시**: 125%/150%에서만 실패하면 `set_dpi_awareness()`가 안 먹은 것이다. 이건 실제 버그이므로 보고.

> 참고: 이 스크립트는 레터박스를 0으로 두고 클라이언트 rect 추적만 검증한다. 레터박스 검출은 G8에서 실제 프레임으로 확인된다.

---

### G4 — R2 수용 기준: 캡처 성능 `[자동]` (게임이 보이는 상태)

```powershell
pip install dxcam
python tools/verify/g5_capture.py --title "^LDPlayer" --seconds 60
```

**합격**: `effective fps >= 29.5`, `dup ratio < 0.02`, `PASS` 출력.

**실패 시 순서대로 확인**
1. LDPlayer의 FPS 설정이 30 이상인가 (설정 → 성능)
2. 에뮬레이터 창이 다른 창에 가려져 있거나 최소화돼 있지 않은가 — DXGI는 가려진 창을 갱신하지 않는다
3. 멀티모니터라면 `--monitor-index`를 0, 1… 로 바꿔가며 확인. 엉뚱한 화면을 잡고 있으면 dup이 치솟는다
4. 그래도 안 되면 `--fps 20`으로 재측정해 상한이 어디인지 파악해 보고. **기준값을 낮춰 통과시키지 말 것**

---

### G5 — 인코더 선택 확인 `[자동]`

```powershell
python -c "from rdom.recorder.encoder import probe_encoder; print('selected:', probe_encoder('h264_nvenc'))"
```

**합격**: `h264_nvenc` 또는 `libx264` 중 하나가 출력된다(둘 다 정상).
`libx264`로 떨어졌다면 G8 실주행에서 CPU 사용률을 확인하고, 게임 프레임에 영향이 있으면 보고.

---

### G6 — R4/R5 수용 기준: 실제 입력 `[사람]`

```powershell
pip install pynput
python tools/verify/g7_hook.py --title "^LDPlayer" --taps 50 --drags 50
```

에뮬레이터 창 안에서 **짧은 탭 50회 → 명확한 드래그 50회**(20px 이상 확실히) 실행 후 셸에서 Enter.

**합격**: `taps 50`, `drags 50`, orphan 0, outside 0, `PASS`.
**부분 실패**: 개수가 49/51처럼 근소하게 어긋나면 제스처가 애매했던 것이다. **`tap_radius_n`을 건드리지 말고 다시 시도**한다. 3회 재시도해도 계속 어긋나면 그 사실을 수치와 함께 보고.
**전량 실패**(0건 기록): 훅 자체가 안 붙은 것. pynput 설치와 권한을 확인하고 보고.

---

### G7 — 통합 실주행 60초 `[사람]`

```powershell
python -m rdom.recorder.record --config config/recorder.toml `
  --emulator-name LDPlayer --emulator-version <실제버전> --instance LDPlayer-0 `
  --android-res 1600x900 --android-dpi 240 `
  --game-version <실제버전> --gfx-preset high
```

시작 후 게임을 60초 정도 실제로 플레이한다. F9로 에피소드 시작/종료를 한 번 눌러보고, F12로 종료.

**합격**

- 종료 시 `OK` 출력, `FAIL` 줄이 하나도 없음
- `data/sessions/<id>/session.json`의 `result.status == "OK"`
- `result.verify.checks` 전 항목 `ok: true` (`skipped`는 허용)
- `frames.jsonl` 줄 수 ≈ 60 × 30 = 1800 ± 5%
- `video/seg_00000.mp4`가 실제로 재생됨
- `result.actions > 0`, `result.episodes == 1`
- `env.letterbox`가 실제 화면과 맞는가 — 레터박스가 없는데 0이 아니면 검출 임계값 문제

확인 명령:

```powershell
$s = Get-ChildItem data\sessions | Sort-Object Name | Select-Object -Last 1
Get-Content "$($s.FullName)\session.json" | ConvertFrom-Json | ConvertTo-Json -Depth 6
(Get-Content "$($s.FullName)\frames.jsonl").Count
```

**실패 시**: `result.verify.checks`에서 `ok:false`인 항목 이름과 `detail`을 그대로 보고. 특히 `segment_frame_counts` 실패는 **가장 심각한 결함**이다 — 인코더와 로그가 어긋났다는 뜻이고, 이 상태로 수집하면 모든 액션 라벨이 밀린다.

---

### G8 — 워치독 동작 확인 `[사람]`

G7과 같은 명령으로 시작한 뒤, **녹화 중에 에뮬레이터 창을 일부러 드래그해서 옮긴다.**

**합격**

- 몇 초 내에 녹화가 스스로 멈춘다
- `session.json`의 `result.status == "FATAL"`, `result.fatal == "window_changed"`
- `events.jsonl` 마지막에 `{"ev":"fatal","code":"window_changed", ...}`가 있고 `old`/`new` rect가 다르다
- **그때까지의 `frames.jsonl`과 mp4는 정상적으로 남아 있다** (데이터를 버리지 않는다)

**실패 시**: 창을 옮겼는데 녹화가 계속되면 조용한 데이터 손상 경로가 열려 있는 것이다. 최우선 버그로 보고.

---

### G9 — R9 30분 실주행 `[사람]`

G7과 같은 명령으로 30분 연속 녹화. 그동안 실제로 플레이한다.

**합격**

- `result.status == "OK"`
- `result.dup_ratio < 0.02`, `result.stalls == 0`
- `events.jsonl`에 `warn` 이벤트가 없거나, 있다면 `fps_drop`이 5건 미만
- 세그먼트 파일이 `segment_sec=600` 기준 **3개** 생성됨
- **용량**: 30분 = 약 0.65GB (산정치 1.3GB/시간). **±20% 안에 들어야 한다**
- 종료까지 걸리는 시간이 과도하지 않은가 (마지막 세그먼트 flush 대기)

**실패 시**: 용량이 산정치를 크게 벗어나면 CRF나 해상도 설정이 의도와 다른 것이다. `session.json`의 `capture` 블록을 실제 파일 크기와 함께 보고.

---

## 2. 게이트 통과 후 할 일

1. `CLAUDE_CODE_TODO.md`의 "지금 바로 할 것" 섹션에서 **통과한 항목만** 체크박스를 지운다. 미검증 항목을 임의로 지우지 말 것
2. 실측값을 `docs/01_GAME_SPEC.md`에 기록한다 (파일이 없으면 새로 만든다):
   - 에뮬레이터 창 client rect, 실제 해상도·DPI
   - 레터박스 insets 실측값
   - 측정된 effective FPS, dup ratio, 시간당 용량
   - 선택된 코덱
3. G3에서 정한 "고정 UI 요소"의 `(u,v)`를 기록해 둔다 — R6 캘리브레이션의 `button_uv` 후보가 된다

---

## 3. 참고: 알려진 제약

- `device_bash` 마운트 불가(2026-09-08 Windows 업데이트) 때문에 Cowork에서는 이 게이트들을 돌릴 수 없다. 그래서 너에게 넘긴다
- Cowork 컨테이너는 PyPI 접근이 막혀 있어 테스트를 `unittest`로 작성했다. 로컬에서 `pytest tests/`도 그대로 동작한다
- `config/recorder.toml`의 `calib.button_uv = [0.93, 0.05]`는 **플레이스홀더**다. R6를 구현하기 전에 G3에서 실측한 값으로 바꿔야 한다

---

## 4. 참고: 설계상 의도된 동작 (버그로 오인 금지)

| 현상 | 의도 |
| --- | --- |
| 창을 옮기면 녹화가 죽는다 | 맞다. 조용한 데이터 손상보다 시끄러운 중단이 낫다 (spec §1.3) |
| 사이드바 클릭이 기록되지 않는다 | 맞다. 콘텐츠 영역 밖은 전량 폐기 (spec §4.3) |
| 액션의 `t`가 뗄 때가 아니라 누를 때다 | 맞다. 의사결정 시점에 더 가깝다 (spec §3.2) |
| 3초 롱탭이 `drag`가 아니라 `tap`이다 | 맞다. 지속시간은 분류에 쓰지 않는다 (spec §4.2) |
| 캡처 지연·반응지연 보정이 안 돼 있다 | 맞다. 전부 dataset builder 담당 (spec §1.1) |
| 액션이 셀 인덱스가 아니라 `(u,v)`로 저장된다 | 맞다. 보드 그리드가 아직 미확정 (spec §1.2) |
| 큐가 넘치면 프레임을 버린다 | 맞다. 블로킹하면 `t`의 의미가 깨진다 (spec §5) |

---

## 5. 보고 형식

각 게이트마다 한 줄, 실패한 게이트는 상세히:

```
G0 환경 준비        PASS   ffmpeg 6.1.1, python 3.11.9
G1 오프라인 테스트   PASS   76 tests, 0 skipped
G2 window.py        PASS   client=(104,132,1704,1032) 1600x900
G3 재현성           FAIL   ← 아래 상세
G4 캡처 성능        (미실행 — G3 실패로 중단)
...

## G3 실패 상세
- 명령: python tools/verify/g3_repro.py --title "^LDPlayer" --rounds 10
- 출력: spread u=0.0081 v=0.0003 (tolerance 0.002)
- 관찰: 배율 100%에서는 PASS, 125%에서만 u 방향으로만 어긋남
- 추정 원인: <근거와 함께>
- 수정 여부: 안 함 / 했음(무엇을, 왜)
```

마지막에 **다음에 해야 할 일 한 가지**를 제안하고 끝낸다.
