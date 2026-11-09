// Вакансии Перми: рендер таблицы + таймер до следующего парса (08:00 МСК = 05:00 UTC)
"use strict";

const EXP = {
  noExperience: "без опыта",
  between1And3: "1–3 года",
  between3And6: "3–6 лет",
  moreThan6: "6+ лет",
};
const PARSE_HOUR_UTC = 5; // 08:00 МСК

let VACANCIES = [];
let META = null;

const $ = (id) => document.getElementById(id);
const fmtMoney = (x) => (x == null ? null : String(x).replace(/\B(?=(\d{3})+(?!\d))/g, " "));

function salaryText(v) {
  const f = v.per_from, t = v.per_to;
  if (f && t) return `${fmtMoney(f)} – ${fmtMoney(t)}`;
  if (f) return `от ${fmtMoney(f)}`;
  if (t) return `до ${fmtMoney(t)}`;
  return "—";
}

function nextParseDate(from = new Date()) {
  const t = new Date(from);
  t.setUTCHours(PARSE_HOUR_UTC, 0, 0, 0);
  if (from >= t) t.setUTCDate(t.getUTCDate() + 1);
  return t;
}

function startTimer() {
  const el = $("timer");
  let target = META?.next_parse ? new Date(META.next_parse) : nextParseDate();
  if (isNaN(target) || target < new Date()) target = nextParseDate();

  const tick = () => {
    const now = new Date();
    if (now >= target) {
      el.textContent = "парсится…";
      // после парса подтянуть свежие данные (JSON может закэшироваться — рвём кэш)
      setTimeout(() => load(true), 60_000);
      target = nextParseDate(now);
      return;
    }
    let s = Math.floor((target - now) / 1000);
    const h = String(Math.floor(s / 3600)).padStart(2, "0");
    const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
    const sec = String(s % 60).padStart(2, "0");
    el.textContent = `${h}:${m}:${sec}`;
  };
  tick();
  setInterval(tick, 1000);
}

function renderStats() {
  const total = META?.total ?? VACANCIES.length;
  const fresh = META?.new_count ?? VACANCIES.filter((v) => v.is_new).length;
  const stars = META?.stars ?? VACANCIES.filter((v) => v.mark === "star").length;
  const last = META?.last_parse
    ? new Date(META.last_parse).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" })
    : "—";
  $("stats").innerHTML = `
    <div class="stat"><b>${total}</b><span>всего</span></div>
    <div class="stat"><b style="color:var(--new)">${fresh}</b><span>новых</span></div>
    <div class="stat"><b style="color:var(--star)">${stars}</b><span>в шорт-листе</span></div>
    <div class="stat"><span class="when">обновлено ${last} МСК</span></div>`;
}

function render() {
  const q = $("search").value.trim().toLowerCase();
  const onlyNew = $("only-new").checked;

  const rows = VACANCIES.filter((v) => {
    if (onlyNew && !v.is_new) return false;
    if (q && !(v.name + " " + v.employer).toLowerCase().includes(q)) return false;
    return true;
  });

  const tbody = $("tbody");
  tbody.innerHTML = rows.map((v) => {
    const badges =
      (v.is_new ? '<span class="badge new">NEW</span>' : "") +
      (v.size === "small" ? '<span class="badge small">+ малая компания</span>' : "") +
      (v.mark === "star" ? '<span class="badge star">⭐ шорт-лист</span>' : "");
    const rating = v.rating
      ? `★ ${Number(v.rating).toFixed(1)}` + (v.reviews ? ` <span class="employer-site">(${v.reviews})</span>` : "")
      : "—";
    const verdict = v.verdict ? `<span class="verdict">${v.verdict}</span>` : "";
    return `<tr>
      <td class="name-cell"><a class="vac" href="${v.url}" target="_blank" rel="noopener">${v.name}</a>${badges}${verdict}</td>
      <td>${v.employer ?? "—"}</td>
      <td class="num">${salaryText(v)}${v.gross ? "" : " <span class=\"employer-site\">на руки</span>"}</td>
      <td class="exp">${EXP[v.exp] ?? "—"}</td>
      <td class="num">${rating}</td>
      <td class="num">${v.responses ?? "—"}</td>
      <td>${v.district ?? "—"}</td>
      <td class="num">${v.pub ? v.pub.slice(8, 10) + "." + v.pub.slice(5, 7) : "—"}</td>
    </tr>`;
  }).join("");

  $("empty").hidden = rows.length > 0;
}

async function load(silent) {
  const bust = "?t=" + Date.now();
  try {
    const [dv, dm] = await Promise.all([
      fetch("data/vacancies.json" + bust).then((r) => r.json()),
      fetch("data/meta.json" + bust).then((r) => r.json()),
    ]);
    VACANCIES = dv;
    META = dm;
    renderStats();
    render();
  } catch (e) {
    if (!silent) console.error(e);
  }
}

$("search").addEventListener("input", render);
$("only-new").addEventListener("change", render);

load().then(startTimer);
