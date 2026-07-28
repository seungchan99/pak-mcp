# PAK NVH 분석 파이프라인 설계 (PAK 전용)

> 대상: `PAK` + `PAK_Browser` MCP 서버 (PAK 6.4, Tcl COM 브리지)
> 원칙: **단일 COM 연결·순차 실행**, **모든 position 출력은 응답이 아니라 캡처로 검증**,
> **Sound(dB(A)) vs Vibration(선형) 분리**.
> 오케스트레이터 = Claude Desktop이 아래 6단계를 상태머신처럼 순서·조건·재시도로 조율.

---

## 0. 파이프라인 전체 흐름 (State Machine)

```
[S0 Preflight] → [S1 Discover] → [S2 Plan] → [S3 Execute] → [S4 Verify] ──ok──→ [S5 Report] → [S6 Persist*]
                                                   ▲                    │
                                                   └──── retry/fallback ─┘ (fail)
```

- 각 단계는 **성공 게이트**를 통과해야 다음으로 넘어간다.
- 실패 시 정해진 **fallback** 경로로 재시도하고, 2회 연속 실패면 사람에게 원인(캡처 포함)과 함께 중단 보고.
- `*` 표시(S6)는 **사용자가 명시적으로 요청할 때만** 실행.

---

## 1. 단계별 정의

### S0 — Preflight (환경 가드) : 배포환경 조용한 실패 예방
| 도구 | 목적 |
|---|---|
| `server_info` / `get_working_mode` | COM 연결 확인 + **position 기반 작업모드인지 검증**. 아니면 `set_working_mode`로 position-oriented 전환 (배포 이슈 1순위) |
| `reset_graphdef` | 깨끗한 Graphic Definition에서 시작 (재실행 안전) |
| 캡처 경로 존재 확인 | `C:/MCPProject_pak/` 없으면 저장 실패 → 존재 경로 지정 또는 폴더 마운트 |

**게이트:** 작업모드 = position-oriented AND 캡처 경로 쓰기 가능.

### S1 — Discover (데이터·채널 카탈로그) : PAK_Browser
| 도구 | 산출물 |
|---|---|
| `get_current_project` | 프로젝트/Job 확정 |
| `list_project_data` / `list_last_measurements` | 측정 이름 목록 (`Job/Name [CP]` 포맷) |
| `get_channels` | position/direction/quantity **라벨 원문** (예 `RR_KNUCKLE_LH 1 z +Z`) |

**규칙:** 이름은 **절대 가정하지 말고** 매번 조회. `get_channels` 라벨은 **바이트 단위 그대로** 다음 단계로 전달(접미사 제거 금지 → 채널1 조용한 폴백 발생).

**게이트:** 대상 측정·채널이 카탈로그에 실제 존재.

### S2 — Plan (분석 계획 수립, 도구 호출 없음)
1. **채널 분류:** Sound Pressure → A-weight 그룹 / Acceleration·토크·RPM·온도 → 선형 그룹. **절대 한 다이어그램에 Pa+m/s² 혼합 금지.**
2. **Track 결정 (빠르게 확정):**
   - 외부소음/정속/pass-by/타이어 → **Distance** (`Distance / S / Cart. coord.x`, -10~20 m)
   - 그 외 → **Time** (Min..Max)
3. **레이아웃:** 다이어그램 = 채널/포지션, 커브 = 측정/런(오버레이 비교). 3D(Throughput APS)는 `Average [Q]`로 2D 축약(3D 2개 동일 다이어그램 금지).
4. **분석 패밀리 → 도구 매핑 확정** (아래 표).
5. **rows JSON 생성** (한 번에 전체 행 구성).

> **레이아웃 규칙:** RMS 표는 `RMS.vas_dly`, **그 외 모든 출력은 `standard.vas_dly`** (도구가 자동 적용).

| 분석 | 도구 | 핵심 |
|---|---|---|
| Band-pass RMS 표 | `output_rms` | 밴드=X축 범위, `draw_table`, `sumlevel_token==BandpaÞ mag`, 레이아웃 `RMS.vas_dly` |
| 3D/2D APS | `configure_rows` / `configure_row`(오버레이 `Average [Q]`) | 32768/16384 |
| 1/1·1/3 Octave | `configure_octave_rows` | `fraction`, Average[Q] |
| Overall(전체레벨 vs 시간/RPM) | `configure_overall_rows` | 통계축약 금지, 추이곡선 |
| Order APS / Order complex | `configure_orderaps_rows` / `configure_ordercomplex_rows` | RPM track, max order=`Tp2spec_maxorder` |
| Detector(외부 LH vs RH) | `configure_detector_rows` | `track_preset` distance/speed/time |

**게이트:** rows JSON 완성 + 각 행에 weighting/track 계획 명시.

### S3 — Execute (렌더링)
- 계획된 `configure_*_rows` / `output_rms`를 **한 턴에 배치 호출**(PAK가 COM 하나로 직렬화하므로 왕복만 줄임).
- 마지막 행에서만 `output=true`로 **한 번 렌더**. **여러 번 output 금지.**
- Sound 채널은 도구가 `DarstFilter.Fweight=A`로 **자동 A-weight** (확인만).

**게이트:** 도구 응답 `ok` + 각 행 `weighting` 에코가 Sound=`A`.

### S4 — Verify (조용한 실패 차단) — 파이프라인의 핵심
> 응답의 `rows[].channel`은 **입력 에코**일 뿐, PAK가 실제 붙인 채널이 아니다. `ok`여도 그래프가 비었을 수 있다.

성공 = **두 조건 모두** 통과:
1. **토큰 검증:** RMS면 `sumlevel_token == "BandpaÞ mag"`(U+00DE), Sound면 축이 dB(A).
2. **시각 검증:** `graphic_output` 재호출 → `capture_viewer`(저장 경로 `C:/MCPProject_pak/view_shot.png`) → Read(PNG)로 범례/축/곡선/페이지 탭이 기대와 일치.

**Fallback:**
- 축이 dB(lin)로 나오면 `pak_eval`로 `DarstFilter.Fweight=A` 수동 적용.
- Read가 "outside connected folders" → 캡처 폴더 마운트 후 재Read(캡처 실패 아님).
- 캡처가 직전 화면이면 `graphic_output` 1회 더 + 새 파일명 재캡처.
- COM 잠금 → `release_all` 후 재시도.

**게이트:** 토큰+시각 2중 검증 통과. 2회 실패 시 중단·보고.

### S5 — Report
- **Sound / Vibration 그룹 분리** 후 각각 (dominant 채널·차수·RPM/거리 추이).
- RMS는 스크린샷 표에서 값(Test/pos/RMS)을 그룹별로 판독해 보고.
- 마지막에 짧은 **교차 상관**(예: "진동은 5·8차 높지만 소음으로는 2차만 방사").
- 물리량(토크/RPM/속도/온도/RMS)은 **선형축·단위 그대로**, 소음·차수는 dB 유지.

### S6 — Persist (요청 시에만)
- `save_graphdef`(사용자 명시 요청 한정), 다중 뷰는 `new_page`/`goto_page`로 분리, export.

---

## 2. 오케스트레이터 의사코드

```python
def pak_pipeline(request):
    preflight()                      # S0: working mode + capture path + reset
    cat = discover()                 # S1: project/measurements/channels (라벨 원문)
    plan = build_plan(request, cat)  # S2: 분류·track·레이아웃·rows JSON

    for attempt in range(2):
        execute(plan)                # S3: 배치 configure_* / output_rms, 1회 render
        v = verify(plan)             # S4: 토큰 + 캡처 2중 검증
        if v.ok:
            break
        plan = apply_fallback(plan, v)   # weighting/mount/refresh/release_all
    else:
        return abort(v)              # 원인 + 캡처와 함께 중단 보고

    report = summarize(v.capture)    # S5: Sound/Vibration 분리 + 교차상관
    if request.save:                 # S6
        persist(plan)
    return report
```

---

## 3. 교차 관심사 (Cross-cutting)
- **동시성:** COM 1개 → 항상 순차. 병렬 호출 금지, 왕복만 배치로 축소.
- **재시도:** 검증 실패는 예외가 아니라 정상 분기 → fallback 후 재실행.
- **관측성:** 각 단계 게이트 통과 여부를 로그로 남겨 어디서 깨졌는지 추적.
- **로케일:** 배포 PAK UI 언어 다르면 quantity 토큰(`Acceleration` vs `Beschleunigung`) 실패 가능 → 캡처로 드러남.

---

## 4. 최소 실행 예 (내부소음 RMS)
```
S0  get_working_mode → reset_graphdef
S1  get_current_project → list_project_data → get_channels
S2  rows = [{row,diagram,curve,measurement,position(라벨원문),direction,quantity}, ...]
S3  output_rms(rows, band_from, band_to, deactivate_beyond, capture=true)   # 레이아웃 RMS.vas_dly 자동
S4  sumlevel_token=="BandpaÞ mag" 확인 + view_shot.png Read로 표 확인
S5  Sound/Vibration 분리 보고
```
보통 **브라우저 조회 + output_rms + 이미지 Read = 3콜**로 끝난다.
```
```
