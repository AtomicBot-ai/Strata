import sys

def solve():
    data = sys.stdin.read().split()
    it = iter(data)
    N = int(next(it))
    Q = int(next(it))
    l = 1
    r = 2

    total = 0

    for _ in range(Q):
        H = next(it)
        T = int(next(it))

        if H == 'L':
            moving_start = l
            fixed = r
        else:
            moving_start = r
            fixed = l

        best = None

        for dir_sign in (1, -1):
            pos = moving_start
            steps = 0
            valid = True
            while pos != T:
                nxt = (pos - 1 + dir_sign) % N + 1
                if nxt == fixed:
                    valid = False
                    break
                pos = nxt
                steps += 1
                # stop after full circle to avoid infinite loop
                if steps > N:
                    valid = False
                    break
            if valid and (best is None or steps < best):
                best = steps

        total += best
        if H == 'L':
            l = T
        else:
            r = T

    print(total)

solve()
