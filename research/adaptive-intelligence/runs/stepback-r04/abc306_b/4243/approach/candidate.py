import sys

s = sys.stdin.read().split()
a = [int(x) for x in s][:64]
ans = 0
for i, v in enumerate(a):
    if v:
        ans += 1 << i
print(ans)
