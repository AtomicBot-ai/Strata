import sys

def main():
    lines = sys.stdin.read().splitlines()
    vals = []
    for line in lines:
        line = line.strip()
        if line:
            vals.append(int(line))
    for v in reversed(vals):
        print(v)

if __name__ == "__main__":
    main()
