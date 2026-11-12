"""Сборка библиотеки задач из архивов SGF (Ultimate Go Problems и wbaduk).

Запуск: python tools/build_library.py <папка с архивами> [...]
Результат: gogame/problems/library.json.gz — задачи разложены по уровню сложности (этапы
«Библиотека: …») и по темам (уровни), у каждой темы есть объяснение «что изучаем и зачем».
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gogame.problems import sgf_import  # noqa: E402
from gogame.problems.sgf_import import file_to_problems  # noqa: E402

TRANSLATIONS_DIR = ROOT / "tools" / "translations"

BANDS = ["Библиотека: 25–16 кю", "Библиотека: 15–10 кю", "Библиотека: 9–4 кю", "Библиотека: 3 кю – 2 дан",
         "Библиотека: 3–5 дан и сильнее", "Библиотека: тематические сборники"]
CHUNK = 100

# тема -> (название, что изучаем, зачем это в партии)
TOPICS = {
    "capture": ("Захват камней",
                "Как поймать камни соперника: атари с нужной стороны, лестница, сеть, двойная угроза.",
                "Почти каждый бой заканчивается захватом или его угрозой. Умение увидеть захват на шаг раньше "
                "соперника — основа силы в тактике."),
    "life": ("Жизнь и смерть",
             "Как сделать два глаза своей группе или не дать их сделать соперника: жизненно важные пункты, "
             "сокращение пространства, ложные глаза.",
             "Судьба больших групп решает партию. Кто лучше читает жизнь и смерть, тот смело атакует и не "
             "боится вторжений."),
    "living": ("Ходы для жизни",
               "Как жить группе, оказавшейся в окружении: расширение пространства и ключевые пункты глаз.",
               "Вторгаясь на территорию соперника, нужно уметь быстро сделать живую группу."),
    "sabaki": ("Сабаки: лёгкая жизнь",
               "Сабаки — гибкая игра слабой группой: жертвы, лёгкие ходы, выход в центр.",
               "Когда ваша группа в меньшинстве, важно не цепляться за каждый камень, а сохранить главное."),
    "tesuji": ("Тесудзи (мэк)",
               "Тесудзи — сильный местный ход, который решает бой: бросок, вклин, укол, жертва.",
               "Тесудзи превращают проигранную позицию в выигранную. Чем больше приёмов вы знаете, тем быстрее "
               "находите их в своих партиях."),
    "semeai": ("Гонка за дамэ (семеай)",
               "Бой двух окружённых групп: счёт дамэ, внешние и общие дамэ, глаз против отсутствия глаза.",
               "Семеай встречаются в каждой второй партии. Правильный счёт дамэ говорит, атаковать или защищаться."),
    "endgame": ("Ёсэ",
                "Розыгрыш границ в конце партии: цена хода, сэнтэ и готэ, тесудзи на первой линии.",
                "Партии часто решаются несколькими очками в ёсэ. Сильный игрок знает, какой ход крупнее."),
    "endgame_tesuji": ("Тесудзи в ёсэ",
                       "Приёмы конца игры, которые приносят лишние очки: прыжок обезьяны, броски, угрозы.",
                       "Одно тесудзи в ёсэ стоит столько же, сколько выигранный бой."),
    "opening": ("Дебют",
                "Распределение доски в начале партии: углы, края, расширения, направление игры.",
                "Хороший дебют даёт удобную партию на много ходов вперёд."),
    "haengma": ("Хэнма: ход камней",
                "Как камни должны двигаться: прыжки, косуми, хане, лёгкая и тяжёлая форма.",
                "Хорошая форма позволяет играть быстро и без ошибок: камни работают вместе и не дают себя "
                "разрезать."),
    "attack": ("Атака и защита",
               "Как атаковать слабые группы и защищать свои: давление издалека, отрезание базы, укрепление.",
               "Атака — главный способ получить очки в середине игры, а своевременная защита — не отдать их."),
    "handicap": ("Игра с форой",
                 "Типичные позиции партий с форой: как использовать камни форы и отвечать на хитрые ходы.",
                 "С форой учатся почти все любители: знание типовых ходов помогает реализовать преимущество."),
    "invading": ("Вторжение",
                 "Как вторгаться в территорию соперника и как наказывать вторжения.",
                 "Большие зоны соперника нужно разрушать вовремя, иначе он выиграет на территории."),
    "shape": ("Базовые формы",
              "Типовые формы и ответы на них, которые нужно знать наизусть.",
              "Знание форм экономит время на чтение и помогает избегать плохих ходов."),
    "joseki": ("Дзёсэки",
               "Стандартные розыгрыши в углу и их смысл: кто что получает и какое продолжение лучше.",
               "Дзёсэки учат не заучиванию, а балансу: территория в обмен на влияние."),
    "middle": ("Середина игры",
               "Как вести борьбу в середине партии и надёжно довести преимущество до победы.",
               "Середина игры — самая длинная часть партии, здесь решается, кто будет вести."),
    "next": ("Найдите лучший ход",
             "Позиции из партий: оцените доску и выберите самый важный ход.",
             "В партии никто не скажет, где задача. Этот навык — видеть главное на всей доске."),
    "misc": ("Разное", "Задачи разных типов.", "Разнообразная тренировка развивает чтение и интуицию."),
    "tricks": ("Ловушки",
               "Хитрые ходы (хамэтэ) и правильные ответы на них.",
               "Знание ловушек защищает от неприятных сюрпризов и учит читать до конца."),
    "first": ("Первые шаги",
              "Самые основы: дамэ, захват, глаза, простые формы.",
              "Без этих навыков невозможно играть осмысленно: они нужны в каждой партии."),
    "basic": ("Интенсивный курс основ",
              "Короткие уроки по основным приёмам с выбором правильного ответа.",
              "Курс закрепляет базовые идеи, на которых строится вся игра."),
    "classic": ("Классические задачи",
                "Старинные задачи мастеров прошлого: длинное и точное чтение.",
                "Классические задачи развивают умение считать варианты до конца."),
}

# Названия приёмов в китайских и японских сборниках: (название, что это такое)
TECHNIQUES = {
    "做活": ("Сделать жизнь", "Найдите ход, который даёт группе два глаза."),
    "对杀": ("Гонка за дамэ", "Посчитайте дамэ обеих групп и выиграйте гонку."),
    "要点": ("Жизненно важный пункт", "Найдите пункт, который решает судьбу группы."),
    "双活": ("Сэки", "Сэки — взаимная жизнь двух групп без глаз: никто не может атаковать первым."),
    "眼杀": ("Глаз против отсутствия глаза", "В гонке группа с глазом обычно побеждает группу без глаз."),
    "打劫": ("Ко", "Решение через ко: бой, где камни снимают по очереди с угрозами между взятиями."),
    "破眼": ("Разрушение глаз", "Не дайте группе соперника сделать второй глаз."),
    "棋理": ("Принципы игры", "Задачи на понимание общих принципов: где важнее ходить и почему."),
    "趣题": ("Занимательные задачи", "Необычные позиции, где решение спрятано."),
    "常型": ("Типовые формы", "Формы, которые встречаются в партиях постоянно."),
    "断": ("Разрез", "Ход, разделяющий камни соперника на две слабые части."),
    "扑": ("Бросок", "Жертва камня внутри формы соперника, чтобы отнять дамэ или глаз."),
    "扳": ("Хане", "Загиб вокруг камня соперника, чтобы ограничить его."),
    "尖": ("Косуми", "Диагональный ход: прочная связь и тихое давление."),
    "金鸡独立": ("«Золотой петух на одной ноге»",
                 "Спуск к краю, после которого соперник не может подойти ни с одной стороны."),
    "点": ("Укол (оки)", "Камень в жизненно важный пункт формы соперника."),
    "挖": ("Вклин (варикоми)", "Ход между двумя камнями соперника, создающий две точки разреза."),
    "立": ("Спуск (сагари)", "Ход к краю доски, увеличивающий дамэ или пространство для глаз."),
    "跳": ("Прыжок", "Быстрый ход через пункт, чтобы выйти или перекрыть путь."),
    "夹": ("Зажим (хасами)", "Ход, зажимающий камень соперника с двух сторон."),
    "渡": ("Переход (ватари)", "Соединение своих групп под камнями соперника по первой линии."),
    "征": ("Лестница", "Погоня атари за атари, гонящая камни к краю."),
    "枷": ("Сеть (гэта)", "Ход на шаг впереди, после которого камню некуда бежать."),
    "秤砣": ("«Гиря»", "Жертва нескольких камней, чтобы зажать соперника в плохую форму."),
    "倒脱靴": ("«Снять сапог» (игра под камнями)",
               "После того как соперник снимает ваши камни, вы ходите на освободившееся место и ловите его."),
    "扑吃": ("Бросок и захват", "Бросок, после которого камни соперника попадают в атари."),
    "接不归": ("«Не вернуться домой» (оиотоси)", "Камни в атари, которые не могут соединиться со своими."),
    "接不歸": ("«Не вернуться домой» (оиотоси)", "Камни в атари, которые не могут соединиться со своими."),
    "破眼": ("Разрушение глаз", "Не дайте группе соперника сделать второй глаз."),
    "渡手法": ("Переход (ватари)", "Соединение своих групп под камнями соперника по первой линии."),
    "棄子": ("Жертва камней", "Отдать камни, чтобы выиграть больше в другом месте."),
    "擠": ("Втискивание", "Ход вплотную, отнимающий у соперника дамэ или глаз."),
    "征子": ("Лестница", "Погоня атари за атари, гонящая камни к краю."),
    "左右同型": ("Симметричные формы", "В симметричной позиции важно, с какой стороны начать."),
    "tuke": ("Цукэ (прижим)", "Ход вплотную к камню соперника."),
    "oki": ("Оки (укол внутрь)", "Камень внутрь формы соперника в жизненно важный пункт."),
    "warikomi": ("Варикоми (вклин)", "Ход между двумя камнями соперника."),
    "kiri": ("Кири (разрез)", "Разрез камней соперника."),
    "hane_osae": ("Хане и осаэ (загиб и блок)", "Загиб вокруг камней соперника и блокировка."),
    "hasamituke": ("Хасами-цукэ (зажим-прижим)", "Прижим между двумя камнями соперника."),
    "kosumi": ("Косуми (диагональ)", "Диагональный ход."),
    "geta": ("Гэта (сеть)", "Сеть: ход на шаг впереди убегающих камней."),
    "watari": ("Ватари (переход)", "Соединение по первой линии."),
    "suteishi": ("Сутэиси (жертва)", "Жертва камней ради выгоды."),
    "tukekosi": ("Цукэкоси (прижим-перескок)", "Прижим, перепрыгивающий через камень соперника."),
    "mekaku": ("Отнять глаз", "Ход, лишающий группу соперника глаза."),
    "sagari": ("Сагари (спуск)", "Спуск к краю доски."),
    "atekomi": ("Атэкоми (вклин с атари)", "Ход внутрь формы с угрозой атари."),
    "sonota": ("Разное", "Другие приёмы."),
    "hane": ("Хане (загиб)", "Загиб вокруг камня соперника."),
    "hiki": ("Хики (отступление)", "Ход назад, к своим камням."),
    "nobi": ("Нобу (вытягивание)", "Вытягивание камней по прямой."),
    "osae": ("Осаэ (блок)", "Блокировка камней соперника."),
    "tobi": ("Тоби (прыжок)", "Прыжок через пункт."),
    "kake": ("Какэ (шапка)", "Ход, накрывающий камень соперника сверху."),
    "nozoki": ("Нодзоки (укол)", "Угроза разреза."),
    "horikomi": ("Хорикоми (бросок)", "Бросок камня внутрь, чтобы отнять дамэ."),
    "tsuke": ("Цукэ (прижим)", "Ход вплотную к камню соперника."),
    "damedumari": ("Нехватка дамэ (дамэдзумари)", "Камни соперника не могут защититься, потому что им не хватает дамэ."),
    "doukei": ("Симметричные формы", "В симметричной позиции важно, с какой стороны начать."),
    "hanaduke": ("Хана-дзукэ (прижим в лоб)", "Прижим к голове камня соперника."),
    "kosumituke": ("Косуми-цукэ", "Диагональный прижим к камню соперника."),
    "oiotosi": ("Оиотоси («не вернуться домой»)", "Камни в атари, которые не могут соединиться со своими."),
    "ositubusi": ("Осицубуси (сдавливание)", "Соперник вынужден заполнить собственные дамэ или глаз."),
    "sibori": ("Сибори (выжимание)", "Жертва камней, после которой соперник получает плохую тяжёлую форму."),
    "sicho": ("Лестница (сичо)", "Погоня атари за атари, гонящая камни к краю."),
    "tobituke": ("Тоби-цукэ", "Прыжок с прижимом к камню соперника."),
}


def classify(rel: str) -> tuple[int, str, str]:
    """(номер этапа, тема, подпись сборника) по пути файла внутри архива."""
    parts = rel.split(os.sep)
    low = rel.lower()
    top = parts[0]
    # ------------------------------------------------ wbaduk
    ranks = {"16-25K": 0, "13K~15K": 1, "10K~12K": 1, "7K~9K": 2, "4K~6K": 2, "1K~3K": 3, "1D~2D": 3, "3D~5D": 4}
    if top in ranks:
        sub = parts[1].lower()
        topic = ("endgame_tesuji" if "maek of endgame" in sub else
                 "endgame" if "endgame" in sub else
                 "semeai" if "capturing race" in sub else
                 "tesuji" if "maek" in sub else
                 "capture" if "capturing" in sub else
                 "living" if "living" in sub else
                 "life" if "life" in sub or "challenges" in sub else
                 "opening" if "opening" in sub else
                 "attack" if "attack" in sub else
                 "handicap" if "handicap" in sub else
                 "shape" if "pattern" in sub else
                 "tricks" if "trick" in sub else
                 "next" if "next move" in sub or "best move" in sub else
                 "haengma" if "haengma" in sub or "responses" in sub else "misc")
        return ranks[top], topic, f"wbaduk {top}"
    named = {
        "First step in Baduk": (0, "first"), "Intensive Basic": (1, "basic"), "Haengma": (5, "haengma"),
        "The way of Haengma": (5, "haengma"), "Fast-paced Hangma": (5, "haengma"),
        "Sensible next move": (5, "haengma"), "Dictionary Series": (5, "tesuji"),
        "Two Opposite Choices": (5, "capture"), "Opening Study": (5, "opening"),
        "Secure victory in the middle game": (5, "middle"), "Master Series": (5, "next"),
        "The Latest Jungsuk(Joseki)": (5, "joseki"),
    }
    if top in named:
        band, topic = named[top]
        return band, topic, f"wbaduk: {top}"
    if top == "Maek(Tesuji)":
        band = {"beginner": 1, "intermediate 1": 2, "intermediate 2": 2}.get(parts[1].lower(), 3)
        return band, "tesuji", "wbaduk: Maek (Tesuji)"
    if top == "Life&Death":
        band = 3 if "1D" in parts[1] else 4
        return band, "classic" if "Classic" in parts[1] else "life", "wbaduk: Life & Death"
    # ------------------------------------------------ Ultimate Go Problems
    if top.startswith("Ultimate"):
        name = parts[1]
        u = name.upper()
        lvl = 0 if "ELEMENTARY" in u else 1 if "INTERMEDIATE" in u else 2 if "ADVANCED" in u else 3 if " PRO" in u else None
        topic = ("attack" if "ATTACK" in u else "capture" if "CAPTURING" in u else "attack" if "DEFENSE" in u else
                 "endgame" if "END GAME" in u else "sabaki" if "SABAKI" in u else "semeai" if "SEMEAI" in u else None)
        if topic and lvl is not None:
            return lvl, topic, "Ultimate Go Problems"
        fixed = {
            "TSUMEGO - THE BASIC": (0, "life", "Ultimate Go Problems: Tsumego Basic"),
            "TSUMEGO CHO CHIKUN - ADVANCED": (3, "life", "Тё Тикун, «Энциклопедия жизни и смерти» (продвинутый том)"),
            "TSUMEGO CLASSIC- XUANXUAN QIJING": (4, "classic", "«Сюаньсюань Цицзин» (классический китайский сборник, 1349)"),
            "SAKATA EIO TESUJI": (4, "tesuji", "Саката Эйо, «Тесудзи»"),
            "GET STRONG AT ATTACKING": (2, "attack", "Ричард Боздоу, «Get Strong at Attacking»"),
            "GET STRONG AT HANDICAP GO": (2, "handicap", "Ричард Боздоу, «Get Strong at Handicap Go»"),
            "GET STRONG AT INVADING": (2, "invading", "Ричард Боздоу, «Get Strong at Invading»"),
            "GET STRONG AT THE OPENING": (2, "opening", "Ричард Боздоу, «Get Strong at the Opening»"),
            "MAKING SHAPE STRATEGY": (2, "shape", "Ultimate Go Problems: Making Shape"),
        }
        if name in fixed:
            return fixed[name]
        if name == "+BONUS":
            col = parts[2]
            if col.startswith("AMERICAN"):
                return 5, "misc", "Американская ассоциация го (AGA)"
            if col.startswith("CHINESE"):
                return 5, "tech", "Китайский сборник (1034 задачи)"
            if col.startswith("KOREAN"):
                return 5, "misc", "Корейская школа бадук (1000 задач)"
            if col.startswith("GO SEIGEN"):
                return 4, "tech", "Го Сэйгэн, «Словарь тесудзи»"
            if col.startswith("TESUJI DICTIONARY"):
                return 5, "tech", "«Словарь тесудзи» (248 задач)"
    return 5, "misc", top


def technique(fname: str) -> str:
    n = re.sub(r"#U([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), fname)
    n = re.sub(r"^\d+_", "", Path(n).stem)
    n = re.sub(r"__Vs_?$", "", n)
    n = re.sub(r"^下冊之.[：:\-]*", "", n)
    n = re.sub(r"[\d\-_ ]+$", "", n)
    return n


def init_worker():
    sgf_import.load_translations(TRANSLATIONS_DIR)


def work(item):
    path, rel = item
    sgf_import.COLLECT = set()
    try:
        probs = file_to_problems(Path(path), 0)
    except Exception:
        probs = []
    return rel, probs, sgf_import.COLLECT if probs else set()


def main(dirs):
    collect_to = None
    if "--collect" in dirs:
        i = dirs.index("--collect")
        collect_to = Path(dirs[i + 1])
        dirs = dirs[:i] + dirs[i + 2:]
    items = []
    for d in dirs:
        d = Path(d)
        for dp, _, fs in os.walk(d):
            for f in fs:
                if f.lower().endswith(".sgf"):
                    full = Path(dp) / f
                    items.append((str(full), str(full.relative_to(d))))
    # внутри архива задачи идут по номерам в именах файлов
    def natkey(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s[1])]
    items.sort(key=natkey)
    with Pool(os.cpu_count() or 2, initializer=init_worker) as pool:
        results = pool.map(work, items, chunksize=40)
    untranslated = sorted(set().union(*(r[2] for r in results)) - set(sgf_import.TRANSLATIONS)
                          if not sgf_import.TRANSLATIONS else
                          set().union(*(r[2] for r in results)))
    sgf_import.load_translations(TRANSLATIONS_DIR)
    untranslated = sorted(t for t in untranslated if t not in sgf_import.TRANSLATIONS)
    print(f"текстов без перевода: {len(untranslated)} ({sum(map(len, untranslated)):,} символов)")
    if collect_to:
        collect_to.write_text(json.dumps(untranslated, ensure_ascii=False, indent=0), encoding="utf-8")
    results = [(rel, probs) for rel, probs, _ in results]

    groups: dict[tuple, list] = {}
    meta: dict[tuple, tuple] = {}
    skipped = 0
    unknown: dict[str, int] = {}
    for rel, probs in results:
        if not probs:
            skipped += 1
            continue
        band, topic, source = classify(rel)
        if topic == "tech":
            tech = technique(Path(rel).name)
            title, concept = TECHNIQUES.get(tech, ("Разное", "Задачи на разные приёмы."))
            if tech not in TECHNIQUES:
                unknown[tech] = unknown.get(tech, 0) + 1
            key = (band, source, title)
            meta[key] = (title, concept, TOPICS["tesuji"][2], source)
        else:
            title, concept, why = TOPICS[topic]
            key = (band, source, title)
            meta[key] = (title, concept, why, source)
        for p in probs:
            p["_rel"] = rel
        groups.setdefault(key, []).extend(probs)

    levels, problems = [], []
    level_no = 2000
    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2])):
        band, source, _ = key
        title, concept, why, src = meta[key]
        probs = groups[key]
        chunks = [probs[i:i + CHUNK] for i in range(0, len(probs), CHUNK)]
        for ci, chunk in enumerate(chunks):
            rng = f" ({ci * CHUNK + 1}–{ci * CHUNK + len(chunk)})" if len(chunks) > 1 else ""
            m = re.search(r"«([^»]+)»", src)
            short = m.group(1) if m else src
            levels.append({"level": level_no, "title": f"{title}{rng} · {short}", "stage": BANDS[band],
                           "lesson": f"{concept} {why} Задачи из сборника: {src}. Комментарии к ходам взяты из "
                                     f"сборника и переведены на русский; «Разбор с ИИ» объяснит любой ход.",
                           "books": src})
            for n, p in enumerate(chunk, 1):
                rel = p.pop("_rel")
                h = hashlib.md5(f"{rel}#{p['id']}".encode()).hexdigest()[:10]
                p["id"] = f"lib-{h}"
                p["level"] = level_no
                p["title"] = f"Задача {ci * CHUNK + n}"
                p["concept"] = concept
                p["why"] = why
                p["source"] = src
                p.pop("marked", None)
                problems.append(p)
            level_no += 1
    out = ROOT / "gogame" / "problems" / "library.json.gz"
    data = json.dumps({"levels": levels, "problems": problems}, ensure_ascii=False, separators=(",", ":"))
    with gzip.open(out, "wt", encoding="utf-8", compresslevel=9) as f:
        f.write(data)
    print(f"файлов: {len(items)}, задач: {len(problems)}, уровней: {len(levels)}, без решения: {skipped}")
    if unknown:
        print("неизвестные приёмы:", unknown)
    print(f"записано {out} ({out.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main(sys.argv[1:])
