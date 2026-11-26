import sys

def main():
    data = sys.stdin.read().split()
    values = [int(x) for x in data]
    out = "\n".join(str(x) for x in reversed(values))
    sys.stdout.write(out + ("\n" if out else ""))

if __name__ == "__main__":
    main()
