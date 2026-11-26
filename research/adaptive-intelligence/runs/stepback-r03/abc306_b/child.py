import sys

bits = sys.stdin.read().split()
val = 0
for i, b in enumerate(bits):
    if b == '1':
        val += 1 << i
print(val)
