import sys

def main():
    data = sys.stdin.read().split()
    values = [int(x) for x in data]
    for x in reversed(values):
        print(x)

if __name__ == "__main__":
    main()
