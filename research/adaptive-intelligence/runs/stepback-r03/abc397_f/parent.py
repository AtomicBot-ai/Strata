import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    A = list(map(int, data[1:1+n]))
    left = [0]*(n+1)
    seen = set()
    for k in range(1, n+1):
        seen.add(A[k-1])
        left[k] = len(seen)
    right = [0]*(n+1)
    seen = set()
    for k in range(n, 0, -1):
        seen.add(A[k-1])
        right[k-1] = len(seen)
    # right[j] = distinct in A[j+1..n]
    ans = 0
    for i in range(1, n-1):  # i 1..n-2
        counts = {}
        distinct = 0
        for j in range(i+1, n):  # j i+1..n-1
            v = A[j-1]
            if counts.get(v, 0) == 0:
                distinct += 1
            counts[v] = counts.get(v, 0) + 1
            total = left[i] + distinct + right[j]
            if total > ans:
                ans = total
    print(ans)

if __name__ == "__main__":
    main()
