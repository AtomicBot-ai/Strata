import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))
    left = [0] * (n + 1)
    seen = set()
    for k in range(1, n + 1):
        seen.add(a[k - 1])
        left[k] = len(seen)
    right = [0] * (n + 1)
    seen = set()
    for k in range(n, 0, -1):
        seen.add(a[k - 1])
        right[k - 1] = len(seen)
    best = 0
    for i in range(1, n - 1):
        cur = 0
        freq = {}
        for j in range(i + 1, n):
            v = a[j - 1]
            if freq.get(v, 0) == 0:
                cur += 1
            freq[v] = freq.get(v, 0) + 1
            total = left[i] + cur + right[j]
            if total > best:
                best = total
    print(best)

if __name__ == "__main__":
    main()
