"""Fixed evaluation-only probes for the six R03 tasks. No official hidden labels."""

from collections import Counter, deque
from itertools import accumulate


def case(label, inp, out):
    return dict(label=label, input=inp, output=str(out))


def vector(a):
    return f"{len(a)}\n" + " ".join(map(str, a)) + "\n"


def ring(n, commands):
    hands = {"L": 1, "R": 2}
    total = 0
    for hand, target in commands:
        blocked = hands["R" if hand == "L" else "L"]
        assert target != blocked
        q = deque([(hands[hand], 0)])
        seen = {blocked, hands[hand]}
        while q:
            pos, d = q.popleft()
            if pos == target:
                total += d
                break
            for step in (-1, 1):
                nxt = (pos - 1 + step) % n + 1
                if nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, d + 1))
        hands[hand] = target
    return total


def cases(task):
    if task == "abc344_b":
        return [
            case(str(i), "\n".join(map(str, a)), "\n".join(map(str, reversed(a))))
            for i, a in enumerate(([0], [8, 8, 7, 0], [10**9, 1, 0]))
        ]
    if task == "abc306_b":
        return [
            case(str(i), " ".join(str((n >> j) & 1) for j in range(64)), n)
            for i, n in enumerate((0, 2**63, 2**64 - 1, 0x5555555555555555))
        ]
    if task == "abc398_c":
        result = []
        for i, a in enumerate(
            ([7], [2, 2, 3, 3], [8, 8, 3, 9, 9, 6], [10**9, 5, 10**9, 12, 1])
        ):
            c = Counter(a)
            u = [(v, j) for j, v in enumerate(a, 1) if c[v] == 1]
            result.append(case(str(i), vector(a), max(u)[1] if u else -1))
        return result
    if task == "abc376_b":
        rounds = [
            (3, [("L", 1)]),
            (6, [("L", 3), ("R", 5), ("L", 4)]),
            (7, [("R", 7), ("L", 6), ("R", 1), ("L", 3)]),
        ]
        return [
            case(
                str(i),
                f"{n} {len(cmd)}\n" + "".join(f"{h} {t}\n" for h, t in cmd),
                ring(n, cmd),
            )
            for i, (n, cmd) in enumerate(rounds)
        ]
    if task == "abc397_f":
        result = []
        for i, a in enumerate(
            ([1, 1, 1], [1, 2, 3], [1, 2, 1, 3, 1, 2], [2, 2, 1, 3, 1, 4, 4, 3])
        ):
            best = max(
                len(set(a[:l])) + len(set(a[l:r])) + len(set(a[r:]))
                for l in range(1, len(a) - 1)
                for r in range(l + 1, len(a))
            )
            result.append(case(str(i), vector(a), best))
        # Each of the three segments can contain every one of the 257 values.
        result.append(case("scale", vector(list(range(1, 258)) * 90), 771))
        return result
    if task == "abc398_d":
        result = []
        moves = {"N": (-1, 0), "S": (1, 0), "E": (0, 1), "W": (0, -1)}
        for i, (s, r, c) in enumerate(
            [("E", 0, 1), ("NESWNE", -1, 0), ("NSNS", 1, 1), ("WSWNSE", 0, -2)]
        ):
            smoke = {(0, 0)}
            out = ""
            for ch in s:
                dr, dc = moves[ch]
                smoke = {(x + dr, y + dc) for x, y in smoke} | {(0, 0)}
                out += str(int((r, c) in smoke))
            result.append(case(str(i), f"{len(s)} {r} {c}\n{s}\n", out))
        n = 20000
        result.append(case("scale", f"{n} 0 1\n" + "E" * n + "\n", "1" * n))
        return result
    raise KeyError(task)
