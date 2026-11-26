import sys

data = sys.stdin.read().split()
arr = [int(x) for x in data]
for x in reversed(arr):
    print(x)
