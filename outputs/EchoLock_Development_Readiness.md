# EchoLock 개발 준비 문서

**대회:** AI Builders Challenge with IBM Bob — August Challenge  
**선택 주제:** Advance Space Exploration with AI  
**프로젝트:** EchoLock — Intent-Preserving Command Escrow for Deep-Space Missions  
**핵심 문장:** *A command can be correct when sent—and dangerous when received. EchoLock adapts the action without betraying the intent.*  
**문서 상태:** 구현 착수 전 기준선  
**작성 기준일:** 2026-08-23

---

## 1. 프로젝트 결정 사항

### 1.1 해결할 문제

심우주 통신에는 수분에서 수십 분의 지연이 발생한다. 지상에서 명령을 작성하고 전송할 당시에는 안전했더라도, 명령이 우주선에 도착하거나 실제로 실행될 때는 배터리, 온도, 자세, 통신창, 장비 상태가 달라질 수 있다. EchoLock은 전송 오류나 고장 자체가 아니라 **시간 경과로 명령의 전제와 실행 맥락이 낡아지는 문제**를 다룬다.

### 1.2 확정된 핵심 구조

> **Mission Intent Envelope → State Drift Report → Intent-Safe Patch → Delta Certificate**

- **Mission Intent Envelope (MIE):** 원본 명령과 별도로 목표, 전제, 절대 금지조건, 우선순위, 유효기간, 수정 허용범위를 봉인한다.
- **State Drift Report (SDR):** 전송 당시 예상 상태와 도착·실행 당시 실제 상태의 차이를 계산하고, 깨진 전제를 식별한다.
- **Intent-Safe Patch (ISP):** 원본 명령을 변경하지 않고, 허용된 범위 안에서만 지연·축소·대체하는 별도 패치를 생성한다.
- **Delta Certificate:** 원본과 패치의 차이, 변경 이유, 보존된 목표, 안전 검증 결과, 예상 자원 영향을 재현 가능한 기록으로 반환한다.

### 1.3 변경하지 않을 설계 원칙

1. 원본 명령은 불변이며 덮어쓰지 않는다.
2. 생성형 AI는 대안 후보와 설명을 만들 수 있지만 최종 안전 판정자는 아니다.
3. 하드 안전조건은 결정론적 규칙 엔진이 검증한다.
4. 검증을 통과하지 못한 패치는 실행할 수 없다.
5. 모든 판정은 동일 입력에서 재현 가능해야 한다.
6. 목표 보존과 안전 보존을 별도로 측정한다.
7. PoC임을 명시하고 실제 비행 인증 또는 운용 가능성을 주장하지 않는다.

### 1.4 판정 상태

- **EXECUTE:** 원본 명령을 그대로 실행한다.
- **ADAPT:** 검증된 Intent-Safe Patch를 붙여 실행한다.
- **DEFER:** 허용된 지연 범위 안에서 조건 회복 또는 통신창을 기다린다.
- **REJECT:** 하드 안전조건, 유효기간 또는 수정 권한을 위반하므로 실행하지 않는다.

---

## 2. 선행기술 비교 및 독창성 경계

EchoLock은 onboard constraint checking이나 autonomous scheduling 자체를 발명했다고 주장하지 않는다. 독창성은 **지연 명령에 목표와 수정 권한을 함께 전달하고, 원본을 보존한 별도 패치와 검증 증거를 반환하는 결합 구조**에 둔다.

| 선행기술·프로젝트 | EchoLock과 겹치는 기능 | EchoLock의 차별점 | 유사 위험 | 개발 대응 |
|---|---|---|---|---|
| [JPL MEXEC](https://ai.jpl.nasa.gov/public/projects/mexec/) | 실행 직전 제약검사, 지연·중단, 상태 기반 실행 조정 | 지상 운영자의 목표·전제·수정 허용범위를 별도 봉인하고 원본 명령과 패치를 감사하는 구조 | 높음 | 단순 precondition checker로 구현하지 말고 MIE와 Delta Certificate를 데모의 중심에 둔다. |
| [Intelligent Spacecraft Autonomous Operations 특허](https://patents.google.com/patent/US20090157236A1/en) | just-in-time 자원·제약검사, 재스케줄링, 우선순위 적용 | 원래 목적을 보존하는 제한된 패치와 목표 보존 정량화 | 높음 | “실행 직전 재검증이 최초”라는 표현을 금지한다. 원본 불변·패치 방식과 수정 권한 경계를 강조한다. |
| [NASA TaskSAT](https://github.com/nasa-jpl/tasksat) | 사전조건, 불변조건, 사후조건, 시간·자원 제약의 형식 검증 | 인간의 명령 의도와 허용 가능한 의미 변화까지 다루는 지연 통신 워크플로 | 중간~높음 | 형식 제약 검증을 경쟁 기술이 아닌 안전 검증 계층의 설계 근거로 삼는다. |
| [NASA Aerie/PlanDev](https://github.com/NASA-AMMOS/aerie) | 활동 모델, 시뮬레이션, 스케줄·제약·명령 확장 | 도착 시점 상태 드리프트와 원본 명령에 부착되는 검증 패치 | 중간 | 범용 임무 계획기가 아니라 “uplink-to-execution intent escrow”로 범위를 좁힌다. |
| [ESA 협력 PASEOS](https://github.com/aidotse/PASEOS) | 배터리·열·방사선·통신 제약을 반영한 우주 활동 시뮬레이션 | 명령 의도, 수정 권한, 패치, 증명서 워크플로 | 중간 | 공개된 물리 모델의 개념을 참고하되 EchoLock의 평가 데이터와 표현은 독자적으로 만든다. |
| [NASA cFS Limit Checker](https://github.com/nasa/LC) | 텔레메트리 임계치 감시와 자동 대응 | 특정 지연 명령의 목적 보존과 제한된 대안 생성 | 낮음~중간 | 단순 임계치 경보 화면에 머물지 않고 원본·현재 상태·패치·증거의 연결을 보여준다. |
| [Machine Intent Contracts](https://github.com/maccessUK/MIC) | 목표, 권한, 정책, 제한, 실행 증거를 구조화 | 심우주 지연, 우주선 상태 드리프트, 임무 명령 패치 | 중간 | `Intent Contract`를 고유명처럼 사용하지 않고 `Mission Intent Envelope`를 프로젝트 용어로 사용한다. |
| [IntentMesh](https://github.com/joshualamerton/Intentmesh-agent2agent) | Intent Contract, 제약 평가, counterfactual simulation, 대안 계획 | 우주선 명령의 전송·도착 시간 차이와 비행 안전 검증 | 중간~높음 | 범용 에이전트 거버넌스가 아닌 time-of-arrival command semantics를 명확히 증명한다. |
| [QAINET](https://qai.ai/) | 우주 자율성, bounded intent contract, 검증 경로, 실행 증거 | 공개 정보상 지연된 지상 명령의 원본 보존 패치 구조는 확인되지 않음 | 중간 | 세계 최초 주장을 피하고 공개 자료 기준의 기능 차이만 주장한다. |
| [NASA MuSCAT](https://github.com/nasa/muscat) | 우주선 상태와 자율 알고리즘 평가용 시뮬레이션 | 지연 명령의 의도 보존 및 패치 승인 계층 | 낮음 | 범용 시뮬레이터와 경쟁하지 말고 평가 환경으로서의 시뮬레이션만 구현한다. |

### 2.1 허용되는 포지셔닝

> EchoLock does not claim to invent onboard constraint checking. It explores a different layer: preserving an operator’s mission intent when a delayed command must be adapted at execution time, without modifying the original command.

### 2.2 금지할 주장

- “세계 최초의 우주선 명령 검증 시스템”
- “기존 우주선에는 실행 직전 안전검사가 없다”
- “AI가 우주선의 안전을 보장한다”
- “실제 임무 생존율을 입증했다”
- “NASA 또는 ESA 수준의 비행 인증을 충족한다”

### 2.3 유사 사례 추적 시 변경 기준

다음 네 요소 중 세 개 이상을 동일한 심우주 명령 맥락에서 구현한 신규 사례가 발견되면 높은 유사도로 분류한다.

1. 목표·전제·불변조건·수정 권한을 함께 보내는 명령 봉투
2. 전송 상태와 도착 상태의 명시적 drift 분석
3. 원본을 보존한 제한적 명령 patch
4. 목표 보존과 안전조건 통과를 증명하는 반환 기록

높은 유사 사례가 발견되기 전에는 핵심 구조를 변경하지 않는다.

---

## 3. 대회 필수요건 및 실격 방지

### 3.1 참가·제출 요건

- 참가자는 만 18세 이상이며 고등교육기관 재학생이어야 한다.
- 개인 참가 또는 1~5명 팀 참가가 가능하다.
- 모든 참가자는 대회 플랫폼에 개별 등록해야 한다.
- August Challenge에서 팀당 하나의 프로젝트만 제출한다.
- 제출물은 영어로 작성한다.
- IBM Bob을 프로젝트의 핵심 개발 도구로 사용한다.
- 작동하는 프로토타입 또는 PoC를 제공한다.
- 팀원마다 IBM SkillsBuild의 IBM Bob 관련 학습 활동을 최소 1개 완료한다.
- 공개 GitHub 저장소를 제공한다.
- 최대 3분 길이의 공개 데모 영상을 제공한다.
- 프로젝트와 팀원 정보, GitHub 링크, 영상 링크를 BeMyApp 제출 페이지에서 최종 제출한다.
- 공식 마감은 2026년 8월 31일 11:59 PM ET이며, 8월의 미국 동부시간을 기준으로 2026년 9월 1일 12:59 PM KST에 해당한다.

### 3.2 README 필수 내용

- Problem statement
- Solution description
- AI/technical approach
- Architecture
- Selected challenge theme: Advance Space Exploration with AI
- Why the solution matters for space exploration
- How IBM Bob was used
- Setup and demo instructions
- Test and evaluation results
- Limitations and safety disclaimer
- License and third-party attribution

### 3.3 제출 증빙

- IBM SkillsBuild 활동 완료 화면과 수료증·배지
- 과정명, 완료일, 사용 계정 이메일 기록
- IBM Bob 개발 로그
- 주요 Bob 프롬프트와 결과 요약
- Bob이 생성하거나 개선한 테스트 및 문서 기록
- 타사 데이터·라이브러리의 출처와 라이선스
- 영상과 GitHub 링크의 비로그인 공개 접근 확인
- 제출 완료 화면 캡처와 확인 이메일

**확보된 학습 증빙:** `How IBM Bob and AI Tools Are Changing the Way Solutions Are Built` — 2026-08-23 완료. 수료증 원본은 공개 저장소가 아닌 개인 보관 위치에 유지한다.

### 3.4 심사 기준 대응

| 심사 기준 | EchoLock에서 보여줄 증거 |
|---|---|
| Technical Execution | 결정론적 안전 엔진, 상태 시뮬레이터, 네 판정 상태, 재현 가능한 테스트, 원본과 패치의 불변성 |
| Innovation | MIE→SDR→ISP→Delta Certificate의 연결 구조와 기존 constraint checker와의 차이 |
| Challenge Fit | 심우주 통신 지연과 도착 시점 상태 변화라는 우주 고유 문제 |
| Feasibility | 좁은 로버 데이터 전송 시나리오, 명시적 제약, 브라우저 기반 PoC, 실제 시스템과의 통합 경계 |
| Real-World Impact | 안전 때문에 모든 작업을 중단하지 않고 제한된 자원에서 과학 목표를 최대한 보존하는 효과 |

---

## 4. 기능 요구사항

### 4.1 MVP 범위

주 시나리오는 **화성 로버 과학 이미지 전송 명령**으로 고정한다. 동일한 원본 명령이 상태 변화에 따라 EXECUTE, ADAPT, DEFER, REJECT로 달라지는 것을 보여준다.

### 4.2 필수 기능

#### A. 명령 생성 및 봉인

- 사용자가 지상 명령과 예상 실행 시각을 정의할 수 있어야 한다.
- 전송 당시 우주선 예상 상태를 저장해야 한다.
- MIE에 목표, 전제, 하드 불변조건, 우선순위, 유효기간, 허용된 수정 종류와 최대 변경량을 기록해야 한다.
- 원본 명령과 MIE에는 변경 탐지를 위한 고유 ID와 무결성 식별값이 있어야 한다.

#### B. 통신 지연 시뮬레이션

- 명령 전송부터 도착까지의 시간을 설정할 수 있어야 한다.
- 지연 동안 배터리, 열, 자세, 통신 가능 여부, 데이터 저장량 등의 상태가 변해야 한다.
- 정상·저전력·과열·통신창 상실 등 고정 시나리오를 재현할 수 있어야 한다.

#### C. State Drift Report

- 전송 당시 전제와 도착 상태를 필드별로 비교해야 한다.
- 깨진 전제와 위험해진 하드 불변조건을 구분해야 한다.
- 각 drift가 원본 명령의 실행 결과에 미치는 영향을 표시해야 한다.

#### D. Counterfactual 평가

- 원본 명령을 실행했을 때의 예상 결과를 실행 전에 계산해야 한다.
- 배터리 잔량, 최고 온도, 전송된 유효 이미지 수, 통신창 사용량을 예측해야 한다.
- 실행 강행, 전체 거부, EchoLock 패치의 결과를 같은 기준으로 비교해야 한다.

#### E. Intent-Safe Patch

- MIE가 허용한 변경만 후보로 생성해야 한다.
- 최소 이미지 수, 최대 지연, 압축 허용 여부, 출력 감소 허용 여부 같은 범위를 준수해야 한다.
- 원본 명령을 직접 수정하지 않고 별도 patch로 저장해야 한다.
- 후보마다 목표 보존 점수와 예상 자원 영향을 계산해야 한다.
- 안전 검증을 통과한 후보 중 목표 보존이 가장 높은 후보만 선택해야 한다.

#### F. 결정론적 안전 게이트

- 하드 불변조건을 코드 기반 규칙으로 검증해야 한다.
- 생성형 AI의 설명이나 추천과 독립적으로 동작해야 한다.
- 동일 입력에는 동일 판정과 동일 검증 결과를 반환해야 한다.
- 안전 규칙을 통과하지 못한 후보는 사용자 인터페이스에서도 실행 불가로 표시해야 한다.

#### G. 판정 및 Delta Certificate

- 결과를 EXECUTE, ADAPT, DEFER, REJECT 중 하나로 반환해야 한다.
- 원본 명령 ID, 상태 drift, 적용 patch, 보존 목표, 위반 방지 조건, 예측 결과, 판정 시간을 기록해야 한다.
- Delta Certificate만으로 판정 과정을 다시 확인할 수 있어야 한다.
- AI 설명과 결정론적 검증 결과를 시각적으로 구분해야 한다.

#### H. 데모 화면

- 전송 시점 상태와 도착 시점 상태를 나란히 표시한다.
- 원본 명령은 읽기 전용으로 고정한다.
- 변경된 항목은 patch 형태로 강조한다.
- 안전조건 통과·실패와 목표 보존 점수를 보여준다.
- 네 판정 시나리오를 빠르게 재생할 수 있어야 한다.
- baseline과 EchoLock 결과 비교표를 제공한다.

### 4.3 비기능 요구사항

- 데모는 비로그인 상태에서 실행 가능해야 한다.
- 시나리오는 고정 seed 또는 고정 입력으로 재현 가능해야 한다.
- 판단 근거와 단위가 화면에 명시되어야 한다.
- 외부 API 장애가 있어도 사전 정의된 데모 시나리오는 실행 가능해야 한다.
- 비밀키와 개인정보를 저장소에 포함하지 않는다.
- 타사 데이터와 라이브러리 라이선스를 명시한다.
- 안전 검증 실패 시 fail-closed 방식으로 동작한다.

### 4.4 MVP에서 제외할 범위

- 실제 우주선 또는 NASA 시스템 연결
- 고정밀 궤도·열·전력 비행 해석
- 실제 명령 송신
- 승무원 생명유지 판단
- 다중 우주선 군집 제어
- 비행 인증 또는 정식 형식검증 완료 주장
- LLM의 단독 실행 승인

---

## 5. 검증 계획과 지표

### 5.1 평가 데이터셋

- 최소 60개, 목표 100개의 고정 시나리오를 만든다.
- EXECUTE, ADAPT, DEFER, REJECT의 정답 시나리오를 균형 있게 포함한다.
- 정상, 경계값, 복수 고장, 만료, 센서 불확실성, 허용되지 않은 수정 사례를 포함한다.
- 각 시나리오에는 입력 상태, 예상 판정, 허용 patch, 금지 patch, 근거가 있어야 한다.
- 평가 세트는 데모용 예제와 분리한다.

### 5.2 핵심 지표

| 지표 | 정의 | MVP 합격 기준 | 목표 기준 |
|---|---|---:|---:|
| Safety violation rate | 승인된 실행안 중 하드 불변조건을 위반한 비율 | 0% | 0% |
| Unsafe-command interception recall | 위험한 원본 명령을 ADAPT·DEFER·REJECT한 비율 | ≥95% | 100% |
| Safe-command pass rate | 안전한 원본 명령을 EXECUTE한 비율 | ≥90% | ≥95% |
| False rejection rate | 안전한 명령을 잘못 REJECT한 비율 | ≤10% | ≤5% |
| Adaptation validity rate | 선택된 patch가 수정 권한과 모든 안전조건을 만족한 비율 | 100% | 100% |
| Goal preservation score | 원래 목표 대비 패치 후 보존된 가중 효용 | 평균 ≥0.70 | 평균 ≥0.80 |
| Resource margin improvement | 원본 강행 대비 최소 안전 여유 개선량 | 양수 | 시나리오별 근거 제시 |
| Decision latency | 판정과 검증서 생성에 걸린 시간 | 로컬 p95 ≤2초 | p95 ≤1초 |
| Replay consistency | 같은 입력을 반복했을 때 동일 판정·증명서 핵심값 비율 | 100% | 100% |
| Certificate completeness | 필수 증거 필드가 모두 포함된 비율 | 100% | 100% |

### 5.3 비교 baseline

- **Blind Execute:** 도착 상태를 재검사하지 않고 원본 명령을 실행한다.
- **Hard Reject:** 전제 하나라도 깨지면 전체 명령을 거부한다.
- **Rule-Only Delay:** 조건을 만족할 때까지 지연하되 목표 기반 수정은 하지 않는다.
- **EchoLock:** 허용 범위 안에서 안전한 패치를 선택하고 목표 보존을 최적화한다.

### 5.4 필수 테스트 범주

- 단위·경계값 테스트
- 원본 명령 불변성 테스트
- 허용되지 않은 patch 차단 테스트
- 하드 불변조건 우회 시도 테스트
- 만료된 명령 테스트
- 복수 제약 충돌 테스트
- AI가 잘못된 대안을 제안하는 경우의 차단 테스트
- 동일 입력 재현성 테스트
- 누락되거나 비정상적인 상태 데이터 처리 테스트
- 네 판정 상태 end-to-end 테스트

### 5.5 데모용 대표 시나리오

**원본 명령:** 오늘 촬영한 암석 이미지 10장을 고출력으로 지구에 전송한다.

1. **EXECUTE:** 배터리·열·통신 상태가 전제와 일치한다.
2. **ADAPT:** 배터리가 예상보다 낮아 이미지 수·해상도·출력을 허용 범위에서 줄인다.
3. **DEFER:** 통신창이 닫혀 있으나 최대 지연 범위 안에 다음 통신창이 열린다.
4. **REJECT:** 열 한계와 최소 예비전력 조건이 동시에 위반되고 허용된 patch로 해결할 수 없다.

---

## 6. IBM Bob 활용 및 증빙 계획

IBM Bob은 프로젝트의 주 개발 도구로 사용한다. 제품 런타임에서 Bob이 우주선 안전 결정을 직접 내린다고 표현하지 않는다.

### 6.1 Bob에게 맡길 개발 작업

- 요구사항을 추적 가능한 작업으로 분해
- MIE, SDR, ISP, Delta Certificate 데이터 모델 설계
- 상태 전이와 자원 계산 모델 설계
- 결정론적 안전 규칙 및 판정 우선순위 설계
- 테스트 시나리오와 경계값 자동 생성
- property-based test 및 회귀 테스트 설계
- 실패 테스트 원인 분석과 수정 제안
- README, 아키텍처, 평가 보고서 초안 작성
- 데모 흐름과 3분 영상 대본 초안 작성

### 6.2 Bob 사용 증빙

`docs/bob-development-log.md`에 날짜별로 다음을 기록한다.

- 사용한 목표와 프롬프트 요약
- Bob이 제안한 설계 또는 변경
- 사람이 수락·수정·거부한 내용과 이유
- Bob이 만든 테스트와 발견한 결함
- 수정 전후 검증 결과
- 최종 산출물에 반영된 위치

비밀번호, 토큰, 개인정보, 내부 계정정보는 기록하지 않는다.

---

## 7. IBM Bob 시작 프롬프트

아래 프롬프트를 IBM Bob에 그대로 전달하되, 저장소 위치와 선택한 기술 스택만 실제 값으로 보완한다.

```text
You are the primary AI development partner for EchoLock, a proof-of-concept being built for the August “Advance Space Exploration with AI” theme of the AI Builders Challenge with IBM Bob.

Do not write implementation code yet. Begin by analyzing the requirements, identifying ambiguities, proposing a traceable architecture and creating a phased implementation plan with acceptance criteria and tests.

PROJECT PROBLEM
Deep-space commands can be safe when transmitted from Earth but unsafe when received or executed because battery, thermal, attitude, communication-window and subsystem states may change during the communication delay. EchoLock must evaluate this state drift while preserving the operator’s original mission intent.

FIXED CORE ARCHITECTURE
Mission Intent Envelope → State Drift Report → Intent-Safe Patch → Delta Certificate

NON-NEGOTIABLE DESIGN RULES
1. The original command is immutable and must never be overwritten.
2. The Mission Intent Envelope separately records the goal, assumptions, hard invariants, priority, expiry and explicit adaptation authority.
3. The State Drift Report compares expected send-time state with arrival/execution-time state and identifies broken assumptions.
4. An Intent-Safe Patch may only use adaptations explicitly allowed by the envelope.
5. Generative AI may propose alternatives and explanations, but a deterministic safety engine must make the final validation decision.
6. A candidate that fails any hard invariant or adaptation-authority check must fail closed.
7. Every result must be classified as EXECUTE, ADAPT, DEFER or REJECT.
8. Every decision must produce a reproducible Delta Certificate that records the original command identity, drift, patch, preserved goals, safety checks, predicted resource effects and decision timing.
9. The PoC must not claim flight readiness, formal certification or guaranteed spacecraft safety.

MVP SCENARIO
A Mars rover receives a delayed command to transmit ten scientific rock images at high power. The same original command must produce four demonstrable outcomes under different arrival states:
- EXECUTE when all assumptions remain valid.
- ADAPT when reduced image count, resolution or transmission power can safely preserve useful science.
- DEFER when a communication window will reopen within the allowed delay.
- REJECT when no authorized patch can satisfy thermal and reserve-power invariants.

REQUIRED CAPABILITIES
- Immutable original command and Mission Intent Envelope
- Configurable communication-delay and spacecraft-state simulation
- State Drift Report
- Counterfactual comparison of blind execution, hard rejection and EchoLock adaptation
- Authorized patch generation and ranking by goal preservation
- Deterministic safety gate independent of AI-generated explanations
- Delta Certificate and audit trail
- A browser-based demonstration interface
- Fixed, reproducible scenarios and an evaluation suite of at least 60 cases, targeting 100

PRIMARY METRICS
- 0% safety violations among approved actions
- at least 95% unsafe-command interception recall
- at least 90% safe-command pass rate
- no more than 10% false rejection rate
- 100% adaptation-authority compliance
- average goal-preservation score of at least 0.70
- 100% replay consistency
- local p95 decision latency no greater than two seconds

NOVELTY BOUNDARY
Do not claim that EchoLock invents onboard constraint checking, autonomous scheduling or just-in-time resource validation. Those capabilities exist in systems such as JPL MEXEC and prior spacecraft autonomy work. EchoLock’s contribution is the combined workflow that transmits mission intent and adaptation authority, measures arrival-state drift, attaches a verified patch without modifying the original command, and returns evidence of intent and safety preservation.

IBM BOB EVIDENCE REQUIREMENT
Maintain a development log describing your recommendations, generated tests, defects found, proposed corrections, human decisions and resulting validation changes. Never place credentials or personal data in the log.

YOUR FIRST RESPONSE MUST CONTAIN ONLY:
1. A concise restatement of the system boundary.
2. A list of ambiguities or decisions that must be resolved before coding.
3. A proposed component architecture and responsibility table.
4. A requirements-to-tests traceability matrix.
5. A phased implementation plan ordered by technical risk.
6. Acceptance criteria for the first vertical slice.
7. The exact files and documents you propose to create, without creating them yet.

Wait for explicit approval before generating implementation code or modifying files.
```

---

## 8. 개발 체크리스트

### A. 참가 및 학습

- [x] BeMyApp 대회 등록을 완료했다.
- [ ] 모든 팀원이 개별 등록했다.
- [x] 개인 참가자의 IBM SkillsBuild IBM Bob 학습 활동을 최소 1개 완료했다.
- [x] 학습 완료 이메일과 수료증 링크를 확보했다.
- [x] August 우주 탐사 주제를 선택했다.

### B. 구현 착수 전

- [ ] 본 문서를 IBM Bob에게 제공했다.
- [ ] Bob의 첫 분석 응답을 검토했다.
- [ ] 미해결 요구사항과 단위·임계값을 결정했다.
- [ ] MVP와 제외 범위를 승인했다.
- [ ] 공개 저장소와 라이선스를 결정했다.
- [ ] Bob 개발 로그 형식을 만들었다.
- [ ] 타사 자료와 라이선스 사용 방침을 정했다.

### C. 핵심 도메인 설계

- [ ] 원본 명령 불변성 규칙이 명시됐다.
- [ ] Mission Intent Envelope 필드가 확정됐다.
- [ ] State Drift Report 계산 규칙이 확정됐다.
- [ ] 허용 patch 종류와 최대 변경량이 정의됐다.
- [ ] 하드 불변조건과 소프트 목표가 분리됐다.
- [ ] 목표 보존 점수 계산법이 정의됐다.
- [ ] EXECUTE·ADAPT·DEFER·REJECT 우선순위가 정의됐다.
- [ ] Delta Certificate 필수 증거 필드가 확정됐다.

### D. 첫 수직 슬라이스

- [ ] 하나의 원본 이미지 전송 명령이 입력된다.
- [ ] 전송 상태와 도착 상태가 표시된다.
- [ ] drift가 계산된다.
- [ ] 원본 강행 결과가 예측된다.
- [ ] 하나의 허용 patch가 생성된다.
- [ ] 결정론적 안전 게이트가 patch를 검증한다.
- [ ] ADAPT 또는 REJECT 판정이 생성된다.
- [ ] 원본이 변경되지 않았음을 확인한다.
- [ ] Delta Certificate가 생성된다.
- [ ] 동일 입력 재실행 결과가 일치한다.

### E. 전체 MVP

- [ ] 네 판정 상태의 대표 시나리오가 모두 동작한다.
- [ ] Blind Execute, Hard Reject, Rule-Only Delay baseline이 구현됐다.
- [ ] 최소 60개 평가 시나리오가 준비됐다.
- [ ] 모든 하드 안전조건 테스트가 통과한다.
- [ ] AI의 잘못된 후보가 결정론적 게이트에서 차단된다.
- [ ] 핵심 지표가 자동 계산된다.
- [ ] 목표 기준 미달 지표의 원인과 한계가 기록됐다.
- [ ] 외부 API 없이도 데모가 재현된다.
- [ ] 비로그인 사용자가 데모에 접근할 수 있다.

### F. IBM Bob 활용 증빙

- [ ] 주요 Bob 작업이 날짜별로 기록됐다.
- [ ] Bob이 생성한 테스트와 발견한 결함이 기록됐다.
- [ ] 사람의 수락·수정·거부 판단이 기록됐다.
- [ ] 수정 전후 평가 결과가 기록됐다.
- [ ] README의 `How IBM Bob Was Used`와 개발 로그가 일치한다.
- [ ] 영상에서 Bob의 실질적 기여를 짧고 명확하게 보여준다.

### G. 공개 저장소와 README

- [ ] 문제, 솔루션, AI 접근, 아키텍처, 선택 주제를 영어로 설명한다.
- [ ] 기존 선행기술과 EchoLock의 차이를 과장 없이 설명한다.
- [ ] 설치·실행·데모 절차를 검증했다.
- [ ] 평가 데이터와 결과를 공개했다.
- [ ] 한계, PoC 면책, 안전 경계를 명시했다.
- [ ] 라이선스와 타사 출처를 명시했다.
- [ ] 비밀키·개인정보·불필요한 대용량 파일이 없다.

### H. 3분 데모 영상

- [ ] 0:00–0:20에 통신 지연과 stale command 문제를 설명한다.
- [ ] 0:20–0:40에 네 단계 구조를 보여준다.
- [ ] 동일 명령의 EXECUTE와 ADAPT 차이를 시연한다.
- [ ] DEFER와 REJECT를 빠르게 보여준다.
- [ ] 원본 불변과 patch 구조를 확대해 보여준다.
- [ ] 결정론적 안전 검증과 Delta Certificate를 보여준다.
- [ ] baseline 대비 지표를 보여준다.
- [ ] IBM Bob의 테스트 생성·결함 발견·개선 기여를 보여준다.
- [ ] 총 길이가 3분을 넘지 않는다.
- [ ] 영상 링크가 공개 상태다.

### I. 최종 제출

- [ ] GitHub 저장소가 공개 상태다.
- [ ] 데모 링크와 영상 링크를 로그아웃 상태에서 확인했다.
- [ ] 프로젝트 및 팀원 정보가 정확하다.
- [ ] 요구된 모든 링크와 설명이 영어로 입력됐다.
- [ ] 마감 하루 전 제출을 완료했다.
- [ ] 제출 완료 화면과 확인 이메일을 보관했다.
- [ ] 공식 마감 전 최종 제출 상태를 다시 확인했다.

---

## 9. 구현 착수 승인 기준

다음 네 조건을 모두 충족하면 IBM Bob에게 코드 생성을 승인한다.

1. 팀원별 필수 IBM SkillsBuild 학습 활동과 증빙이 완료됐다. **(개인 참가 기준 완료: 2026-08-23)**
2. MIE 필드, 하드 불변조건, 수정 권한, 목표 보존 점수가 결정됐다.
3. 첫 수직 슬라이스의 입력·예상 출력·합격 테스트가 확정됐다.
4. IBM Bob이 제안한 아키텍처와 요구사항-테스트 추적표를 사람이 검토했다.

이전에는 구현 코드를 생성하지 않는다.
