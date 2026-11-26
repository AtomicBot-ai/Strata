import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1+n]))
    left = [0]*(n+1)
    seen = set()
    for idx in range(1, n+1):
        seen.add(a[idx-1])
        left[idx] = len(seen)
    right = [0]*(n+1)
    seen = set()
    for idx in range(n, 0, -1):
        seen.add(a[idx-1])
        right[idx] = len(seen)  # right[k] = distinct in a[k+1..n]? careful
    # Let's define right[k] = distinct in positions k+1..n.
    right2 = [0]*(n+1)
    seen = set()
    for k in range(n, 0, -1):
        seen.add(a[k-1])
        right2[k-1] = len(seen)  # after adding position k, distinct in k..n
    # right2[j] should be distinct in positions j+1..n; from loop, right2[k-1] = distinct in k..n,
    # so right2[j] = distinct in j+1..n.
    ans = 0
    for i in range(1, n-1):
        cnt = {}
        distinct = 0
        for j in range(i+1, n):
            v = a[j-1]
            if cnt.get(v, 0) == 0:
                distinct += 1
            cnt[v] = cnt.get(v, 0) + 1
            total = left[i] + distinct + right2[j]
            if total > ans:
                ans = total
    print(ans)

main()
