import sys

lines = sys.stdin.read().splitlines()
values = []
for line in lines:
    if line.strip() == '':
        continue
    v = int(line.strip())
    if v == 0:
        values.append(0)
        break
    values.append(v)

out = values[::-1]
print('\n'.join(map(str, out)))
