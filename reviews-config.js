// 우리 가족 리뷰 / 요청 게시판 설정 (구글 폼 + 구글 시트)
// 비워 두면 해당 기능은 꺼져요. 리뷰가 꺼지면 "네이버 리뷰 보기" 링크만 보여요.
// 설정 방법은 README의 "우리 가족 리뷰"와 "요청 게시판" 항목을 보세요.
window.REVIEWS = {
  // 구글 폼 "미리 채워진 링크"의 주소 (viewform 까지)
  formUrl: "https://docs.google.com/forms/d/e/1FAIpQLSfYBO2yhLo3Lnps9Sg2grebpykxz8MQj6Yn5oKavCzZkJvpdg/viewform",
  // 미리 채워진 링크에서 확인한 항목 ID. 예: { id: "entry.123456", name: "entry.789012" }
  entries: { id: "entry.1919307592", name: "entry.232855612" },
  // 응답 시트(링크가 있는 모든 사용자-뷰어)의 CSV 주소. gid 는 응답 탭의 gid.
  csvUrl: "https://docs.google.com/spreadsheets/d/14GQ1buJ4odIQr1aEeo4TV6BmiDFwBYtl2MTH74IzOs4/gviz/tq?tqx=out:csv&gid=475770353",
};
window.REQUESTS = {
  formUrl: "",
  csvUrl: "",
};
