import sys

def main():
    data = sys.stdin.read().split()
    if not data:
        return
    idx = 0
    N = int(data[idx]); idx += 1
    Q = int(data[idx]); idx += 1

    left = 1
    right = 2

    total = 0

    for _ in range(Q):
        H = data[idx]; T = int(data[idx+1]); idx += 2
        if H == 'L':
            moving = left
            fixed = right
        else:
            moving = right
            fixed = left

        best = None
        for dir in (1, -1):
            pos = moving
            steps = 0
            valid = True
            # Explore paths around the ring until target is reached.
            # Avoid moving into fixed position.
            while True:
                nxt = ((pos - 1 + dir) % N) + 1
                if nxt == fixed:
                    valid = False
                    break
                pos = nxt
                steps += 1
                if pos == T:
                    valid = True
                    break
                if steps > N:
                    valid = False
                    break

            if valid:
                if best is None or steps < best:
                    best = steps

        total += best
        if H == 'L':
            left = T
        else:
            right = T

    print(total)

if __name__ == "__main__":
    main()
