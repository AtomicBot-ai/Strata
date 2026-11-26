import sys

def main():
    input_data = sys.stdin.read().split()
    idx = 0
    N = int(input_data[idx]); idx += 1
    Q = int(input_data[idx]); idx += 1

    l = 1
    r = 2

    total = 0

    for i in range(Q):
        H = input_data[idx]; T = int(input_data[idx + 1]); idx += 2

        if H == 'L':
            moving = l
            fixed = r
        else:
            moving = r
            fixed = l

        best = None
        for dir_step in (1, -1):
            pos = moving
            steps = 0
            ok = True
            while pos != T:
                nxt = ((pos - 1 + dir_step) % N) + 1
                if nxt == fixed:
                    ok = False
                    break
                pos = nxt
                steps += 1
                if steps >= N:
                    ok = False
                    break
            if ok:
                if best is None or steps < best:
                    best = steps
        total += best
        if H == 'L':
            l = T
        else:
            r = T

    print(total)

if __name__ == "__main__":
    main()
