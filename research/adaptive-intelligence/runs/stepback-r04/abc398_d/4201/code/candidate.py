import sys

def main():
    data = sys.stdin.read().split()
    N = int(data[0]); R = int(data[1]); C = int(data[2])
    S = data[3]
    smoke = {(0, 0)}
    res = []
    for ch in S:
        new = set()
        if ch == 'N':
            for r, c in smoke:
                new.add((r - 1, c))
        elif ch == 'S':
            for r, c in smoke:
                new.add((r + 1, c))
        elif ch == 'W':
            for r, c in smoke:
                new.add((r, c - 1))
        else:  # E
            for r, c in smoke:
                new.add((r, c + 1))
        res.append('1' if (R, C) in new else '0')
        if (0, 0) not in new:
            new.add((0, 0))
        smoke = new
    sys.stdout.write(''.join(res))

main()
