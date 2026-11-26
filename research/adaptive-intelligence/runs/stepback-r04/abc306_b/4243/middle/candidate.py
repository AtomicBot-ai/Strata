import sys

bits = sys.stdin.read().split()
value = 0
for i, b in enumerate(bits):
    value |= (int(b) << i)
print(value)
