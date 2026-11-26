import sys

def solve():
    data = sys.stdin.read().split()
    if not data:
        return
    N = int(data[0])
    R = int(data[1])
    C = int(data[2])
    S = data[3]
    smoke = {(0, 0)}
    res = []
    dirs = {'N': (-1, 0), 'S': (1, 0), 'W': (0, -1), 'E': (0, 1)}
    for ch in S:
        dr, dc = dirs[ch]
        smoke = {(r + dr, c + dc) for r, c in smoke}
        res.append('1' if (R, C) in smoke else '0')
        if (0, 0) not in smoke:
            smoke.add((0, 0))
    sys.stdout.write(''.join(res))

solve()
