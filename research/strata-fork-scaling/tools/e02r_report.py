"""Summarize measured E02-R contrasts without pooling branches as independent trees."""
import json
import statistics
from pathlib import Path

from e02r import CAL, CORE, DEPTHS, HOLD, KEYS, OUT, SHORT, read

REPORT = OUT.parents[1] / "reports"
NAMES = {
    "native-mixed": "Одиночный prefill, парный decode относительно штатного совместного запроса",
    "native-serial": "Одиночный prefill и decode относительно штатного совместного запроса",
    "one-factor-chunk64": "Размер порции prefill 64 вместо 128",
    "one-factor-swapped": "Смена физического слота для каждой ветки",
    "one-factor-reverse": "Обратная подача запросов в те же слоты",
    "one-factor-joint": "Парное вычисление общего префикса до сохранения",
    "batch-effect-native": "Парный / одиночный decode при повторном вычислении",
    "batch-effect-fork": "Парный / одиночный decode при восстановлении"
}


def summary(rows):
    avg=lambda k: statistics.fmean(r[k] for r in rows)
    return dict(observations=len(rows),trees=len({r["seed"] for r in rows}),
                max_abs=max(r["max_abs"] for r in rows), mean_rmse=avg("rmse"), max_rmse=max(r["rmse"] for r in rows),
                mean_js=avg("js"),max_js=max(r["js"] for r in rows), mean_overlap=avg("top10_overlap"),
                greedy_hits=sum(r["greedy_agreement"] for r in rows), byte_matches=sum(r["exact"] for r in rows))


def collect(stage,seeds,tags):
    data={}
    for tag in tags:
        rows=[r for seed in seeds for r in read(OUT/stage/str(seed)/(tag+".json"))]
        data[tag]={"all":summary(rows),"by_depth":{str(d):summary([r for r in rows if r["depth"]==d])
                               for d in DEPTHS if any(r["depth"]==d for r in rows)}}
    return data


def fmt(v):
    return f"{v:.5g}".replace(".",",")


def main():
    gate=read(OUT/"gate.json")
    controls=["native-"+a for a in CORE[1:]+SHORT]+["one-factor-"+a for a in SHORT]
    f_arms=["mixed","serial","swapped","reverse","chunk64"]
    hold=collect("hold",HOLD,controls+["matched-"+a for a in f_arms]+["cross-"+a for a in f_arms]+
                 ["batch-effect-native","batch-effect-fork"])
    cal=collect("cal",CAL,controls)
    panel=read(OUT/"hold-panel.json")
    matching=[hold["matched-"+arm]["all"] for arm in f_arms]
    total=sum(r["observations"] for r in matching)
    exact=sum(r["byte_matches"] for r in matching)
    interaction={k:max(r["interaction"][k] for r in panel) for k in KEYS}
    result=dict(calibration=cal, independent=hold,matched_rows=total,matched_exact=exact,
                max_abs_interaction=interaction,gate=gate)
    (REPORT/"E02-R-metrics.json").write_text(json.dumps(result,indent=2)+"\n")
    verdict={
        "passed":"Новый критерий пройден. Разрешён E03 на исходных условиях.",
        "exact_mismatch":"Нарушено точное совпадение при одинаковых путях. Требуется локализация.",
        "native_out_of_envelope":"Независимый штатный контроль вышел за контрольный диапазон. Конкурентная эквивалентность по новому правилу остаётся неопределённой.",
        "candidate_out_of_envelope":"Численный критерий для восстановленного состояния не пройден."
    }[gate["status"]]
    lines=["# E02-R. Перенос состояния и пакетные вычисления","", "**"+verdict+"**","",
           f"В проверке с тем же вычислительным путём побайтно совпали {exact} из {total} векторов. "
           "Каждый содержит 200 058 оценок возможного следующего токена. Два продолжения дерева получали одинаковые заданные ID во всех сравниваемых режимах.","",
           "## Устройство опыта","",
           "Восемь новых деревьев сформировали контрольный диапазон только на штатных операциях Strata. "
           "На четырёх других деревьях запускались и пересчёт, и снимок. Проверялись границы 1 023, 1 024, 1 025 и 2 049. "
           "Длинные режимы включали 1 024 последовательных шага и восемь срезов. Короткие контроли включали 32 шага и четыре среза.","",
           "В основном факторном опыте в обоих режимах префикс обрабатывался одиночно. "
           "Две ветки затем либо исполнялись по очереди, либо шли одним пакетом. "
           "Один и тот же бинарник с наблюдателем сохранял полные FP32-логиты. В штатном режиме операции сохранения и восстановления не вызывались. "
           "Наблюдатель проверял фактическую форму пакета, использование сохранённого префикса и все токены продолжения.","",
           "## Что менялось на независимых деревьях","",
           "В порядке перечисления метрик ниже приведены максимальная абсолютная ошибка, средние по срезам RMSE и JS-дивергенция, средняя доля общих токенов среди первых десяти и число совпавших жадных выборов. JS измерена в натуральных логарифмах.",""]
    for key,name in NAMES.items():
        r=hold[key]["all"]
        lines.append(f"- {name} — {fmt(r['max_abs'])}, {fmt(r['mean_rmse'])}, {fmt(r['mean_js'])}, "
                     f"{fmt(100*r['mean_overlap'])}% и {r['greedy_hits']}/{r['observations']}.")
    lines+=["","Максимальная по всем проверенным срезам разность эффектов пакетного decode со снимком и без него "
            "составила "+", ".join(f"{name} {fmt(interaction[k])}" for k,name in zip(KEYS,("max abs","RMSE","JS","top-10 loss","greedy loss")))+".","",
            "## Динамика на длинных продолжениях","",
            "[График ошибок по восьми веткам](E02-R-depth.png)","",
            "Для пары «обычное совместное исполнение / одиночный prefill с парным decode и снимком» "
            "ниже приведены максимальная ошибка и средние RMSE, JS, top-10 overlap, затем совпадения greedy. На каждой глубине восемь веток четырёх деревьев.",""]
    for d in DEPTHS:
        r=hold["cross-mixed"]["by_depth"][str(d)]
        lines.append(f"- После {d} токенов — {fmt(r['max_abs'])}, {fmt(r['mean_rmse'])}, {fmt(r['mean_js'])}, "
                     f"{fmt(100*r['mean_overlap'])}% и {r['greedy_hits']}/8.")
    lines+=["","## Основание решения","",
            "На контрольной выборке для каждой метрики и глубины фиксировалась наибольшая наблюдаемая ошибка дерева "
            "(среднее двух веток, затем максимум по штатным расписаниям). На независимой панели отдельно оценивались "
            "штатные контрасты и контрасты со снимком. Точное совпадение одинаковых путей требовалось для каждой ветки и каждого среза. "
            "Исходный результат E02 сохранён. Вывод ограничен этим движком, двумя слотами, выбранными фиксированными траекториями и наблюдавшимися глубинами.",""]
    for fail in gate["failures"]:
        lines.append(f"- {fail['group']}, глубина {fail['depth']}, {fail['metric']} — {fmt(fail['value'])}, граница {fmt(fail['limit'])}.")
    lines+=["","[Правила до калибровки](../E02-R.md) · [Зафиксированные границы и хеши](../runs/E02-R/freeze.json) · "
            "[Старт независимой проверки](../runs/E02-R/holdout-start.json) · [Вердикт](../runs/E02-R/gate.json) · "
            "[Все агрегаты по глубинам и факторам](E02-R-metrics.json) · [Наблюдения по деревьям](../runs/E02-R/)",""]
    (REPORT/"E02-R.md").write_text("\n".join(lines))


if __name__=="__main__":
    main()
