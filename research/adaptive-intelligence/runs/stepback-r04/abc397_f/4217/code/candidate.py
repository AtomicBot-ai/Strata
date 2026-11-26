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
        counts = {}
        distinct = 0
        # middle segment from i+1 to j, j from i+1 to n-1
        for j in range(i + 1, n):
            v = a[j - 1]
            if counts.get(v, 0) == 0:
                distinct += 1
            counts[v] = counts.get(v, 0) + 1
            total = left[i] + distinct + right[j]
            if total > best:
                best = total
    print(best)

if __name__ == "__main__":
    main()
