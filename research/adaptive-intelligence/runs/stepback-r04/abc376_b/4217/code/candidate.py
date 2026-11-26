import sys

def solve():
    data = sys.stdin.read().split()
    if not data:
        return
    idx = 0
    N = int(data[idx]); idx += 1
    Q = int(data[idx]); idx += 1
    l = 1
    r = 2
    total = 0
    for _ in range(Q):
        H = data[idx]; T = int(data[idx + 1]); idx += 2
        if H == 'L':
            fixed = r
            start = l
        else:
            fixed = l
            start = r
        best = None
        for dir in (1, -1):
            pos = start
            steps = 0
            ok = True
            while True:
                if pos == T:
                    best = min(best, steps) if best is not None else steps
                    ok = False
                    break
                next_pos = ((pos - 1 + dir) % N) + 1
                if next_pos == fixed:
                    ok = False
                    break
                pos = next_pos
                steps += 1
                if steps > N:
                    ok = False
                    break
            # if not ok, nothing further needed
        total += best if best is not None else 0
        if H == 'L':
            l = T
        else:
            r = T
    print(total)

solve()
