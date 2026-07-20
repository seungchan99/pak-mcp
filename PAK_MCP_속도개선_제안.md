# PAK MCP 서버 속도 개선 제안 — 일괄 행 설정 경로

작성일: 2026-07-16
대상: PAK NVH MCP 서버 (`output_rms` / `configure_rows` 를 제공하는 Python COM 자동화 서버)
근거: pak-nvh 스킬 문서 + 실측 타이밍(아래) + PAK Graphic Definition COM 동작 관찰

---

## 1. 문제 (측정된 사실)

Beetle_TP_G2 CH1 을 2D APS 50곡선으로 오버레이 출력하며 측정:

| 조건 | 소요시간 | 곡선당 |
|---|---|---|
| A-가중 O, 캡처 O | 57.5초 | ~1.15초 |
| A-가중 O, 캡처 X | 61.6초 | ~1.23초 |
| A-가중 X, 캡처 X | 55.7초 | ~1.11초 |

- 캡처(스크린샷)는 병목이 아님 — 껐을 때 오히려 편차 범위 내에서 더 걸림.
- A-가중 오프는 ~10%(≈6초)만 단축 — 소음 행마다 DarstFilter 열고/닫는 비용.
- **시간의 대부분은 곡선 수에 선형 비례** → 행마다 반복되는 설정/재계산이 근본 원인.

## 2. 근본 원인 (가설)

`output_rms` 는 클라이언트 입장에선 "한 번 호출"이지만, 내부에서 행(row)을 하나씩
순차 설정한다. 세 가지가 곡선당 비용을 만든다고 추정:

1. **"Apply changes directly"(즉시 적용)가 켜진 상태에서 행을 설정** — 스크린샷의
   Graph. par. 패널에 `Apply changes directly ☑` 가 항상 켜져 있음. 이 경우 속성을
   바꿀 때마다 PAK가 그래프를 **재계산/재렌더**할 가능성이 높음. 50행이면 재렌더 50회.
2. **행마다 DarstFilter(주파수 가중) 서브객체 open/release** — 스킬 문서상 A-가중은
   `Item.DarstFilter.Fweight="A"` 로 설정하며, 이때 Datentyp/GesPegel/TrackingParams 를
   먼저 release 해야 함. 행마다 이 open/release가 반복됨.
3. **Average[Q] 등 행별 속성 설정이 개별 COM 왕복** — 3D→2D 축약(`Par. stat. param.`)을
   행마다 세팅.

## 3. 제안하는 변경

### 3-A. (최우선) 일괄 구성 중 "즉시 적용" 차단 → 마지막에 1회 렌더

일괄 설정 시작 시 즉시적용을 끄고, 전체 행 구성 후 한 번만 `Graphicoutput` 실행.

```python
def _bulk_apply(graphdef, rows, *, final_output=True):
    prev = graphdef.ApplyDirectly          # 현재 상태 저장
    graphdef.ApplyDirectly = False         # ← 행 설정 중 재렌더 차단 (즉시적용 OFF)
    try:
        for r in rows:
            _configure_one(graphdef, r)     # 재렌더 없이 속성만 세팅
    finally:
        graphdef.ApplyDirectly = prev
    if final_output:
        graphdef.Graphicoutput()            # 마지막에 딱 1회 렌더
```
> 정확한 프로퍼티명(`ApplyDirectly`)은 서버가 이미 체크박스를 다루는 코드가 있으면
> 그 이름을 재사용. 없으면 UI Automation 으로 체크박스 토글 후 복원.
> **이 변경만으로 재렌더 N회 → 1회가 되어 가장 큰 단축 기대.**

### 3-B. `configure_rows`(일괄)에 `stat_parameter` 추가

현재 `configure_rows` 는 한 COM 세션에서 일괄 처리하지만 `stat_parameter` 인자가 없어,
3D(Throughput APS)→2D 오버레이 비교에는 못 쓰고 `configure_row` 를 행마다 호출해야 함.
`configure_rows` 의 각 행 객체에 `stat_parameter` (그리고 `blocksize`, `x_from`,
`x_to`, `y_type`)를 받도록 확장.

```python
# rows[i] 에 아래 키 허용
#   stat_parameter: "Average [Q]"  → 토큰 "Mittelwert   [  Q]"
#   blocksize, x_from, x_to, y_type
if "stat_parameter" in r:
    item.Statpar = STAT_TOKENS[r["stat_parameter"]]   # 3D→2D 축약
```
→ Average[Q] 오버레이도 `configure_rows` **단일 호출**로 처리 가능.

### 3-C. 가중 필터 open/release 중복 제거

행들이 같은 가중(예: 전부 A)이면 DarstFilter 를 행마다 열지 말고, 필요한 행에 대해
**한 번만** 열어 batch 로 처리하거나, 직전 값과 같으면 skip.

```python
if r.get("weighting") != last_weighting:
    _set_weighting(item, r["weighting"])   # 바뀔 때만
    last_weighting = r["weighting"]
```

### 3-D. (선택) `output_rms` 도 3-A 경로 재사용

`output_rms` 내부 행 루프를 3-A(`ApplyDirectly=False` 감싸기)로 감싸면 RMS 표
출력도 동일하게 빨라짐. 밴드패스 Sum-level 설정도 같은 배치 안에서 처리.

## 4. 기대 효과

| 변경 | 예상 효과 |
|---|---|
| 3-A 즉시적용 차단 | **가장 큼** — 재렌더 N→1. 50곡선에서 수십 초대 단축 기대 |
| 3-B 일괄 stat_parameter | 비교 오버레이의 COM 왕복 대폭 감소 |
| 3-C 가중 중복 제거 | ~10% (실측 근거) |
| 3-D output_rms 적용 | RMS 표 출력에도 동일 이득 |

## 5. 호환성 · 검증

- **하위호환**: 3-B 의 새 키는 모두 선택(optional). 미지정 시 기존 동작 유지.
- **회귀 검증**: 개선 전/후로 동일 rows 를 출력해 **RMS 값·곡선이 완전히 동일**한지
  확인(수치 불변이 필수). 본 세션의 20~50Hz / 5~100Hz 값(예: Front Right 57.5/58.5/57.9)을
  기준값으로 사용 가능.
- **성능 측정**: 50곡선 기준 개선 전 ~57초 → 목표치 대비 단축폭 기록.
- **주의**: `ApplyDirectly` 복원을 `finally` 로 보장(예외 시에도 원상복구), 사용자가
  보던 즉시적용 상태를 바꾸지 않도록.

## 6. 요약

이 개선은 **스킬(SKILL.md) 이 아니라 PAK MCP 서버 코드**에서 진행해야 하며, 핵심은
"행 설정 중 재렌더를 막고 마지막에 1회만 렌더"(3-A)와 "일괄 경로에 Average[Q] 지원
추가"(3-B) 두 가지다. 3-A 는 관측된 선형 비용의 주원인(즉시적용 재렌더)을 직접 겨냥하므로
가장 효과가 클 것으로 예상된다.
