import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    R = int(data[1])
    C = int(data[2])
    S = data[3]
    smoke = {(0, 0)}
    out = []
    for i, ch in enumerate(S):
        dr = 0
        dc = 0
        if ch == 'N':
            dr = -1
        elif ch == 'S':
            dr = 1
        elif ch == 'W':
            dc = -1
        elif ch == 'E':
            dc = 1
        new_smoke = set()
        for r, c in smoke:
            new_smoke.add((r + dr, c + dc))
        if (0, 0) not in new_smoke:
            new_smoke.add((0, 0))
        smoke = new_smoke
        out.append('1' if (R, C) in smoke else '0')
    sys.stdout.write(''.join(out))

if __name__ == '__main__':
    main()
