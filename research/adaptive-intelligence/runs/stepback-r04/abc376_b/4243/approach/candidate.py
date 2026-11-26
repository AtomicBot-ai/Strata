import sys

def solve():
    data = sys.stdin.read().split()
    idx = 0
    N = int(data[idx]); idx += 1
    Q = int(data[idx]); idx += 1
    instructions = []
    for _ in range(Q):
        H = data[idx]; T = int(data[idx+1]); idx += 2
        instructions.append((H, T))

    l = 1
    r = 2
    total = 0

    def ring_dist(start, target, forbidden):
        # positions numbered 1..N, adjacency cyclic
        # cannot pass through forbidden (the fixed hand). moving hand must not enter forbidden.
        # Compute minimal steps from start to target avoiding forbidden.
        # Since start != target and target != forbidden.
        # Two directed paths on cycle: clockwise and counterclockwise.
        def steps_to(direction):
            # direction +1 means increasing part with wrap (1->2->...->N->1), direction -1 means decreasing
            pos = start
            cnt = 0
            while pos != target:
                if direction == 1:
                    pos = pos + 1
                    if pos > N:
                        pos = 1
                else:
                    pos = pos - 1
                    if pos < 1:
                        pos = N
                cnt += 1
                if pos == forbidden:
                    return None
                if cnt > N:
                    return None
            return cnt
        cw = steps_to(1)
        ccw = steps_to(-1)
        vals = [v for v in (cw, ccw) if v is not None]
        if not vals:
            # Cannot pass forbidden? But guaranteed achievable. Return None
            return None
        return min(vals)

    for H, T in instructions:
        if H == 'L':
            fixed = r
            start = l
            # target T must != fixed (guaranteed)
            d = ring_dist(start, T, fixed)
            # Moving hand should not equal fixed along path; distance ensures avoidance.
            # But is the path length always equal to minimal operations? Need ensure the path does not enter fixed hand and also cannot pass through? yes.
            if d is None:
                raise ValueError("Not achievable")
            total += d
            l = T
        else:
            fixed = l
            start = r
            d = ring_dist(start, T, fixed)
            if d is None:
                raise ValueError("Not achievable")
            total += d
            r = T

    print(total)

solve()
