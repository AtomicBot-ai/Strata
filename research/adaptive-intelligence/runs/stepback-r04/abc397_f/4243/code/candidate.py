import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))

    left = [0] * (n + 1)
    seen = set()
    for idx in range(1, n + 1):
        seen.add(a[idx - 1])
        left[idx] = len(seen)

    right = [0] * (n + 1)
    seen = set()
    for idx in range(n, 0, -1):
        seen.add(a[idx - 1])
        right[idx] = len(seen)

    ans = 0
    for i in range(1, n - 1):
        counts = {}
        distinct = 0
        for j in range(i + 1, n):
            x = a[j - 1]
            if x not in counts:
                distinct += 1
            counts[x] = counts.get(x, 0) + 1
            # middle segment is i+1..j (1-indexed), right[j] is suffix after j
            total = left[i] + distinct + right[j]
            if total > ans:
                ans = total
    print(ans)

main()
