import sys

tokens = sys.stdin.read().split()
value = 0
for i, token in enumerate(tokens[:64]):
    if token == '1':
        value += 1 << i
print(value)
