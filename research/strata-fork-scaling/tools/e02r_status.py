"""Compact report of all external replication panels. Preserve each prospective verdict."""
from pathlib import Path
import json

from runner import LAB

ROOT=LAB/"runs/E02-R/extension"

def read(path):
    return json.loads(path.read_text())

def main():
    rows=[]
    vectors=exact=0
    for folder in sorted(ROOT.glob("cohort-*")):
        seeds=read(folder/"manifest.json")["seeds"]
        finished=[]
        for seed in seeds:
            if (folder/f"tree-{seed}.json").is_file():
                finished.append(seed)
                for item in (ROOT/"hold"/str(seed)).glob("matched-*.json"):
                    items=read(item)
                    vectors+=len(items)
                    exact+=sum(r["exact"] for r in items)
        decision=folder/"gate.json"
        rows.append(dict(cohort=folder.name,finished=finished,planned=seeds,
                         status=read(decision)["status"] if decision.exists() else "in_progress",
                         failures=read(decision).get("failures",[]) if decision.exists() else []))
    data=dict(cohorts=rows,matched_vectors=vectors,exact=exact,trees=sum(len(x["finished"]) for x in rows))
    (ROOT/"summary.json").write_text(json.dumps(data,indent=2)+"\n")
    lines=["# E02-R. Дополнительные независимые группы","",
           f"В учтённых законченных деревьях побайтно совпали {exact} из {vectors} пар векторов. "
           f"Всего деревьев {data['trees']}. Первоначальная независимая выборка сюда не входит.","",
           "У каждой группы есть собственный результат по правилам, зафиксированным до её запуска. "
           "Повторная проверка по многим группам даёт больше возможностей увидеть редкое отклонение. "
           "Выход самой штатной Strata за калибровочный диапазон фиксируется отдельно от ошибки переноса.",""]
    for row in rows:
        tags={"passed":"пройдена","native_out_of_envelope":"штатное исполнение вышло за диапазон",
              "candidate_out_of_envelope":"контраст со снимком вышел за диапазон",
              "exact_mismatch":"нарушено побайтное совпадение","in_progress":"в процессе"}
        lines.append(f"- {row['cohort']} — {len(row['finished'])}/4 деревьев, {tags[row['status']]}.")
        for fail in row["failures"]:
            lines.append(f"  - {fail['group']}, после {fail['depth']} шагов, {fail['metric']}: "
                         f"{fail['value']:.7g} при зафиксированной границе {fail['limit']:.7g}.")
    lines+=["","[Исходная калибровка](../runs/E02-R/freeze.json) · [Все дополнительные наблюдения](../runs/E02-R/extension/)",""]
    (LAB/"reports/E02-R-extension.md").write_text("\n".join(lines))
    print(data["trees"],exact,vectors,rows[-1]["status"])

if __name__=="__main__":
    main()
