import sys

def main():
    lines = sys.stdin.read().splitlines()
    values = []
    for line in lines:
        if line.strip() == '':
            continue
        x = int(line.strip())
        if x == 0:
            values.append(0)
            break
        values.append(x)
    for x in reversed(values):
        print(x)

if __name__ == '__main__':
    main()
