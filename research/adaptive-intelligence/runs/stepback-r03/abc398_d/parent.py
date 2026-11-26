import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    R = int(data[1])
    C = int(data[2])
    S = data[3]
    smoke = {(0, 0)}
    ans = []
    for t in range(1, n + 1):
        ch = S[t - 1]
        new = set()
        if ch == 'N':
            for r, c in smoke:
                new.add((r - 1, c))
        elif ch == 'W':
            for r, c in smoke:
                new.add((r, c - 1))
        elif ch == 'S':
            for r, c in smoke:
            for r, c in smoke:
                new.add((r + 1, c))
        else: # E
            for r, c in smoke:
                new.add((r, c + 1))
        # time t+0.5: check before generation
        ans.append('1' if (R, C) in new else '0')
        if (0, 0) not in new:
            new.add((0, 0))
        smoke = new
    sys.stdout.write(''.join(ans))

if __name__ == '__main__':
    main()
