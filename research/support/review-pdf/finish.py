from pathlib import Path
from collections import Counter
from statistics import median
import json,hashlib
p=Path('research/adaptive-intelligence/runs/stepback-live-01')
def load(f):return json.loads(f.read_text())
def num(n,d=1):return f'{n:.{d}f}'.replace('.',',')
def pct(n):return num(100*n/72)
def h(code):return hashlib.sha256(code.encode()).hexdigest()
lock=load(p/'lock.json'); summary=load(p/'summary.json'); totals=summary['totals']
tasks={r['id']:r for r in load(p/'tasks.json')}; scores=load(p/'scores.json')
rows=[load(p/'jobs'/f'{k}-{s}-{m}.json') for k,s,m in lock['schedule']]
idx=lambda r:(r['task'],r['seed'],r['mode'])
ix={idx(r):r for r in rows}; sc={idx(r):r for r in scores}
assert len(ix)==len(sc)==summary['n']==288 and set(ix)==set(sc)
group={m:[r for r in rows if r['mode']==m] for m in 'ABCD'}
def passed(r):
 c=r['selected']['code']
 return bool(c) and any(v['passed']==len(tasks[r['task']]['public']) and v['code_sha']==h(c) for v in r['public_checks'])
pub={m:sum(map(passed,group[m])) for m in group}
children={m:[(r,b) for r in group[m] for b in r['branches'] if b['parent'] is not None] for m in 'CD'}
def exact(m,n):return sum(ix[k,s,m]['selected']['code']==ix[k,s,n]['selected']['code'] for k,s,z in ix if z==m)
def gap(label):
 v=summary['pairs'][label];return f'{num(v["pp"])} п.п. (95% ДИ от {num(v["ci"][0])} до {num(v["ci"][1])}), выигрышей {v["wins"]}, проигрышей {v["losses"]}'
print(json.dumps(dict(summary={k:v for k,v in summary.items() if k!='pairs'},pairs={k:{i:j for i,j in v.items() if i!='by_task'} for k,v in summary['pairs'].items()},pub=pub,equal=[exact('C','B'),exact('D','C')],children={m:[len(bs),sum(bool(b['code']) for r,b in bs),sum(b['name']==r['selected']['branch'] for r,b in bs)] for m,bs in children.items()}),ensure_ascii=False,indent=1))
f=[]
f.append('# Итог пилота ветвления Strata с дедлайном 30 секунд')
f.append('25 ноября 2026 · Inkling-2-Mini SQ-10 · один Apple M4 Max 48 GiB · 24 задачи AtCoder из девяти соревнований · три seed на задачу. Завершены все 288 назначений замороженного протокола. Каждый режим оценён на тех же 72 сочетаниях задачи и seed.')
f.append('## Что получил пользователь')
f.append('| Режим | Прошли все скрытые тесты | Прошли публичные примеры | Хотя бы один готовый правильный кандидат | Медиана выдачи | 95-й процентиль |\n|---|---:|---:|---:|---:|---:|\n'+'\n'.join(f'| {m} · '+{'A':'один старт','B':'независимые старты','C':'ветвление','D':'ветвление с отсечением'}[m]+f' | {v["correct"]}/72 ({pct(v["correct"])}%) | {pub[m]}/72 | {v["oracle"]}/72 | {num(v["p50_ms"]/1000,2)} с | {num(v["p95_ms"]/1000,2)} с |' for m,v in totals.items()))
f.append('Оценивали выбранную вовремя программу по всем сохранённым скрытым тестам задачи. Отсутствие ответа считается ошибкой. Столбец «хотя бы один» описывает достижимую точность при идеальном выборе из уже завершённых кандидатов на момент выдачи. Публичные примеры видит селектор, скрытые ответы открыты после окончания генерации.')
f.append('## Парные сравнения')
f.append('\n'.join('- **'+label.replace('-',' минус ')+'** — '+gap(label)+'.' for label in ['D-A','C-B','D-C','D-B']))
f.append('Каждая разность считается на одинаковых задачах и seed. Описательный 95% интервал получен в 20 000 перевыборках целых задач с тремя seed. При совпавших результатах на всей выборке интервал вырождается в ноль. Он не устанавливает эквивалентность на других задачах. Главный критерий для перехода к подтверждению — минимум +5 п.п. D относительно A при нижней границе интервала выше нуля. Выбор A был зафиксирован по отдельной калибровке.')
f.append('## Где дерево успело повлиять')
f.append(f'Между B и C текст выбранной программы либо отсутствие выдачи совпали в {exact("C","B")}/72 случаях. Между C и D — в {exact("D","C")}/72. Эти сравнения включают совпавшие пустые ответы.')
for m,bs in children.items():
 f.append(f'- **{m}.** Запущено дочерних веток — {len(bs)}, дали извлекаемую программу — {sum(bool(b["code"]) for r,b in bs)}, получили атрибуцию выдачи — {sum(b["name"]==r["selected"]["branch"] for r,b in bs)}. Запросов с наблюдавшимся расхождением при одновременной генерации родителя и ребёнка — {totals[m]["divergent"]}/72. Возможностей для отсечения — {totals[m]["opportunities"]}, фактических отмен этим правилом — {totals[m]["pruned"]}.')
f.append('Атрибуция выбирает первую ветку с выданным текстом при совпадениях. Родители занимают оба слота в начале запроса, ребёнок получает слот после его освобождения. Ранний публичный успех завершает поиск. При таком порядке отсечение может быть полезным только при одновременно активных родителе и ребёнке, совпадающем общем суффиксе и ожидающей работе.')
f.append('## Стоимость, ограничения и материалы')
f.append(f'Максимум суммы выделенной Metal-памяти и снимков — {num(max(v["peak_alloc"] for v in totals.values())/2**30,2)} GiB при лимите 20 GiB. Зарегистрированный пик отдельного счётчика физической памяти процесса движка — {num(max(v["peak_footprint"] for v in totals.values())/2**30,2)} GiB. Число нарушений дедлайна публикации — {sum(v["missed"] for v in totals.values())} из 288. Отсутствие программы к сроку и опоздание самой публикации — разные исходы.')
f.append('Результат относится к прогретой модели, тестам stdin/stdout, двум слотам, ветвлению перед маркером ответа и досрочной выдаче при публичном успехе. Малый набор отобран из доступных диапазонов LiveCodeBench, каждые три seed разделяют одну задачу. Другие бюджеты ожидания, политика ранней выдачи, локализация смысловой ошибки, Qwen в роли автора, энергия и физические чтения SSD в этот пилот не входили.')
f.append('[Замороженный протокол](protocol.json) · [Порядок запусков и хеши](lock.json) · [Сводка с разбивкой по задачам](summary.json) · [Все оценки](scores.json) · [Журналы генерации](jobs/) · [Резервный протокол подтверждения](confirmation.md) · [Воспроизведение](../../branching/stepback.md)')
(p/'report.md').write_text('\n\n'.join(f)+'\n')
