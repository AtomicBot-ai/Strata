import sys

def main():
    data = sys.stdin.read().split()
    N = int(data[0])
    R = int(data[1])
    C = int(data[2])
    S = data[3]
    smoke = {(0, 0)}
    ans = []
    for i in range(N):
        d = S[i]
        new = set()
        for r, c in smoke:
            if d == 'N':
                new.add((r - 1, c))
            elif d == 'W':
                new.add((r, c - 1))
            elif d == 'S':
                new.add((r + 1, c))
            else:
                new.add((r, c + 1))
        if (0, 0) not in new:
            new.add((0, 0))
        smoke = new
        ans.append('1' if (R, C) in smoke else '0')
    print(''.join(ans))

if __name__ == '__main__':
    main()
