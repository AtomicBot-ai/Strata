import sys

def solve():
    input_data = sys.stdin.read().split()
    n = int(input_data[0])
    A = list(map(int, input_data[1:1+n]))
    prefix_distinct = [0]*(n+1)
    distinct_prefix = set()
    for i in range(1, n+1):
        distinct_prefix.add(A[i-1])
        prefix_distinct[i] = len(distinct_prefix)
    # For each j, maintain distinct suffix
    suffix_distinct = [0]*(n+1)
    distinct_suffix = set()
    for j in range(n, 0, -1):
        distinct_suffix.add(A[j-1])
        suffix_distinct[j] = len(distinct_suffix)
    # prefix distinct for left; suffix distinct for right
    # For middle, we need distinct in (i+1..j). Precompute using hashmap over positions? We'll do O(N^2) worst? 3e5 too big. Use approach:
    # For each j, iterate i=1..j-1, compute middle distinct by removing prefix i from set of values in segment? Use dictionary counts.
    ans = 0
    for j in range(2, n):
        # Build suffix distinct
        # distinct suffix in (j+1..n)
        distinct_suffix_set = set(A[j:])  # j is 1-indexed position, segment A[j:] (0-index i.e. positions j+1..n)
        right_cnt = len(distinct_suffix_set)
        # Build middle counts by scanning i from 1 to j-1
        # middle set initially = values in A[0..j-1] (positions 1..j). For i, remove values of prefix A[0..i-1]
        # We maintain freq of middle segment for i=0 (i.e. i=1: segment A[1..j-1] 0-index? Careful)
        # Let's just maintain freq for current i: segment positions i+1..j (1-index) => 0-index A[i:j] (since i 1-index left end; segment A_{i+1}..A_j)
        # Start i=1 => segment A_2..A_j => 0-index A[1:j]
        # Compute freq
        freq = {}
        for k in range(1, j):
            freq[A[k]] = freq.get(A[k], 0) + 1
        distinct_mid = len(freq)
        left_cnt = prefix_distinct[1]  # i=1
        total = left_cnt + distinct_mid + right_cnt
        ans = max(ans, total)
        # Move i from 1 to j-1: for each i, remove A_i (0-index i-1) from freq, update distinct_mid, left_cnt
        for i in range(2, j):
            # remove A_i (0-index i-1) from middle segment (segment A[i-?])
            # For current i, segment 0-index A[i-?] hmm
            # We'll directly recompute: segment A_{i+1..j} = 0-index A[i:j]
            # Starting i=2, segment 0-index A[2:j]? Wait i=1 => A_{2..j} = 0-index A[1:j]. i=2 => A_{3..j} = 0-index A[2:j].
            # Removed elements are A[1:i] (0-index) cumulatively
            # At i=2, removed A[1] (0-index A[1])
            val = A[i-1]  # 0-index A[i-1]
            # Wait segment for i: 0-index A[i:j]. For i=2, A[2:j]. We removed A[1] from previous freq (A[1:j]), so remove A[1] (0-index)
            # Actually previous i=1 freq is A[1:j]. For i=2, we want A[2:j], remove element A[1] (0-index)
            val = A[i-1]  # i=2 -> A[1]
            freq[val] = freq.get(val, 0) - 1
            if freq[val] == 0:
                del freq[val]
            distinct_mid = len(freq)
            left_cnt = prefix_distinct[i]
            total = left_cnt + distinct_mid + right_cnt
            if total > ans:
                ans = total
    print(ans)

solve()
