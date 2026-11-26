import sys
from collections import Counter

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))
    freq = Counter(a)
    best_val = None
    best_label = -1
    for i, v in enumerate(a, 1):
        if freq[v] == 1:
            if best_val is None or v > best_val:
                best_val = v
                best_label = i
    print(best_label)

main()
