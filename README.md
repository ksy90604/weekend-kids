# 🧺 주말 어디 가지?

**아이와 갈 곳을 날씨·예산·거리·영업 여부로 비교해 추천하는 웹 서비스**

🔗 https://ksy90604.github.io/weekend-kids/

## 왜 만들었나
주말마다 "애들이랑 어디 가지?"를 검색하면 블로그 글은 많지만, 정작 알고 싶은 건 따로 있었습니다.
**이번 주 토요일에, 우리 집에서, 이 예산으로, 그날 문 여는 곳이 어디인가.**
AI 챗봇에 물어보면 이미 문 닫은 곳을 추천하기도 했습니다. 그래서 "기억"이 아니라 **공식 데이터를 매일 새로 받아** 추천하는 도구를 직접 만들었습니다.

## 무엇을 하나
- 출발지·가족 구성(어른/영유아/유아/초등)·예산·이동 시간·주제(동물 먹이주기, 체험, 물놀이…)를 고르면
- 장소마다 **4가지 점수**를 매겨 순위를 냅니다
  - 🌤 날씨: 그 장소 좌표의 예보(기온·강수확률·미세먼지). 비 오면 실내, 더우면 물놀이, 가을엔 단풍 명소에 가점
  - 💰 비용: 입장료 × 인원 + 주차비 + 왕복 기름값
  - 🚗 거리: 출발지에서 예상 이동 시간
  - 🕘 영업: 그날 쉬는 요일·휴무일·운영 기간·축제 기간을 확인해 안 열면 제외
- 최대 3곳을 표로 **나란히 비교**, 항목별 우승에 👑
- 다녀온 사람들의 **리뷰(별점·한 줄 평·사진)**, 운영자에게 보내는 **문의·요청 게시판**

## 문제를 어떻게 풀었나
| 문제 | 해결 |
|---|---|
| 닫은 곳을 추천하면 안 된다 | 한국관광공사 TourAPI에서 **매일 새벽 자동 수집**(GitHub Actions). 목록에서 사라진 곳은 자동 제외, 카드마다 정보 수정일 표시 |
| 쉬는 날·요금이 자유 서술 텍스트 | "매주 월요일", "토요일~월요일", "7~8월만", "어른 4,000원 / 어린이 2,000원" 같은 문구를 정규식으로 구조화. "매월 첫째 월요일"처럼 매주가 아닌 휴무는 오탐 방지 |
| 하루 API 호출 한도 1,000회 | 수정일이 바뀐 곳만 상세 재조회, 한도 초과분은 다음 날 이어서 수집 |
| 서버 없이 운영 | 정적 사이트(GitHub Pages) + 브라우저에서 직접 호출하는 무료 날씨 API + 데이터 파일 커밋. 월 비용 0원 |
| 장소 600곳 날씨를 매번 조회하면 느리다 | 좌표를 약 10km 격자로 묶어 호출 수를 1/5로 줄이고, 카드는 20개씩 렌더링 |
| 리뷰·게시판 API가 없다 | 구글 폼으로 받고 구글 시트를 CSV로 읽음. 열 이름을 키워드로 찾아 질문 제목이 바뀌어도 동작 |
| 리뷰에 로그인을 요구하면 이메일이 시트에 쌓인다 | 응답 시트는 비공개로 두고, `IMPORTRANGE`+`QUERY`로 이메일 열만 뺀 공개 시트를 사이트가 읽음 |
| 관광공사에 없는 작은 업체 | **카카오 지도 검색으로 키즈카페·체험농장 등을 매주 자동 수집**(운영시간이 없어 "확인 필요"로 표시), 운영자가 JSON으로 직접 등록하거나, **방문자가 폼으로 제안** → GitHub Actions가 **카카오 지도 검색으로 실재 여부·지역·중복·업종을 자동 검증**해 통과하면 좌표·전화까지 채워 등록. 결과(등록/반려 사유)는 사이트에 표시 |
| 어르신·휴대폰 사용자 | 큰 터치 영역, 키보드 탐색, 다크 모드, 모바일 레이아웃, 접근성 속성 |

## 기술
- **프론트**: HTML / CSS / Vanilla JS (프레임워크·빌드 도구 없음)
- **데이터 수집**: Python 3 표준 라이브러리만 사용, 단위 테스트 포함
- **자동화**: GitHub Actions (cron) → 수집 → 변경 시 자동 커밋
- **외부 데이터**: 한국관광공사 TourAPI, Open-Meteo(날씨·대기질), Google Forms/Sheets
- **배포**: GitHub Pages

```
index.html / style.css / app.js   화면, 점수 계산, 비교, 리뷰·게시판
reviews-config.js                 구글 폼·시트 연결 설정
data/places.json                  수집된 장소 (자동 갱신)
data/custom-places.json           직접 등록 장소
scripts/fetch_places.py           TourAPI 수집·파싱
scripts/test_fetch_places.py      파싱 규칙 테스트
.github/workflows/update-places.yml  매일 새벽 3시 자동 갱신
```

## 배운 것
- 공공데이터는 "있다"와 "쓸 수 있다"가 다르다. 절반 이상이 자유 서술이라 파싱 규칙과 테스트가 핵심이었다.
- 무료 서비스를 조합하면 서버 없이도 사용자 입력(리뷰·요청)을 받을 수 있지만, **개인정보가 어디에 쌓이는지**를 먼저 설계해야 한다.
- 사용자 요청("게시판이 아래에 있어 불편")을 받아 바로 고치는 흐름을 게시판 자체로 운영해 봤다.

---

## 로컬 실행
```bash
python -m http.server 8766
```
http://localhost:8766 접속

## 장소 데이터 갱신 (TourAPI)
`scripts/fetch_places.py`가 서울·인천·경기의 관광지, 문화시설, 레포츠, 축제를 받아 아이와 갈 만한 곳만 골라 `data/places.json`을 만듭니다.

```bash
# 키 확인 (응답 형식 출력)
python scripts/fetch_places.py --check
# 전체 수집 (키는 실행 시 입력 또는 TOUR_API_KEY 환경변수)
python scripts/fetch_places.py
# API 호출 없이 저장된 데이터에 필터·파싱 규칙만 다시 적용
python scripts/fetch_places.py --reprocess
# 파싱 테스트 (키 불필요)
python scripts/test_fetch_places.py
```

GitHub 저장소 Settings → Secrets and variables → Actions에 `TOUR_API_KEY`를 등록하면 매일 자동으로 돌아갑니다.

## 직접 등록하는 장소
관광공사 데이터에 없는 곳은 [data/custom-places.json](data/custom-places.json)에 적습니다.
형식은 [data/custom-places.example.json](data/custom-places.example.json)을 보세요. push 하면 바로 사이트에 합쳐집니다.
좌표는 카카오맵에서 장소 검색 → 공유 → 주소 복사로 얻을 수 있습니다.

## 카카오 지도 검색으로 사설 장소 수집
관광공사에 없는 키즈카페·실내놀이터·체험농장·동물농장·눈썰매장은 `scripts/fetch_kakao.py`가
시/군/구 86곳 × 키워드로 카카오 지도를 검색해 `data/kakao-places.json`에 모읍니다 (매주 일요일 새벽, `update-kakao.yml`).
- 업종이 맞지 않는 곳(술집·숙박·주거 등)과 기존 장소와 겹치는 곳은 제외. 매번 전체를 다시 만들어 지도에서 사라진 곳은 자동 제거.
- 쉬는 날·요금 정보가 없어 카드에 "지도 검색" 배지와 "운영시간 정보 없음 · 전화로 확인하세요"로 표시되고, 영업 여부 필터에서 제외하지 않음.

```bash
KAKAO_REST_KEY=키 python scripts/fetch_kakao.py --sido 서울 --keyword 키즈카페 --dry-run
python scripts/test_fetch_kakao.py
```

## 방문자 장소 제안 → 자동 검증 등록
1. 구글 폼(질문: `장소 이름`, `지역 (시/군/구)`, `추천 이유`, `쉬는 날 (선택)`, `이용 시간 (선택)`, `요금 (선택)`, `닉네임 (선택)`) → 응답 시트를 뷰어 공개 → `reviews-config.js`의 `PROPOSALS`에 폼 링크와 CSV 주소 등록
2. [카카오 디벨로퍼스](https://developers.kakao.com)에서 앱을 만들고 **REST API 키**를 GitHub Secrets에 `KAKAO_REST_KEY`로 등록
3. `.github/workflows/verify-proposals.yml`이 6시간마다 `scripts/verify_proposals.py`를 실행
   - 카카오 키워드 검색 → 이름 유사도 0.6 이상 + 제안한 지역이 주소에 포함 + 술집·숙박 등 업종 제외 + 기존 장소와 500m 안 중복 제외
   - 통과: `data/custom-places.json`에 추가(좌표·주소·전화·지도 링크 자동), 반려: 사유 기록
   - 결과는 `data/proposals-status.json`에 쌓이고 사이트 "장소 제안하기" 화면에 표시
4. 잘못 등록된 곳은 `custom-places.json`에서 지우면 됨. 제안 시트의 `숨김` 열에 값을 적으면 그 제안은 무시

```bash
python scripts/test_verify_proposals.py          # 검증 로직 테스트 (키 불필요)
KAKAO_REST_KEY=키 python scripts/verify_proposals.py --dry-run
```

## 리뷰 · 요청 게시판 (구글 폼 + 구글 시트)
설정은 [reviews-config.js](reviews-config.js)에 적습니다. 비워 두면 해당 기능은 꺼집니다.

**요청 게시판**
1. 구글 폼(질문: `요청 내용`, `닉네임`) → 응답을 새 시트에 연결
2. 시트 공유: 링크가 있는 모든 사용자 → 뷰어
3. 응답 탭 오른쪽에 `상태`(접수/진행중/완료/보류 드롭다운), `답변`, `숨김` 열 추가
4. `csvUrl`에 `https://docs.google.com/spreadsheets/d/<시트ID>/gviz/tq?tqx=out:csv&gid=<탭gid>`

**리뷰** (구글 로그인 필요, 사진 첨부 가능)
1. 구글 폼(질문: `장소 ID`, `장소 이름`, `별점`, `한 줄 평`, `이용 적정 나이`, `파일 첨부`, `닉네임`)
   설정 → 응답 → 이메일 주소 수집: **확인됨**
2. 응답 시트는 **비공개** 유지 (이메일 포함)
3. 공개용 시트를 새로 만들고 A1에 이메일 열을 뺀 `QUERY(IMPORTRANGE(...))` 수식 → 뷰어 공개 → `csvUrl`에 등록
4. 폼의 "미리 채워진 링크"에서 `장소 ID`, `장소 이름` 항목의 `entry.숫자`를 `entries`에 등록
5. 드라이브의 "File responses" 폴더를 뷰어 공개하면 사진이 사이트에 표시됨

열 이름은 키워드로 찾으므로 질문 제목이 조금 달라도 됩니다. 운영자가 `숨김` 열에 아무 값이나 적으면 그 줄은 표시되지 않습니다.
형식 예시: [data/reviews.sample.csv](data/reviews.sample.csv), [data/requests.sample.csv](data/requests.sample.csv)

## 알아두기
- 가격·운영시간은 공공데이터 기준이라 현장과 다를 수 있습니다. 임시 휴관은 늦게 반영됩니다.
- Open-Meteo 무료 API는 비상업용입니다. 상업 전환 시 기상청 API 등으로 교체해야 합니다.
- 사진: 한국관광공사 (저작권 유형별 출처 표기 조건 확인 필요)
