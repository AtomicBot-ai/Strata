import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))

    freq = {}
    for x in a:
        freq[x] = freq.get(x, 0) + 1

    max_val = -1
    label = -1
    for i, x in enumerate(a, start=1):
        if freq[x] == 1 and x > max_val:
            max_val = x
            label = i

    print(label)

if __name__ == "__main__":
    main()
