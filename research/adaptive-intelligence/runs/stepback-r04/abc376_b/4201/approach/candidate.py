import sys

def solve():
    data = sys.stdin.read().splitlines()
    idx = 0
    N = int(data[idx].split()[0]); Q = int(data[idx].split()[1]); idx += 1
    l = 1
    r = 2
    total = 0
    for _ in range(Q):
        line = data[idx].split(); idx += 1
        H = line[0]
        T = int(line[1])
        if H == 'L':
            start = l; fixed = r; target = T
        else:
            start = r; fixed = l; target = T
        # two directions on cycle
        # direction +1 (increasing labels, wrap)
        # number of steps for +1 direction to reach target
        d_plus = (target - start) % N
        d_minus = (start - target) % N
        # Validate path for +1: positions after each step start+1..target; none equals fixed.
        # The number of steps d_plus; path positions p_k = (start + k - 1) % N? Let's enumerate k=1..d_plus.
        def valid(direction):
            if d_plus == 0 and direction == 'plus':
                return True
            if direction == 'plus':
                steps = d_plus
                for k in range(1, steps+1):
                    pos = ((start-1 + k) % N) + 1
                    if pos == fixed:
                        return False
                return True
            else:
                steps = d_minus
                if steps == 0:
                    return True
                for k in range(1, steps+1):
                    pos = ((start-1 - k) % N) + 1
                    if pos == fixed:
                        return False
                return True
        best = None
        for direction, steps in (('plus', d_plus), ('minus', d_minus)):
            if valid(direction):
                if best is None or steps < best:
                    best = steps
        if best is None:
            best = 0
        total += best
        if H == 'L':
            l = T
        else:
            r = T
    print(total)

solve()
