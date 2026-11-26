import sys

tokens = sys.stdin.read().split()
bits = list(map(int, tokens))
value = 0
for i, bit in enumerate(bits):
    if bit:
        value += 1 << i
print(value)
