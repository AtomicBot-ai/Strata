import sys

def main():
    data = sys.stdin.read().strip().split()
    if not data:
        return
    it = iter(data)
    N = int(next(it))
    Q = int(next(it))
    H = []
    T = []
    for _ in range(Q):
        H.append(next(it))
        T.append(int(next(it)))

    l = 1
    r = 2
    total = 0

    def nxt(p, d):
        # d = +1 or -1
        if d == 1:
            return p + 1 if p < N else 1
        else:
            return p - 1 if p > 1 else N

    for i in range(Q):
        h = H[i]
        target = T[i]
        if h == 'L':
            fixed = r
            pos = l
        else:
            fixed = l
            pos = r

        best = None
        for d in (1, -1):
            p = pos
            steps = 0
            valid = True
            while p != target:
                np = nxt(p, d)
                # Destination must not be the fixed hand (other hand not specified)
                if np == fixed:
                    valid = False
                    break
                p = np
                steps += 1
                if steps > N:
                    valid = False
                    break
            if valid and (best is None or steps < best):
                best = steps
        if best is None:
            best = 0
        total += best
        if h == 'L':
            l = target
        else:
            r = target

    print(total)

if __name__ == "__main__":
    main()
