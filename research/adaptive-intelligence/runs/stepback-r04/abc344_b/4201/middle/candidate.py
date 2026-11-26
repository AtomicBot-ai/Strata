import sys

def main():
    values = [int(line) for line in sys.stdin if line.strip()]
    for v in reversed(values):
        print(v)

if __name__ == "__main__":
    main()
