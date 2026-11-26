import sys

def dist_along(start, target, direction, N):
    d = 0
    pos = start
    while pos != target:
        pos = (pos - 1 + direction) % N + 1
        d += 1
    return d

def route_cost(start, target, fixed, N, direction):
    d = 0
    pos = start
    while pos != target:
        nxt = (pos - 1 + direction) % N + 1
        if nxt == fixed:
            return None
        pos = nxt
        d += 1
    return d

def min_cost(start, target, fixed, N):
    ans = None
    for direction in (1, -1):
        c = route_cost(start, target, fixed, N, direction)
        if c is not None and (ans is None or c < ans):
            ans = c
    return ans

def main():
    data = sys.stdin.read().split()
    N = int(data[0])
    Q = int(data[1])
    l = 1
    r = 2
    total = 0
    idx = 2
    for _ in range(Q):
        H = data[idx]
        T = int(data[idx + 1])
        idx += 2
        if H == 'L':
            cost = min_cost(l, T, r, N)
            l = T
        else:
            cost = min_cost(r, T, l, N)
            r = T
        total += cost
    print(total)

main()
