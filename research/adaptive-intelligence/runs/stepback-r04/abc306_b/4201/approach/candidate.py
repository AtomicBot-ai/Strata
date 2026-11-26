import sys

tokens = sys.stdin.read().split()
a = [int(x) for x in tokens[:64]]
value = 0
for i, bit in enumerate(a):
    if bit:
        value += 1 << i
print(value)
