import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))
    freq = {}
    for x in a:
        freq[x] = freq.get(x, 0) + 1
    best = -1
    best_label = -1
    for i in range(n):
        if freq[a[i]] == 1:
            if a[i] > best:
                best = a[i]
                best_label = i + 1
    print(best_label if best_label != -1 else -1)

if __name__ == "__main__":
    main()
