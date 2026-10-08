// 우리 가족 리뷰 / 요청 게시판 설정 (구글 폼 + 구글 시트)
// 비워 두면 해당 기능은 꺼져요. 리뷰가 꺼지면 "네이버 리뷰 보기" 링크만 보여요.
// 설정 방법은 README의 "우리 가족 리뷰"와 "요청 게시판" 항목을 보세요.
window.REVIEWS = {
  // 구글 폼 "미리 채워진 링크"의 주소 (viewform 까지)
  formUrl: "https://docs.google.com/forms/d/e/1FAIpQLSfYBO2yhLo3Lnps9Sg2grebpykxz8MQj6Yn5oKavCzZkJvpdg/viewform",
  // 미리 채워진 링크에서 확인한 항목 ID. 예: { id: "entry.123456", name: "entry.789012" }
  entries: { id: "entry.1919307592", name: "entry.232855612" },
  // 응답 시트(링크가 있는 모든 사용자-뷰어)의 CSV 주소. gid 는 응답 탭의 gid.
  // 응답 원본 시트는 비공개(이메일 포함). 공개 시트가 IMPORTRANGE+QUERY 로 이메일 열을 뺀 사본을 보여 준다.
  csvUrl: "https://docs.google.com/spreadsheets/d/1LkEQ5ZVuZnYWu54gfV4_-_Icf9kkAlQ2fL1ZtXt24YY/gviz/tq?tqx=out:csv&gid=0",
};
// 장소 제안: 구글 폼으로 받고, GitHub Actions 가 카카오 지도 검색으로 검증해 자동 등록 (scripts/verify_proposals.py)
window.PROPOSALS = {
  formUrl: "",
  csvUrl: "",
};
window.REQUESTS = {
  formUrl: "https://docs.google.com/forms/d/e/1FAIpQLSc0dbdVS5Miz3WB3GOdUbuABYnhWxgU_123UpCIsJVFZQkxyg/viewform",
  csvUrl: "https://docs.google.com/spreadsheets/d/1oZLCUMIY-NNloTYZYRfs1rD_NpBgqcr5zg-XQ9mTHNE/gviz/tq?tqx=out:csv&gid=1339568842",
};
