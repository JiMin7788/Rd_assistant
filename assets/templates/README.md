# 주사위 스프라이트 템플릿 (M1 인식용)

2026-09-16 추출. 출처: `com.percent.aos.randomdice2` v1.1.1 `split_base_assets.apk`
→ `assets/bin/Data/*` (Unity Addressables, 해시명) → UnityPy로 Sprite 추출.

## dice/ — 보드 주사위 타일 150개 (52 패밀리)

파일명 = Unity 스프라이트명 (`Dice_<이름><변형>.png`). 배경 투명(RGBA).

**변형 접미사 1/2/3 = 렌더 각도** (눈금 레벨 아님):
- `1` 평면 정면 아이콘 (~147×171) — 메뉴/다이스 트리용
- `2` 약간 기울인 뷰 (~167×208)
- `3` 완전 3D 아이소메트릭 (~385×400) — **전투 보드에 표시되는 형태. 셀 템플릿 매칭은 이것 사용**

52 패밀리: Element, Gear, Joker, Flower, ICE, Ax, BINGO, BUBBLE, Blessing, Combo,
Crack, DEATH, Doom, Electric, Energy, Executioner, FLOW, Failure, Germ, Light, Lock,
Mine, Mutation, Neon, Pillar, Poison, Potion, Predator, Punch, ROYAL, Ray, Resonance,
Rock, SPEEDGUN, SawBlade, Slow, Sniper, Switch, TRANSFER, Thorn, Tyrant, Wind, fire,
shuriken, solar, summon, bomb, hammer, Adjust, Alignment, Glow, BrokenGrowth.

## 재추출 방법

```powershell
# 1) APK에서 bin/Data 풀기 (assets/apk/split_base_assets.apk 필요)
# 2) UnityPy로 Sprite 추출 — 필터 (?i)^dice_[a-z]+[0-9]$, skin 제외
```

## 주의 / 다음 단계 (M1)

- 보드 타일에는 **눈금(pip) 점**이 오버레이됨 — 스프라이트 자체엔 테마 심볼만 있음.
  pip 개수(1~7?) 인식은 별도 크롭+숫자/점 분류 필요
- 스킨 변형(`*_skin1`)은 제외함 — 기본 스킨만. 사용자가 스킨 쓰면 추가 추출 필요
- 이름=내부코드. 게임 내 한글명 매핑은 미작성 (M1/지침 작성 시 필요하면 `[percentlocalizationv2]` 번들에서 추출)
