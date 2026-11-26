import sys

def solve():
    data = sys.stdin.read().split()
    idx = 0
    N = int(data[idx]); idx += 1
    Q = int(data[idx]); idx += 1

    l = 1
    r = 2
    total = 0

    def pos(p):
        return (p - 1) % N

    def dist_dir(a, b, d):
        return (b - a) % N if d == 1 else (a - b) % N

    for i in range(Q):
        H = data[idx]; T = int(data[idx+1]); idx += 2
        if H == 'L':
            fixed = r
            cur = l
        else:
            fixed = l
            cur = r

        # target cannot equal fixed (guaranteed).
        best = None

        # two directions around the ring; each path consists of successive adjacent moves.
        # Need to ensure no step lands on fixed (the other hand's current position).
        # Moves are along +1 or -1 mod N (using labels 1..N).
        for d in (1, -1):
            # distance in this direction to target
            if d == 1:
                steps = (T - cur) % N
            else:
                steps = (cur - T) % N

            ok = True
            p = cur
            for _ in range(steps):
                p = ((p - 1 + d) % N) + 1
                if p == fixed:
                    ok = False
                    break
            if ok:
                # also ensure target is not fixed, guaranteed
                if best is None or steps < best:
                    best = steps

        # In this problem, only two directions around the ring. If a direction is impossible, skip.
        if best is None:
            # Should not happen; guarantee only achievable instructions.
            raise RuntimeError("No feasible path")

        total += best
        if H == 'L':
            l = T
        else:
            r = T

    print(total)

solve()
