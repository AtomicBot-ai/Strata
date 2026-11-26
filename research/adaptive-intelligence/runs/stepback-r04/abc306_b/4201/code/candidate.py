import sys

bits = sys.stdin.read().split()
value = 0
for i, token in enumerate(bits):
    if token == '1':
        value += 1 << i
print(value)
