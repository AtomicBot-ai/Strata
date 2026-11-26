import sys

def main():
    data = sys.stdin.read().split()
    N = int(data[0]); R = int(data[1]); C = int(data[2]); S = data[3]
    smoke = {(0, 0)}
    out = []
    for t in range(1, N + 1):
        ch = S[t - 1]
        new = set()
        for r, c in smoke:
            if ch == 'N':
                nr, nc = r - 1, c
            elif ch == 'W':
                nr, nc = r, c - 1
            elif ch == 'S':
                nr, nc = r + 1, c
            else:
                nr, nc = r, c + 1
            new.add((nr, nc))
        if (0, 0) not in new:
            new.add((0, 0))
        smoke = new
        out.append('1' if (R, C) in smoke else '0')
    sys.stdout.write(''.join(out))

if __name__ == '__main__':
    main()
