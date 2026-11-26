import sys
from collections import deque

def solve():
    data = sys.stdin.read().splitlines()
    if not data:
        return
    n, q = map(int, data[0].split())
    instructions = []
    for i in range(1, q + 1):
        parts = data[i].split()
        instructions.append((parts[0], int(parts[1])))

    l = 1
    r = 2
    total = 0

    for h, t in instructions:
        fixed = r if h == 'L' else l
        if h == 'L':
            start = l
            move_to_l = True
        else:
            start = r
            move_to_l = False

        if start == t:
            dist = 0
        else:
            # BFS on cycle with forbidden fixed position
            # positions 1..n
            dist = [None] * (n + 1)
            dist[start] = 0
            dq = deque([start])
            while dq:
                u = dq.popleft()
                if u == t:
                    break
                du = dist[u]
                for v in ((u - 2) % n + 1, (u % n) + 1):
                    if v == fixed:
                        continue
                    if dist[v] is None:
                        dist[v] = du + 1
                        dq.append(v)

            dist = dist[t]

        total += dist
        if move_to_l:
            l = t
        else:
            r = t

    print(total)

solve()
