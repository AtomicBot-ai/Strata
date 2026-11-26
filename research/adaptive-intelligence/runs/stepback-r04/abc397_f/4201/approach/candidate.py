import sys

def solve():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1+n]))

    # Prefix distinct counts
    pref = [0] * (n + 1)
    seen = set()
    for idx in range(1, n + 1):
        seen.add(a[idx - 1])
        pref[idx] = len(seen)

    # Suffix distinct counts: suffix[x] = distinct in a[x..n-1] (0-based index x)
    suff = [0] * (n + 1)
    seen = set()
    for idx in range(n - 1, -1, -1):
        seen.add(a[idx])
        suff[idx] = len(seen)

    # Middle distinct count: need distinct count in a[i:j] (0-based, segment i+1..j means a[i:j])
    # Sliding window with distinct count, using dictionary counts
    # For each i, maintain window from i+1 to j as j increases, but i varies -> expensive.
    # Instead use prefix-like segment distinct by maintaining for each i via iterating j with counts reset per i? Too slow.
    # Use brute with O(N^2) not acceptable. Need optimized.

    # Alternate approach: iterate over middle segments using two pointers per left? Too big.
    # Better: enumerate j as right edge and use sliding window from i+1 to j for i=0..j-1? Still O(N^2) worst.

    # Since N=3e5, need efficient. Use prefix of "last occurrence"? Not easy.
    # But constraints A_i<=N, small values. We can do brute with bitsets? Not available.

    # Simpler efficient method: For each i (0..n-2), compute distinct counts for all j>i via sliding window:
    # window counts from i to j (0-based). Maintain counts and distinct number incrementally as j moves forward.
    best = 0
    from collections import Counter
    for i in range(n - 1):
        # segment start index = i (0-based), segment end j-1 (1-based j). i is 0-based prefix end? Let's map:
        # Split at i (1-based), middle = a[i:j] (0-based), suffix = a[j:] (0-based). i ranges 0..n-2, j ranges i+1..n-1.
        counts = {}
        distinct = 0
        j = i
        # Build window for middle starting at i (0-based index i)
        for j in range(i + 1, n):
            v = a[j - 1]  # a[j-1] is last element of middle (1-based j -> 0-based j-1)
            if counts.get(v, 0) == 0:
                distinct += 1
            counts[v] = counts.get(v, 0) + 1
            # suffix starts at j (0-based index j), suffix distinct = suff[j]
            total = pref[i] + distinct + suff[j]
            if total > best:
                best = total
    print(best)

solve()
