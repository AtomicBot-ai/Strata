import sys

lines = sys.stdin.read().splitlines()
values = [int(line.strip()) for line in lines if line.strip()]
for value in reversed(values):
    print(value)
