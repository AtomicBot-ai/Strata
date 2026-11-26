import sys

def main():
    data = sys.stdin.read().split()
    if not data:
        return
    N = int(data[0])
    R = int(data[1])
    C = int(data[2])
    S = data[3].strip()
    smoke = {(0,0)}
    out = []
    for t in range(1, N+1):
        d = S[t-1]
        moved = set()
        if d == 'N':
            for r,c in smoke:
                moved.add((r-1,c))
        elif d == 'W':
            for r,c in smoke:
                moved.add((r,c-1))
        elif d == 'S':
            for r,c in smoke:
                moved.add((r+1,c))
        else: # E
            for r,c in smoke:
                moved.add((r,c+1))
        out.append('1' if (R,C) in moved else '0')
        if (0,0) not in moved:
            moved.add((0,0))
        smoke = moved
    sys.stdout.write(''.join(out))

if __name__ == '__main__':
    main()
