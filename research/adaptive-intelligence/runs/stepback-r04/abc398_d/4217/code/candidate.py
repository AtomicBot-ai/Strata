import sys

def main():
    data = sys.stdin.read().split()
    N = int(data[0]); R = int(data[1]); C = int(data[2]); S = data[3]
    smoke = {(0,0)}
    ans = []
    for t in range(1, N+1):
        ch = S[t-1]
        moved = set()
        for r,c in smoke:
            if ch == 'N': moved.add((r-1,c))
            elif ch == 'W': moved.add((r,c-1))
            elif ch == 'S': moved.add((r+1,c))
            elif ch == 'E': moved.add((r,c+1))
        # time t+0.5 check: after movement, before generation
        ans.append('1' if (R,C) in moved else '0')
        if (0,0) not in moved:
            moved.add((0,0))
        smoke = moved
    sys.stdout.write(''.join(ans))

if __name__ == '__main__':
    main()
