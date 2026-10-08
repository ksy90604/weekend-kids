// ── 설정값 ────────────────────────────────────────────
const ORIGINS = [
  ["서울 강북(종로)", 37.5735, 126.9790], ["서울 강남", 37.4979, 127.0276], ["서울 강서", 37.5509, 126.8495],
  ["서울 동부(광진)", 37.5385, 127.0823], ["경기 고양", 37.6584, 126.8320], ["경기 성남", 37.4201, 127.1265],
  ["경기 수원", 37.2636, 127.0286], ["경기 용인", 37.2411, 127.1776], ["경기 안양", 37.3943, 126.9568],
  ["경기 부천", 37.5034, 126.7660], ["경기 의정부", 37.7381, 127.0337], ["인천", 37.4563, 126.7052],
];
const BUDGETS = [["무료만", 0], ["3만원", 30000], ["5만원", 50000], ["10만원", 100000], ["상관없음", Infinity]];
const DISTANCES = [["30분", 30], ["1시간", 60], ["1시간 반", 90], ["상관없음", Infinity]];
const PRIORITIES = [
  ["균형 있게", { weather: 1, cost: 1, dist: 1 }],
  ["날씨", { weather: 2.5, cost: 1, dist: 1 }],
  ["예산", { weather: 1, cost: 2.5, dist: 1 }],
  ["가까운 곳", { weather: 1, cost: 1, dist: 2.5 }],
];
// 주제 필터: [표시 이름, 데이터 태그...]. "festival"은 축제 기간이 있는 항목.
const THEMES = [
  ["🐑 동물 먹이주기", "feeding"], ["🐾 동물", "animals"], ["🎨 체험·만들기", "craft"],
  ["🔭 과학·우주", "science"], ["🏛️ 박물관·전시", "museum"], ["🏊 물놀이", "water"], ["🛷 눈썰매", "snow"],
  ["🌳 꽃·숲·단풍", "nature", "bloom", "foliage"], ["🎠 놀이공원", "play"], ["🦀 갯벌", "tide"], ["🎉 축제", "festival"],
];
const FAMILY = [["adult", "어른"], ["baby", "영유아 (0~3세)"], ["kid", "유아 (4~7세)"], ["school", "초등학생"]];
const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];
const FUEL_PER_KM = 150; // 기름값 대략 (원/km)

const state = {
  origin: 0, coords: null,
  family: { adult: 2, baby: 0, kid: 1, school: 1 },
  budget: 4, distance: 3, priority: 0, themes: [],
  day: 0, compare: [], limit: 20,
};
let places = [];
let days = [];        // [{date, weekday}]
let weather = null;   // weather[placeIdx][dayIdx] = {code,tmax,tmin,pop,pm10,pm25}
let ranked = [];

const $ = (id) => document.getElementById(id);
const won = (n) => (n === 0 ? "무료" : n.toLocaleString("ko-KR") + "원");
function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k in n) n[k] = v;
    else n.setAttribute(k, v);
  }
  n.append(...kids.flat().filter((k) => k != null));
  return n;
}

// ── 저장 ──────────────────────────────────────────────
function save() {
  try {
    const { origin, family, budget, distance, priority, themes } = state;
    localStorage.setItem("weekend", JSON.stringify({ origin, family, budget, distance, priority, themes }));
  } catch {}
}
function load() {
  try {
    const s = JSON.parse(localStorage.getItem("weekend") || "null");
    if (s) Object.assign(state, s);
    if (!Array.isArray(state.themes)) state.themes = [];
  } catch {}
}

// ── 날씨 ──────────────────────────────────────────────
const WMO = (c) =>
  c === 0 ? ["☀️", "맑음"] : c <= 2 ? ["🌤️", "구름 조금"] : c === 3 ? ["☁️", "흐림"] :
  c <= 48 ? ["🌫️", "안개"] : c <= 57 ? ["🌦️", "이슬비"] : c <= 67 ? ["🌧️", "비"] :
  c <= 77 ? ["❄️", "눈"] : c <= 82 ? ["🌦️", "소나기"] : c <= 86 ? ["🌨️", "눈"] : ["⛈️", "뇌우"];

function dustLevel(w) {
  if (w.pm10 == null) return null;
  if (w.pm10 > 150 || w.pm25 > 75) return ["매우 나쁨", 3];
  if (w.pm10 > 80 || w.pm25 > 35) return ["나쁨", 2];
  if (w.pm10 > 30 || w.pm25 > 15) return ["보통", 1];
  return ["좋음", 0];
}

async function fetchWeatherChunk(points) {
  const lat = points.map((p) => p[0]).join(",");
  const lon = points.map((p) => p[1]).join(",");
  const base = `latitude=${lat}&longitude=${lon}&timezone=Asia%2FSeoul`;
  const [fc, aq] = await Promise.all([
    fetch(`https://api.open-meteo.com/v1/forecast?${base}&forecast_days=16&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max`).then((r) => r.json()),
    fetch(`https://air-quality-api.open-meteo.com/v1/air-quality?${base}&forecast_days=7&hourly=pm10,pm2_5`).then((r) => r.json()).catch(() => null),
  ]);
  const fcs = Array.isArray(fc) ? fc : [fc];
  const aqs = aq ? (Array.isArray(aq) ? aq : [aq]) : [];
  return { fcs, aqs };
}

async function fetchWeather(points) {
  // 주소 길이 제한 때문에 50곳씩 나눠서 요청
  const chunks = [];
  for (let i = 0; i < points.length; i += 50) chunks.push(points.slice(i, i + 50));
  const parts = await Promise.all(chunks.map(fetchWeatherChunk));
  const fcs = parts.flatMap((p) => p.fcs);
  const aqs = parts.flatMap((p) => (p.aqs.length ? p.aqs : p.fcs.map(() => null)));
  if (!fcs[0]?.daily) throw new Error("weather");
  days = fcs[0].daily.time.map((d) => ({ date: d, weekday: new Date(d + "T00:00").getDay() }));
  return fcs.map((f, i) => {
    // 낮 시간(9~18시) 미세먼지 평균
    const dust = {};
    const h = aqs[i]?.hourly;
    if (h) h.time.forEach((t, k) => {
      const hour = +t.slice(11, 13);
      if (hour < 9 || hour > 18 || h.pm10[k] == null) return;
      const d = (dust[t.slice(0, 10)] ||= { pm10: 0, pm25: 0, n: 0 });
      d.pm10 += h.pm10[k]; d.pm25 += h.pm2_5[k]; d.n++;
    });
    return f.daily.time.map((d, k) => ({
      code: f.daily.weather_code[k],
      tmax: f.daily.temperature_2m_max[k],
      tmin: f.daily.temperature_2m_min[k],
      pop: f.daily.precipitation_probability_max[k] ?? 0,
      pm10: dust[d] ? dust[d].pm10 / dust[d].n : null,
      pm25: dust[d] ? dust[d].pm25 / dust[d].n : null,
    }));
  });
}

// ── 리뷰·요청 (구글 시트 CSV) ─────────────────────────
let reviews = {};   // placeId -> [{date, stars, text, ages}] 최신순
let requests = [];

function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') q = false;
      else cell += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += ch;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim()));
}

// 헤더 글에 키워드가 들어 있는 열 번호를 찾는다 (폼 질문 제목이 조금 달라도 동작)
function columns(header, spec) {
  const out = {};
  for (const [key, words] of Object.entries(spec))
    out[key] = header.findIndex((h) => words.some((w) => h.replace(/\s/g, "").toLowerCase().includes(w.toLowerCase())));
  return out;
}

const parseDate = (s) => {
  const m = String(s).match(/(\d{4})[./-]\s*(\d{1,2})[./-]\s*(\d{1,2})/);
  return m ? `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}` : "";
};

async function fetchCsv(url) {
  if (!url) return null;
  try {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(res.status);
    return parseCsv(await res.text());
  } catch { return null; }
}

async function loadReviews(url = window.REVIEWS?.csvUrl) {
  const rows = await fetchCsv(url);
  reviews = {};
  if (!rows || rows.length < 2) return;
  const c = columns(rows[0], { date: ["타임", "시간", "날짜"], id: ["ID", "아이디"], stars: ["별점", "점수"],
    text: ["한줄", "평", "후기", "리뷰"], ages: ["나이", "연령"], nick: ["닉네임", "작성자"], photos: ["사진", "이미지", "첨부"] });
  if (c.id < 0 || c.text < 0) return;
  for (const r of rows.slice(1)) {
    const id = (r[c.id] || "").trim();
    if (!id || !(r[c.text] || "").trim()) continue;
    (reviews[id] ||= []).push({
      date: c.date >= 0 ? parseDate(r[c.date]) : "",
      stars: c.stars >= 0 ? Math.max(0, Math.min(5, parseInt(r[c.stars], 10) || 0)) : 0,
      text: r[c.text].trim(),
      ages: c.ages >= 0 ? (r[c.ages] || "").trim() : "",
      nick: c.nick >= 0 ? (r[c.nick] || "").trim() : "",
      photos: c.photos >= 0 ? driveIds(r[c.photos]) : [],
    });
  }
  for (const list of Object.values(reviews)) list.sort((a, b) => (b.date > a.date ? 1 : b.date < a.date ? -1 : 0));
}

async function loadRequests(url = window.REQUESTS?.csvUrl) {
  const rows = await fetchCsv(url);
  requests = [];
  if (!rows || rows.length < 2) return;
  const c = columns(rows[0], { date: ["타임", "시간", "날짜"], text: ["내용", "요청", "문의"], nick: ["닉네임", "이름"],
    status: ["상태"], reply: ["답변", "회신"] });
  if (c.text < 0) return;
  requests = rows.slice(1).filter((r) => (r[c.text] || "").trim()).map((r) => ({
    date: c.date >= 0 ? parseDate(r[c.date]) : "",
    text: r[c.text].trim(),
    nick: c.nick >= 0 ? (r[c.nick] || "").trim() : "",
    status: c.status >= 0 ? (r[c.status] || "").trim() || "접수" : "접수",
    reply: c.reply >= 0 ? (r[c.reply] || "").trim() : "",
  })).reverse();
}

function reviewFormUrl(p) {
  const { formUrl, entries } = window.REVIEWS || {};
  if (!formUrl) return null;
  const u = new URL(formUrl);
  if (entries?.id) u.searchParams.set(entries.id, p.id);
  if (entries?.name) u.searchParams.set(entries.name, p.name);
  return u.toString();
}

const stars = (n) => "★".repeat(n) + "☆".repeat(5 - n);

// 구글 폼 파일 업로드 셀("https://drive.google.com/open?id=..., ...")에서 파일 ID만 뽑는다.
function driveIds(cell) {
  return [...String(cell || "").matchAll(/(?:[?&]id=|\/d\/)([\w-]{20,})/g)].map((m) => m[1]).slice(0, 4);
}

function photoStrip(ids) {
  if (!ids.length) return null;
  return el("div", { class: "review-photos" }, ids.map((id) =>
    el("a", { href: `https://drive.google.com/file/d/${id}/view`, target: "_blank", rel: "noopener" },
      el("img", { src: `https://drive.google.com/thumbnail?id=${id}&sz=w320`, alt: "리뷰 사진", loading: "lazy",
        onerror: (e) => { e.target.closest("a").remove(); } }))));
}

function reviewBlock(p) {
  const list = reviews[p.id] || [];
  if (!list.length) return null;
  const r = list[0];
  const avg = (list.reduce((a, b) => a + b.stars, 0) / list.length).toFixed(1);
  return el("div", { class: "review" },
    el("div", { class: "review-head" },
      el("span", { class: "stars", "aria-label": `별점 ${r.stars}점` }, stars(r.stars)),
      el("span", { class: "muted" }, `우리 리뷰 ${list.length}개 · 평균 ${avg}`)),
    el("p", { class: "review-text" }, `"${r.text}"`),
    photoStrip(r.photos),
    el("p", { class: "review-meta" }, [r.nick || "익명", r.date, r.ages].filter(Boolean).join(" · ")),
    list.length > 1 ? el("details", { class: "more-reviews" },
      el("summary", {}, `리뷰 ${list.length - 1}개 더 보기`),
      el("ul", {}, list.slice(1, 6).map((x) => el("li", {},
        el("span", { class: "stars" }, stars(x.stars)), ` "${x.text}" `,
        el("span", { class: "muted" }, [x.nick || "익명", x.date].filter(Boolean).join(" · ")),
        photoStrip(x.photos))))) : null);
}

function renderRequests() {
  const { formUrl, csvUrl } = window.REQUESTS || {};
  $("requestForm").hidden = !formUrl;
  if (formUrl) $("requestForm").href = formUrl;
  const open = requests.filter((q) => q.status !== "완료" && q.status !== "보류").length;
  $("navCount").hidden = !open;
  $("navCount").textContent = open;
  const list = $("requestList");
  if (!formUrl && !csvUrl) {
    list.replaceChildren(el("li", { class: "empty" }, "게시판을 준비하고 있어요."));
    return;
  }
  if (!requests.length) {
    list.replaceChildren(el("li", { class: "empty" }, "아직 요청이 없어요. 첫 번째로 남겨 보세요!"));
    return;
  }
  const cls = { 접수: "st-new", 진행중: "st-doing", 완료: "st-done", 보류: "st-hold" };
  list.replaceChildren(...requests.slice(0, 30).map((q) =>
    el("li", { class: "request" },
      el("div", { class: "request-head" },
        el("span", { class: "status " + (cls[q.status] || "st-new") }, q.status),
        el("span", { class: "muted" }, [q.nick || "익명", q.date].filter(Boolean).join(" · "))),
      el("p", {}, q.text),
      q.reply ? el("p", { class: "reply" }, "↳ " + q.reply) : null)));
}

// ── 점수 계산 ─────────────────────────────────────────
function weatherScore(p, w, month) {
  if (!w) return { score: 50, notes: ["날씨 정보 없음"] };
  let s = 65;
  const notes = [];
  const add = (v, msg) => { s += v; if (msg) notes.push((v > 0 ? "👍 " : "👎 ") + msg); };
  const wet = w.pop >= 60 || (w.code >= 51 && w.code <= 67) || (w.code >= 80 && w.code <= 82) || w.code >= 95;
  const snowy = (w.code >= 71 && w.code <= 77) || w.code === 85 || w.code === 86;
  const hot = w.tmax >= 29, cold = w.tmax <= 5;
  const dust = dustLevel(w);
  const dusty = dust && dust[1] >= 2;
  const nice = !wet && !snowy && !hot && !cold && !dusty;
  const water = p.tags.includes("water"), snow = p.tags.includes("snow");

  if (p.setting === "indoor") {
    if (wet) add(25, `비 와도 실내라 괜찮아요`);
    if (dusty) add(25, `미세먼지 ${dust[0]}, 실내가 좋아요`);
    if (hot) add(15, "더위 피하기 좋은 실내");
    if (cold) add(15, "추위 피하기 좋은 실내");
    if (nice) add(-10, "날씨가 좋아 야외도 아까워요");
  } else {
    const k = p.setting === "mixed" ? 0.4 : 1;
    if (wet) add(-55 * k, `비 예보 (강수확률 ${w.pop}%)`);
    if (snowy && !snow) add(-30 * k, "눈 예보");
    if (dusty) add(-40 * k, `미세먼지 ${dust[0]}`);
    if (hot && !water) add(-25 * k, `한낮 ${Math.round(w.tmax)}°C, 더위 주의`);
    if (cold && !snow) add(-25 * k, `최고 ${Math.round(w.tmax)}°C, 추워요`);
    if (cold && snow) add(20, "눈썰매 타기 좋은 추위");
    if (nice) add(25 * (p.setting === "mixed" ? 0.6 : 1), "나들이하기 좋은 날씨");
  }
  if (water) {
    if (hot && !wet) add(30, "더운 날 물놀이 딱!");
    else if (w.tmax < 25) add(-45, "물놀이엔 쌀쌀해요");
  }
  if (p.bestMonths?.includes(month)) {
    const why = p.tags.includes("bloom") && month <= 6 ? "꽃 피는 계절" :
      p.tags.includes("foliage") && month >= 9 && month <= 11 ? "단풍 시즌" :
      p.tags.includes("snow") && (month === 12 || month <= 2) ? "눈썰매 시즌" : "지금이 가기 좋은 때";
    add(15, why);
  }
  return { score: Math.max(0, Math.min(100, Math.round(s))), notes };
}

function haversine(a, b) {
  const R = 6371, toR = Math.PI / 180;
  const dLat = (b[0] - a[0]) * toR, dLon = (b[1] - a[1]) * toR;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * toR) * Math.cos(b[0] * toR) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

function trip(p) {
  const road = haversine(originCoords(), [p.lat, p.lon]) * 1.35; // 도로는 직선보다 깁니다
  const minutes = Math.round(10 + (road / 38) * 60);
  return { km: Math.round(road), minutes };
}

// 샘플 데이터와 TourAPI 데이터의 형식 차이를 맞춘다.
function normalize(p) {
  return {
    setting: "outdoor", tags: [], ages: ["baby", "kid", "school"], emoji: "📍", tip: "",
    closedDays: [], closedDates: [], hours: "이용시간 정보 없음",
    ...p,
    price: p.price ? { adult: p.price.adult, child: p.price.child } : null,
    parking: p.parking ?? p.price?.parking ?? null,
  };
}

function cost(p, km) {
  const f = state.family;
  const ticket = p.price ? f.adult * p.price.adult + (f.kid + f.school) * p.price.child : null; // 영유아는 대부분 무료
  const fuel = Math.round((km * 2 * FUEL_PER_KM) / 1000) * 1000;
  return { ticket, parking: p.parking, fuel, total: (ticket ?? 0) + (p.parking ?? 0) + fuel, known: ticket != null };
}

const md = (iso) => `${+iso.slice(5, 7)}/${+iso.slice(8, 10)}`;

function openCheck(p, day) {
  const month = +day.date.slice(5, 7);
  if (p.period) {
    if (day.date < p.period.start || day.date > p.period.end)
      return { open: false, why: `축제 기간 아님 (${md(p.period.start)}~${md(p.period.end)})` };
    return { open: true, why: `🎉 축제 기간 ${md(p.period.start)}~${md(p.period.end)} · ${p.hours}` };
  }
  if (p.months && !p.months.includes(month)) return { open: false, why: `${p.months[0]}~${p.months.at(-1)}월에만 운영` };
  if (p.closedDates.includes(day.date.slice(5))) return { open: false, why: `${md(day.date)} 휴무일` };
  if (p.closedDays.includes(day.weekday)) return { open: false, why: `${p.closedDays.map((d) => WEEKDAY[d]).join("·")}요일 휴무` };
  return { open: true, why: `${WEEKDAY[day.weekday]}요일 영업 · ${p.hours}` };
}

function matchesTheme(p) {
  if (!state.themes.length) return true;
  return state.themes.some((i) => THEMES[i].slice(1).some((t) => (t === "festival" ? !!p.period : p.tags.includes(t))));
}

function suitsAges(p) {
  const f = state.family;
  const ages = ["baby", "kid", "school"].filter((a) => f[a] > 0);
  return !ages.length || ages.some((a) => p.ages.includes(a));
}

function evaluate() {
  const day = days[state.day];
  if (!day) return;
  const month = +day.date.slice(5, 7);
  const budget = BUDGETS[state.budget][1];
  const maxMin = DISTANCES[state.distance][1];
  const wts = PRIORITIES[state.priority][1];

  const all = places.filter(matchesTheme).map((p, i) => {
    const w = weather?.[p.cell]?.[state.day] ?? null;
    const t = trip(p);
    const c = cost(p, t.km);
    const o = openCheck(p, day);
    const ws = weatherScore(p, w, month);
    const costScore = !c.known ? 50 : budget === Infinity
      ? Math.round(100 - Math.min(c.total / 200000, 1) * 70)
      : budget === 0 ? 100 : Math.round(100 - Math.min(c.total / budget, 1) * 70);
    const distScore = Math.round(Math.max(0, 100 - Math.max(0, t.minutes - 20) * 0.8));
    const total = Math.round((ws.score * wts.weather + costScore * wts.cost + distScore * wts.dist) /
      (wts.weather + wts.cost + wts.dist));

    const out = [];
    if (!o.open) out.push(o.why);
    if (budget === 0 ? c.ticket !== 0 : c.total > budget)
      out.push(budget === 0 && !c.known ? "무료인지 확인 안 됨" : `예산 초과 (${won(c.total)})`);
    if (t.minutes > maxMin) out.push(`이동 약 ${t.minutes}분`);
    if (!suitsAges(p)) out.push("아이 나이와 안 맞아요");
    if (ws.score < 25) out.push("이날 날씨와 안 맞아요");
    return { p, w, trip: t, cost: c, open: o, ws, costScore, distScore, total, out };
  });

  ranked = all.filter((r) => !r.out.length).sort((a, b) => b.total - a.total);
  renderList(all.filter((r) => r.out.length));
  if (!$("compare").hidden) renderCompare();
}

// ── 화면 ──────────────────────────────────────────────
function originCoords() {
  return state.coords ?? ORIGINS[state.origin].slice(1);
}

function chips(id, options, current, onPick) {
  $(id).replaceChildren(...options.map(([label], i) =>
    el("button", { type: "button", "aria-pressed": String(i === current), onclick: () => onPick(i) }, label)));
}

function renderControls() {
  $("origin").replaceChildren(
    ...(state.coords ? [el("option", { value: "-1" }, "📍 내 위치")] : []),
    ...ORIGINS.map(([n], i) => el("option", { value: i }, n)));
  $("origin").value = state.coords ? "-1" : state.origin;

  $("family").replaceChildren(...FAMILY.map(([k, label]) =>
    el("div", { class: "stepper" },
      el("span", {}, label),
      el("button", { type: "button", "aria-label": `${label} 줄이기`, onclick: () => setFamily(k, -1) }, "−"),
      el("output", {}, state.family[k]),
      el("button", { type: "button", "aria-label": `${label} 늘리기`, onclick: () => setFamily(k, 1) }, "+"))));

  chips("budget", BUDGETS, state.budget, (i) => { state.budget = i; changed(); });
  chips("distance", DISTANCES, state.distance, (i) => { state.distance = i; changed(); });
  chips("priority", PRIORITIES, state.priority, (i) => { state.priority = i; changed(); });
  $("theme").replaceChildren(...THEMES.map(([label], i) =>
    el("button", { type: "button", "aria-pressed": String(state.themes.includes(i)), onclick: () => {
      state.themes = state.themes.includes(i) ? state.themes.filter((x) => x !== i) : [...state.themes, i];
      changed();
    } }, label)));
}

function setFamily(k, d) {
  state.family[k] = Math.max(k === "adult" ? 1 : 0, Math.min(8, state.family[k] + d));
  changed();
}

function changed() {
  save();
  renderControls();
  evaluate();
}

function pickDate(iso) {
  let i = days.findIndex((d) => d.date === iso);
  if (i < 0) {
    days.push({ date: iso, weekday: new Date(iso + "T00:00").getDay() });
    i = days.length - 1;
  }
  state.day = i;
  renderDays();
  evaluate();
}

function renderDays() {
  const base = weather?.[0];
  const shown = days.map((d, i) => [d, i]).filter(([, i]) => i < 7 || i === state.day);
  const picker = $("datePick");
  picker.min = days[0].date;
  picker.value = days[state.day].date;
  $("days").replaceChildren(...shown.map(([d, i]) => {
    const w = base?.[i];
    const [icon] = w ? WMO(w.code) : ["", ""];
    const weekend = d.weekday === 0 || d.weekday === 6;
    return el("button", {
      type: "button", role: "tab", class: "day" + (weekend ? " weekend" : ""),
      "aria-selected": String(i === state.day),
      onclick: () => { state.day = i; renderDays(); evaluate(); },
    },
      el("span", { class: "dow" }, i === 0 ? "오늘" : WEEKDAY[d.weekday]),
      el("span", { class: "date" }, `${+d.date.slice(5, 7)}/${+d.date.slice(8)}`),
      el("span", { class: "icon" }, w ? icon : "📅"),
      w ? el("span", { class: "temp" }, `${Math.round(w.tmax)}°`) : el("span", { class: "temp" }, "예보 전"));
  }));
  const w = base?.[state.day];
  if (!w) {
    $("daySummary").textContent = "이 날은 아직 날씨 예보가 없어요. 영업 여부와 비용·거리만으로 비교해요. (예보는 16일 앞까지)";
  } else {
    const [icon, label] = WMO(w.code);
    const dust = dustLevel(w);
    $("daySummary").textContent =
      `${icon} ${ORIGINS[state.origin] && !state.coords ? ORIGINS[state.origin][0] : "내 위치"} 기준 ${label}, ` +
      `${Math.round(w.tmin)}~${Math.round(w.tmax)}°C, 강수확률 ${w.pop}%` +
      (dust ? `, 미세먼지 ${dust[0]}` : ", 미세먼지 예보 전");
  }
}

function meter(label, score, text) {
  return el("div", { class: "meter" },
    el("span", { class: "m-label" }, label),
    el("span", { class: "bar", role: "img", "aria-label": `${score}점` },
      el("span", { style: `width:${score}%`, class: score >= 70 ? "good" : score >= 40 ? "ok" : "bad" })),
    el("span", { class: "m-text" }, text));
}

function weatherText(w) {
  if (!w) return "날씨 정보 없음";
  const [icon, label] = WMO(w.code);
  return `${icon} ${label} ${Math.round(w.tmax)}° · 비 ${w.pop}%`;
}

function card(r, rank) {
  const { p } = r;
  const inCompare = state.compare.includes(p.id);
  return el("li", { class: "card" + (rank === 1 ? " top" : "") + (p.image ? " has-photo" : ""), id: "card-" + p.id },
    p.image ? el("img", { class: "photo", src: p.image, alt: "", loading: "lazy",
      onerror: (e) => { e.target.remove(); } }) : null,
    el("div", { class: "body" },
    el("div", { class: "card-head" },
      el("span", { class: "rank" }, rank),
      el("span", { class: "emoji", "aria-hidden": "true" }, p.emoji),
      el("div", { class: "title" },
        el("h3", {}, p.period ? el("span", { class: "badge" }, "축제") : null, p.name),
        el("p", { class: "sub" }, `${p.area} · ${{ indoor: "실내", outdoor: "야외", mixed: "실내+야외" }[p.setting]}`
          + (p.reserve ? " · 예약 필요" : ""))),
      el("div", { class: "total", title: "종합 점수" }, el("strong", {}, r.total), el("small", {}, "점"))),
    el("div", { class: "meters" },
      meter("🌤 날씨", r.ws.score, weatherText(r.w)),
      meter("💰 비용", r.costScore, r.cost.known ? `약 ${won(r.cost.total)}` : "입장료 확인 필요"),
      meter("🚗 거리", r.distScore, `${r.trip.km}km · 약 ${r.trip.minutes}분`),
      el("div", { class: "meter open" }, el("span", { class: "m-label" }, "🕘 운영"),
        el("span", { class: "m-text" }, "✅ " + r.open.why + (p.restText ? ` (쉬는 날: ${p.restText})` : "")))),
    r.ws.notes.length ? el("ul", { class: "notes" }, r.ws.notes.map((n) => el("li", {}, n))) : null,
    el("details", { class: "breakdown" },
      el("summary", {}, "비용 자세히"),
      el("p", {}, `입장료 ${r.cost.known ? won(r.cost.ticket) : "정보 없음"} + 주차 ${r.cost.parking == null ? "정보 없음" : won(r.cost.parking)}`
        + ` + 기름값(왕복) ${won(r.cost.fuel)}`)),
    p.tip ? el("p", { class: "tip" }, "💡 " + p.tip) : null,
    reviewBlock(p),
    p.modified ? el("p", { class: "verified" }, `정보 수정일 ${p.modified} · 출발 전 운영 여부를 한 번 더 확인하세요`) : null,
    el("div", { class: "actions" },
      el("a", { href: "https://map.kakao.com/?q=" + encodeURIComponent(p.name), target: "_blank", rel: "noopener" }, "🗺 지도"),
      reviewFormUrl(p) ? el("a", { href: reviewFormUrl(p), target: "_blank", rel: "noopener" }, "✍️ 리뷰 남기기") : null,
      el("a", { href: "https://map.naver.com/p/search/" + encodeURIComponent(p.name), target: "_blank", rel: "noopener" },
        reviews[p.id] ? "💬 네이버 리뷰" : "💬 리뷰 보기"),
      p.homepage ? el("a", { href: p.homepage, target: "_blank", rel: "noopener" }, "🔗 누리집") : null,
      p.tel ? el("a", { href: "tel:" + p.tel.replace(/[^\d]/g, "") }, "☎ 전화") : null,
      el("button", {
        type: "button", class: inCompare ? "on" : "", "aria-pressed": String(inCompare),
        onclick: () => toggleCompare(p.id),
      }, inCompare ? "✓ 비교함에 담김" : "+ 비교 담기"))));
}

function renderList(excluded) {
  const day = days[state.day];
  $("count").textContent = `${WEEKDAY[day.weekday]}요일 추천 ${ranked.length}곳`
    + (state.themes.length ? ` · ${state.themes.map((i) => THEMES[i][0].replace(/^\S+\s/, "")).join(", ")}` : "");
  const shown = ranked.slice(0, state.limit);
  $("list").replaceChildren(...(ranked.length
    ? [...shown.map((r, i) => card(r, i + 1)),
       ranked.length > shown.length ? el("li", { class: "more" }, el("button", {
         type: "button", class: "ghost", onclick: () => { state.limit += 20; evaluate(); },
       }, `더 보기 (${ranked.length - shown.length}곳 남음)`)) : null].filter(Boolean)
    : [el("li", { class: "empty" }, "조건에 맞는 곳이 없어요. 예산이나 이동 시간을 늘려 보세요.")]));
  $("excludedBox").hidden = !excluded.length;
  $("excludedTitle").textContent = `이날은 빠진 곳 ${excluded.length}곳 보기`;
  $("excluded").replaceChildren(...excluded.map((r) =>
    el("li", {}, `${r.p.emoji} ${r.p.name} — ${r.out.join(", ")}`)));
  renderTray();
}

// ── 비교 ──────────────────────────────────────────────
function toggleCompare(id) {
  const i = state.compare.indexOf(id);
  if (i >= 0) state.compare.splice(i, 1);
  else {
    if (state.compare.length >= 3) state.compare.shift();
    state.compare.push(id);
  }
  evaluate();
}

function renderTray() {
  const n = state.compare.length;
  $("tray").hidden = n === 0;
  $("trayText").textContent = `비교함 ${n}/3`;
  $("openCompare").disabled = n < 2;
}

function renderCompare() {
  const rows = state.compare.map((id) => ranked.find((r) => r.p.id === id)).filter(Boolean);
  if (rows.length < 2) { $("compare").hidden = true; return; }
  const best = (f, hi = true) => {
    const vals = rows.map(f);
    const b = hi ? Math.max(...vals) : Math.min(...vals);
    return vals.map((v) => v === b);
  };
  const line = (label, cells, wins) =>
    el("tr", {}, el("th", { scope: "row" }, label),
      cells.map((c, i) => el("td", { class: wins?.[i] ? "win" : "" }, c)));
  $("compareTable").replaceChildren(
    el("thead", {}, el("tr", {}, el("th", {}, ""),
      rows.map((r) => el("th", { scope: "col" }, `${r.p.emoji} ${r.p.name}`)))),
    el("tbody", {},
      line("⭐ 종합 점수", rows.map((r) => `${r.total}점`), best((r) => r.total)),
      line("🌤 날씨", rows.map((r) => `${weatherText(r.w)} (${r.ws.score}점)`), best((r) => r.ws.score)),
      line("💨 미세먼지", rows.map((r) => (r.w && dustLevel(r.w) ? dustLevel(r.w)[0] : "예보 전"))),
      line("💰 예상 비용", rows.map((r) => (r.cost.known ? won(r.cost.total) : "확인 필요")), best((r) => (r.cost.known ? r.cost.total : Infinity), false)),
      line("🎟 입장료", rows.map((r) => (r.cost.known ? won(r.cost.ticket) : "정보 없음")), best((r) => r.cost.ticket ?? Infinity, false)),
      line("🚗 이동", rows.map((r) => `${r.trip.km}km · 약 ${r.trip.minutes}분`), best((r) => r.trip.minutes, false)),
      line("🕘 운영", rows.map((r) => r.open.why)),
      line("🗓 쉬는 날", rows.map((r) => r.p.restText || (r.p.closedDays.length ? r.p.closedDays.map((d) => WEEKDAY[d]).join("·") + "요일" : "정보 없음"))),
      line("🏠 실내/야외", rows.map((r) => ({ indoor: "실내", outdoor: "야외", mixed: "실내+야외" }[r.p.setting]))),
      line("💡 팁", rows.map((r) => r.p.tip || "-")),
      Object.keys(reviews).length ? line("⭐ 우리 리뷰", rows.map((r) => {
        const l = reviews[r.p.id];
        return l ? `${stars(Math.round(l.reduce((a, b) => a + b.stars, 0) / l.length))} (${l.length}개)` : "아직 없음";
      }), best((r) => (reviews[r.p.id] ? reviews[r.p.id].reduce((a, b) => a + b.stars, 0) / reviews[r.p.id].length : -1))) : null));
  $("compare").hidden = false;
}

// ── 화면(메뉴) 전환 ───────────────────────────────────
const VIEWS = ["home", "requests", "about"];

function setView(view) {
  if (!VIEWS.includes(view)) view = "home";
  document.body.dataset.view = view;
  document.querySelectorAll(".side-nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  document.title = { home: "주말 어디 가지?", requests: "문의·요청 게시판 · 주말 어디 가지?", about: "이 사이트는 · 주말 어디 가지?" }[view];
  closeMenu();
  window.scrollTo({ top: 0 });
}

function viewFromHash() {
  const h = location.hash.replace(/^#\/?/, "");
  return h === "requests" ? "requests" : h === "about" ? "about" : "home";
}

function openMenu() {
  $("sidebar").classList.add("open");
  $("backdrop").hidden = false;
  $("menuBtn").setAttribute("aria-expanded", "true");
}
function closeMenu() {
  $("sidebar").classList.remove("open");
  $("backdrop").hidden = true;
  $("menuBtn").setAttribute("aria-expanded", "false");
}

// ── 시작 ──────────────────────────────────────────────
function pickRandom() {
  const pool = ranked.slice(0, 5);
  if (!pool.length) return;
  const r = pool[Math.floor(Math.random() * pool.length)];
  const node = $("card-" + r.p.id);
  document.querySelectorAll(".card.picked").forEach((n) => n.classList.remove("picked"));
  node.classList.add("picked");
  node.scrollIntoView({ behavior: "smooth", block: "center" });
}

function defaultDay() {
  const i = days.findIndex((d) => d.weekday === 6 || d.weekday === 0);
  return i < 0 ? 0 : i;
}

async function loadWeather() {
  $("count").textContent = "날씨 불러오는 중…";
  try {
    // 가까운 장소끼리(약 10km 격자) 날씨를 한 번만 받아 호출 수를 줄인다. 0번은 출발지.
    const cells = new Map();
    for (const p of places) {
      const key = `${Math.round(p.lat * 10) / 10},${Math.round(p.lon * 10) / 10}`;
      if (!cells.has(key)) cells.set(key, cells.size + 1);
      p.cell = cells.get(key);
    }
    const points = [...cells.keys()].map((k) => k.split(",").map(Number));
    weather = await fetchWeather([originCoords(), ...points]);
  } catch {
    weather = null;
    const today = new Date();
    days = Array.from({ length: 16 }, (_, i) => {
      const d = new Date(today); d.setDate(d.getDate() + i);
      return { date: d.toLocaleDateString("sv-SE"), weekday: d.getDay() };
    });
    $("daySummary").textContent = "날씨를 불러오지 못해서 날씨 점수 없이 비교해요.";
  }
}

async function init() {
  load();
  state.compare = [];
  renderControls();

  $("menuBtn").addEventListener("click", () => ($("sidebar").classList.contains("open") ? closeMenu() : openMenu()));
  $("backdrop").addEventListener("click", closeMenu);
  window.addEventListener("hashchange", () => setView(viewFromHash()));
  setView(viewFromHash());

  $("origin").addEventListener("change", async (e) => {
    const v = +e.target.value;
    if (v >= 0) { state.origin = v; state.coords = null; }
    changed();
    await loadWeather(); renderDays(); evaluate();
  });
  $("locate").addEventListener("click", () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(async (pos) => {
      state.coords = [pos.coords.latitude, pos.coords.longitude];
      renderControls();
      await loadWeather(); renderDays(); evaluate();
    }, () => alert("위치를 가져오지 못했어요. 출발지를 직접 골라 주세요."));
  });
  $("openCompare").addEventListener("click", () => {
    renderCompare();
    $("compare").scrollIntoView({ behavior: "smooth" });
  });
  $("closeCompare").addEventListener("click", () => { $("compare").hidden = true; });
  $("clearCompare").addEventListener("click", () => { state.compare = []; $("compare").hidden = true; evaluate(); });
  $("pick").addEventListener("click", pickRandom);
  $("datePick").addEventListener("change", (e) => { if (e.target.value) pickDate(e.target.value); });

  try {
    const data = await (await fetch("data/places.json", { cache: "no-cache" })).json();
    places = data.items.map(normalize);
    $("dataNote").innerHTML = data.isSample
      ? "⚠️ 장소 정보(가격·운영시간)는 <strong>연습용 샘플</strong>이에요. 방문 전 꼭 공식 누리집에서 확인하세요."
      : `장소 정보: ${data.source} (${data.updatedAt} 갱신). 임시 휴관은 늦게 반영될 수 있으니 출발 전 확인하세요.`;
  } catch {
    $("count").textContent = "장소 데이터를 불러오지 못했어요.";
    return;
  }
  await Promise.all([loadWeather(), loadReviews(), loadRequests()]);
  renderRequests();
  state.day = defaultDay();
  renderDays();
  evaluate();
}

init();
