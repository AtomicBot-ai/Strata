"""Operator-selected partial E03; distinguish five-block screens and single pairs."""
from e03_observations import main as collect
from runner import LAB
from screen import load


def number(value, digits=3):
    return f"{value:.{digits}f}".replace(".",",")


def main():
    run=LAB/"runs/E03/after-E02-R"
    short=load(run/"short-long-tree.json")
    collect(run)
    rows=load(run/"observations.json")["cells"]
    long=[r for r in rows if r["p"]==16384 and r["complete_pairs"]]
    assert sorted((r["n"],r["complete_pairs"]) for r in long)==[(2,1),(8,1)]
    best=max((r for r in rows if r["status"]=="complete" and r["n"]>1 and r["shared"]),
             key=lambda r:r["median_paired_speedup"])
    lines=["# E03. Сравнение скорости после E02-R","",
           "Полная серия E03 на паузе. Для общего префикса 16 384 и восьми веток выполнена одна дополнительная пара. "
           "E02-R до начала этих измерений прошёл независимую проверку. Все значения ниже относятся к Inkling SQ-10 на одном M4 Max, "
           "при двух выделенных слотах и 128 заданных шагах на ветку. Обе системы обрабатывали те же ID. Во всех включённых парах совпали и конечные выбранные токены.","",
           "## Одно длинное дерево","",
           "Одинаковый лимит двух рабочих слотов позволяет штатному движку обрабатывать ветки по очереди, если это быстрее. "
           "Перед сравнением на отдельном дереве измерены оба штатных расписания. Для восьми веток они заняли "+
           number(short["dev_elapsed_ns"]["1"]/1e9,2)+" с при ширине один и "+number(short["dev_elapsed_ns"]["2"]/1e9,2)+
           " с при ширине два. В качестве основного контроля выбрана ширина "+str(short["baseline_width"])+".",""]
    for r in long:
        lines.append(f"- {r['n']} веток — штатный режим {number(r['B3']['median_s'],2)} с, снимок {number(r['B4']['median_s'],2)} с, "
                     f"ускорение {number(r['median_paired_speedup'],2)}×. Пиковый физический размер процесса "
                     f"{number(r['B3']['peak_footprint_gib'],2)} и {number(r['B4']['peak_footprint_gib'],2)} ГиБ соответственно.")
    lines+=["","Для каждого из двух длинных случаев есть одна измерительная пара. По ним нельзя оценить устойчивость ускорения или доверительный интервал.",
            "","## Случаи с пятью парами","",
            "| Общих токенов | Веток | Штатный режим, с | Снимок, с | Медианное парное ускорение |",
            "|---:|---:|---:|---:|---:|"]
    for r in rows:
        if r["status"]!="complete":
            continue
        prefix=str(r["p"]) if r["shared"] else f"0 (разные входы по {r['p']})"
        lines.append(f"| {prefix} | {r['n']} | {number(r['B3']['median_s'],2)} | {number(r['B4']['median_s'],2)} | {number(r['median_paired_speedup'],3)}× |")
    lines+=["",f"Максимум из полностью измеренных случаев с ветвлением — {number(best['median_paired_speedup'],3)}× "
            f"при общем префиксе {best['p']} и {best['n']} ветках. Для перехода к независимому подтверждению протокол требует 1,30× в скрининге. "
            "Для оставшихся размеров результат открыт. Формального решения G1 по всей матрице нет.","",
            "Физический размер процесса взят из Darwin proc_pid_rusage. Веса отображены в память, аллокации Metal учитываются отдельно. Жёсткого лимита памяти в этом опыте не задавали. "
            "Данные не дают оценки числа агентов, помещающихся в память.","",
            "[Машиночитаемые показатели и состояние всех клеток](../runs/E03/after-E02-R/observations.json) · "
            "[Исходные измерения](../runs/E03/after-E02-R/screen/) · [Выбранное сокращение](../runs/E03/after-E02-R/scope-change.json) · "
            "[Независимый E02-R](E02-R.md)",""]
    (LAB/"reports/E03-short.md").write_text("\n".join(lines))


if __name__=="__main__":
    main()
