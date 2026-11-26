import sys

def main():
    data = sys.stdin.read().split()
    bits = list(map(int, data[:64]))
    value = 0
    for i, b in enumerate(bits):
        if b:
            value += 1 << i
    print(value)

if __name__ == "__main__":
    main()
