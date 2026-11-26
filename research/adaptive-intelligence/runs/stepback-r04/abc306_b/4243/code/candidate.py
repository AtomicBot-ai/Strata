import sys

def main():
    bits = sys.stdin.read().split()
    value = 0
    for i, b in enumerate(bits):
        if b == '1':
            value |= 1 << i
    print(value)

if __name__ == '__main__':
    main()
