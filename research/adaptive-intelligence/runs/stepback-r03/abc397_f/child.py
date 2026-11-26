import sys

def main():
    data = sys.stdin.read().split()
    if not data:
        return
    n = int(data[0])
    A = list(map(int, data[1:1 + n]))

    left = [0] * (n + 1)
    seen = set()
    for k in range(1, n + 1):
        seen.add(A[k - 1])
        left[k] = len(seen)

    right = [0] * (n + 1)
    seen = set()
    for k in range(n, 0, -1):
        seen.add(A[k - 1])
        right[k] = len(seen)

    best = 0
    for i in range(1, n - 1):
        cnt = {}
        distinct = 0
        # j from i+1 to n-1
        for j in range(i + 1, n):
            x = A[j - 1]
            if cnt.get(x, 0) == 0:
                distinct += 1
            cnt[x] = cnt.get(x, 0) + 1
            total = left[i] + distinct + right[j]
            if total > best:
                best = total
        # reset dictionary for next i
        # cnt is rebuilt inside loop; we can't reuse easily due to persistence.
    print(best)

if __name__ == "__main__":
    main()
