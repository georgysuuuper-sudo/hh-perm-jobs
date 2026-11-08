# -*- coding: utf-8 -*-
"""
Парсер вакансий hh.ru (Пермь, от 50 000 руб/мес, за 7 дней).
Качает страницы поиска, вытаскивает HH-Lux-InitialState, фильтрует мусор,
маркирует шорт-лист/ловушки и пишет:
  data/vacancies.json  — отфильтрованный список
  data/meta.json       — last_parse / next_parse / счётчики
  data/seen_ids.json   — все когда-либо виденные id (для метки «новая»)
Запуск: python parser/parse.py  (из корня репо)
"""
import json
import html
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 05:00 UTC == 08:00 мск (расписание GitHub Actions cron)
PARSE_HOUR_UTC = 5

MAX_PAGES = 20
SEARCH_URL = ("https://perm.hh.ru/search/vacancy?area=72&only_with_salary=true"
              "&salary=50000&period=7&page={page}")
MIN_SALARY = 50000


def load_page(url):
    for attempt in range(3):
        r = subprocess.run(
            ["curl", "-s", "--compressed", "--max-time", "40", url,
             "-H", f"User-Agent: {UA}", "-H", "Accept: text/html"],
            capture_output=True,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode("utf-8", errors="replace")
        time.sleep(3)
    return None


def extract_state(h):
    i = h.find("HH-Lux-InitialState")
    if i < 0:
        return None
    start = h.find(">", i) + 1
    end = h.find("</template>", start)
    try:
        return json.loads(html.unescape(h[start:end].strip()))
    except json.JSONDecodeError:
        return None


def compact(v):
    comp = v.get("compensation") or {}
    emp = v.get("company") or {}
    rev = emp.get("employerReviews") or {}
    we = v.get("workExperience") or {}
    pub = v.get("publicationTime") or {}
    addr = v.get("address") or {}
    labels = []
    for lab in v.get("labels") or []:
        if isinstance(lab, dict):
            labels.append(lab.get("name") or lab.get("id") or str(lab))
        else:
            labels.append(str(lab))
    return {
        "id": v.get("vacancyId"),
        "name": v.get("name"),
        "from": comp.get("from"),
        "to": comp.get("to"),
        "per_from": comp.get("perModeFrom"),
        "per_to": comp.get("perModeTo"),
        "currency": comp.get("currencyCode"),
        "gross": comp.get("gross"),
        "employer": emp.get("visibleName") or emp.get("name"),
        "site": emp.get("companySiteUrl"),
        "rating": rev.get("totalRating"),
        "reviews": rev.get("reviewsCount"),
        "exp": we.get("id") if isinstance(we, dict) else we,
        "employment": v.get("employment"),
        "labels": labels,
        "responses": v.get("responsesCount"),
        "pub": (pub.get("$") or "")[:10],
        "district": (addr.get("districtDto") or {}).get("name"),
        "url": f"https://perm.hh.ru/vacancy/{v.get('vacancyId')}",
        "is_adv": v.get("@isAdv"),
    }


def fetch_all():
    all_vacs = {}
    for page in range(MAX_PAGES):
        h = load_page(SEARCH_URL.format(page=page))
        if h is None:
            print(f"page {page}: download failed, stopping")
            break
        st = extract_state(h)
        if st is None:
            print(f"page {page}: no state (blocked?), stopping")
            break
        vacs = (st.get("vacancySearchResult") or {}).get("vacancies") or []
        new = 0
        for v in vacs:
            c = compact(v)
            if c["id"] and c["id"] not in all_vacs:
                all_vacs[c["id"]] = c
                new += 1
        print(f"page {page}: {len(vacs)} items, {new} new (total {len(all_vacs)})")
        if not vacs or new == 0:
            break
        time.sleep(0.7)
    return list(all_vacs.values())


# ---------- фильтры и метки (портировано из build_excel.py) ----------

JUNK = [
    (r"такси|яндекс\s*go|ситимобил|домклик", "такси-агрегатор"),
    (r"курьер|доставк[аи]\s+(заказов|продуктов|еды)|яндекс еда|самокат|delivery", "агрегатор доставки"),
    (r"сетев|mlm|oriflame|фаберлик|эвалар|тианде|nl international", "сетевой маркетинг"),
    (r"стаж[её]р.*риелт|риелтор|агент по недвижимости|помощник риелтора", "риелтор без оклада"),
    (r"страховой агент|страхование.*агент", "страховой агент без оклада"),
    (r"финансовый советник|финансовый консультант", "«финансовый консультант» без оклада"),
    (r"анкет|опросник", "оплата за анкеты"),
    (r"вахт", "вахта"),
    (r"модель|хостес|артист|аниматор", "сомнительное"),
    (r"самозанят", "только самозанятость"),
    (r"webcam|вебкам|чата?", "скам"),
    (r"инвест|трейдинг|крипт|forex", "скам-финансы"),
    (r"заработок|доход от", "скам-формулировка"),
    # бьюти-сфера и прочие неинтересные отрасли
    (r"маникюр|ногтев|педикюр|бровист|лашмейкер|ресниц|косметолог|косметич",
     "бьюти-сфера"),
    (r"парикмах|барбер|барберин|визаж|эпиляц|шугаринг", "бьюти-сфера"),
    (r"повар|пиццамейк|пекарь|кондитер|кухон|бариста|бармен|официант", "общепит"),
    (r"продавец|кассир|мерчендайз|товаровед|кладовщик|комплектовщик|грузчик",
     "розница / склад"),
    (r"водител|таксист|экспедитор|курьер", "водители / доставка"),
    (r"сборщик|разнорабоч|фасовщ|упаковщ|оператор линии|стажёр.*(производств|цех)",
     "производство / разнорабочие"),
    (r"звонцентр|call-?центр|оператор.*звонков|менеджер по (продажам|работе с клиент)",
     "продажи / обзвон"),
    (r"уборщ|горничн|дворник|посудомойщ", "уборка / клининг"),
    (r"охранник|контролер.*зала|смотрящ", "охрана"),
    (r"воспитател|нян|сиделк|аниматор детск", "соцсфера"),
]

# id: (rank, короткий вердикт)
STARS = {
    "139183032": (1, "Обучение сборке/ремонту ПК с нуля, малая контора, вход в IT через железо"),
    "138861878": (2, "Лучший инженерный вход без опыта: обучение с наставником, договор с 1-го дня"),
    "138493136": (3, "Реальный завод, официальное оформление, высокая ЗП для новичка"),
    "139073620": (4, "Обучение с нуля, чевые легально, рост до старшего официанта через 6 мес."),
    "138477354": (5, "Опыт не обязателен, обучают, официальный ТК"),
    "139211130": (6, "Малая компания, обучают, честные «от 50 000», 5/2"),
    "138202914": (7, "2 месяца оплачиваемого обучения — реальная дверь в IT-компанию"),
    "139059143": (8, "Продажа техники, которую понимаешь; малый магазин"),
    "138850298": (9, "Высокая ставка за 11–12 смен, стажировка оплачивается (но это KPI-продажи)"),
    "135476641": (10, "Своя академия барберинга, обучение с нуля, наработка базы клиентов"),
    "139186431": (11, "Лидер производства, официальное оформление, стабильный оклад 2р/мес"),
}

TRAPS = {
    "138783759": "Оклада нет — только % с продаж туров",
    "139182912": "Конвейерный обзвон водителей по всей России",
    "139051570": "В поиске числился «Пермью», в описании — Владикавказ",
    "139226287": "Требуется переезд в Елабугу (Татарстан)",
    "139169058": "В фильтре «без опыта», в описании — опыт от 3 лет",
    "138686676": "Рейтинг работодателя 2.0 из 5",
    "139227628": "Вилка 80–250 тыс. у продавца сладостей без опыта",
    "139161161": "Вилка 50–500 тыс. — маркер серой схемы мотивации",
}


def junk_label(v):
    txt = " ".join(filter(None, [v.get("name"), v.get("employer")])).lower()
    for pat, lab in JUNK:
        if re.search(pat, txt):
            return lab
    return None


def main():
    raw = fetch_all()
    if not raw:
        print("NO DATA FETCHED, keeping old files")
        sys.exit(1)

    seen_path = DATA / "seen_ids.json"
    seen = set(json.loads(seen_path.read_text("utf-8"))) if seen_path.exists() else set()

    clean = [v for v in raw
             if v.get("currency") in ("RUR", None)
             and (v.get("per_to") or v.get("per_from") or 0) >= MIN_SALARY
             # пользователь ищет только вакансии без опыта
             and (v.get("exp") == "noExperience")]

    out = []
    new_count = 0
    for v in clean:
        vid = str(v["id"])
        # ловушки и автофильтр-мусор вообще не выгружаем (звёздные — исключение)
        if vid in TRAPS or (vid not in STARS and junk_label(v)):
            continue
        is_new = vid not in seen
        if is_new:
            new_count += 1
        mark, verdict = "", ""
        if vid in STARS:
            rank, verdict = STARS[vid]
            mark = "star"
        out.append({
            "id": vid,
            "name": v["name"],
            "employer": v["employer"],
            "per_from": v.get("per_from"),
            "per_to": v.get("per_to"),
            "gross": v.get("gross"),
            "rating": v.get("rating"),
            "reviews": v.get("reviews"),
            "exp": v.get("exp"),
            "responses": v.get("responses"),
            "district": v.get("district"),
            "pub": v.get("pub"),
            "url": v["url"],
            "mark": mark,
            "verdict": verdict,
            "is_new": is_new,
        })

    # сортировка: шорт-лист по рангу, затем по убыванию ЗП
    star_rank = {k: r for k, (r, _) in STARS.items()}
    out.sort(key=lambda v: (
        0 if v["id"] in star_rank else 1,
        star_rank.get(v["id"], 99),
        -(v.get("per_from") or 0),
    ))

    now = datetime.now(timezone.utc)
    next_parse = now.replace(hour=PARSE_HOUR_UTC, minute=0, second=0, microsecond=0)
    if now >= next_parse:
        next_parse += timedelta(days=1)

    (DATA / "vacancies.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    seen.update(v["id"] for v in out)
    seen_path.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=1), "utf-8")
    (DATA / "meta.json").write_text(json.dumps({
        "last_parse": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "next_parse": next_parse.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(out),
        "new_count": new_count,
        "stars": sum(1 for v in out if v["mark"] == "star"),
        "hidden": len(clean) - len(out),
    }, ensure_ascii=False, indent=1), "utf-8")

    print(f"TOTAL: {len(out)} (new: {new_count}, stars: {sum(1 for v in out if v['mark']=='star')}, "
          f"filtered out: {len(clean) - len(out)})")


if __name__ == "__main__":
    main()
