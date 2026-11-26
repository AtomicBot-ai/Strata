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
        H = data[idx]; T = int(data[idx+1]); idx += 2
        if H == 'L':
            fixed = r
            cur = l
            other_side = 'L'
        else:
            fixed = l
            cur = r
            other_side = 'R'

        best = None

        for dir in (1, -1):
            # steps around ring, positions in 1..N
            steps = 0
            pos = cur
            valid = True
            while True:
                if pos == T:
                    break
                nxt = (pos - 1 + dir) % N + 1
                if nxt == fixed:
                    valid = False
                    break
                pos = nxt
                steps += 1
                # safety bound: ring only, but target can be far; max N steps
                if steps > N:
                    valid = False
                    break
            if valid and (steps == 0 or pos == T):
                if best is None or steps < best:
                    best = steps

        # If no valid path, guaranteed achievable; but be safe fallback
        if best is None:
            # fallback shortest simple distance (should not happen)
            d = min((T - cur) % N, (cur - T) % N)
            best = d

        total += best

        if H == 'L':
            l = T
        else:
            r = T

    print(total)

if __name__ == "__main__":
    solve()
