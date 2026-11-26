import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))

    freq = {}
    for x in a:
        freq[x] = freq.get(x, 0) + 1

    best_val = None
    best_label = -1

    for i, x in enumerate(a):
        if freq[x] == 1:
            if best_val is None or x > best_val:
                best_val = x
                best_label = i + 1

    print(best_label)

if __name__ == "__main__":
    main()
