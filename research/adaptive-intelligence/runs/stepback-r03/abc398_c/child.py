import sys
from collections import Counter

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))
    freq = Counter(a)
    best_val = None
    best_label = -1
    for i in range(n):
        if freq[a[i]] == 1:
            if best_val is None or a[i] > best_val:
                best_val = a[i]
                best_label = i + 1
    print(best_label)

main()
