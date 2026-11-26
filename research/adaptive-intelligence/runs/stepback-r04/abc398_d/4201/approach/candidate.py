import sys

def main():
    data = sys.stdin.read().split()
    N = int(data[0])
    R = int(data[1])
    C = int(data[2])
    S = data[3].strip()

    # Build segments: (start_time, end_time, direction, origin)
    # A segment is active from t (after generation) until next wind change or N.
    segments = []
    cur = S[0]
    start = 1
    # Actually simulate segment generation by processing wind direction changes.
    # At each t, smoke present before wind moves? Need carefully reconstruct.
    # Simulation approach: maintain list of segments with generation time and direction.
    # A segment begins when smoke exists only at 0,0? The rule: after wind moves all smoke,
    # if no smoke at (0,0), new smoke generated at (0,0). Then next wind moves it.
    # Segments: start when generated, then moves for each subsequent wind.
    # Represent segment with start_generation_time (generation happens at end of step t), direction = next wind? Easier: track active segments as list with time range.

    # We simulate step by step using a queue of active segments:
    # Each segment has birth time b (at time b, after wind at time b) and current position after that wind.
    # Active segment moves each subsequent t if wind direction d. It becomes inactive? Smoke doesn't disappear except? Smoke persists and moves; there is no disappearance. But if generated and moves each step, it always persists.
    # However the rule says all smoke present at that time moves; if no smoke in cell (0,0), new smoke is generated at 0,0.
    # Smoke never disappears, but cells are tracked; many segments.
    # We need answer for each t, so maintain list of active smoke positions. N<=2e5, positions unique.
    # Since smoke moves together in groups, group by generation event and direction runs.
    # Better: segment-based.
    # Generation occurs at time t (after wind at t) when (0,0) is empty. It has position (0,0) at that time.
    # Then at each subsequent time u, if smoke at position (0,0)? The generated smoke moves with all smoke; it may be in same position as others, but group by birth.
    # Actually all smoke present moves each step, including older smoke. A new smoke generated at 0,0 at end of step t. At time t+0.5, all active smoke positions are moved positions.
    # For each t, smoke present at t+0.5 = positions after wind at time t. We can track groups of smoke that started at same generation time; they move together until next generation. But they remain distinct groups; all groups move each step. So for each generation group g, its position evolves by summing wind directions for each step after g.
    # At time t+0.5 (after step t), group born at b<=t is at position (0,0) + sum directions of steps b..t (since born after step b, then moves at steps b+1..t). Wait at generation time b, smoke exists at (0,0) at time b+0.5? Rule: At times t=1..N: Wind blows and all smoke present at that time moves. Then if no smoke in (0,0), new smoke is generated at (0,0).
    # At time 0.5 (after t=1), smoke generated? Initially at t=0 smoke at (0,0). At t=1 wind moves smoke, then if no smoke at (0,0), new smoke generated. So time t+0.5 includes post-wind t and possible generation.
    # Need to track generation condition.

    # Let's do direct simulation with a set/list of active positions, storing groups to compute R,C for each t.
    # N=2e5; direct list of positions could grow O(N). Fine.
    groups = []  # list of (origin position after birth? and current pos)
    # Each group: (born_time, pos_r, pos_c). Initially born at time 0 with position (0,0).
    # At each t:
    #   move all groups by direction S[t-1]
    #   then check if (0,0) is empty among positions (i.e., no group at origin)
    #   if empty, create new group (born_time=t, pos=(0,0))
    #   record answer for t (smoke exists at (R,C))
    # For efficiency, store groups as (born_time, r, c) and update positions. Number groups could be O(N). For each t checking membership of (R,C) among groups could be O(N^2). Need better.
    # Instead track set of positions present (all smoke positions), and for each t, if (R,C) in set then 1.
    # But set membership must be updated after moves: all positions move together. We can maintain a dict position->group? Number distinct positions = number groups (if no duplicates). Groups could collide at same cell? Smoke in same cell is just one cell; set tracks cell presence. Number of distinct cells can grow O(N). At each step, move all positions: O(number groups). Total O(N^2) worst if many generations.
    # Need segment-based to avoid O(N^2).
    # Smoke groups move together; distinct positions can collide. We only need whether target cell occupied at each t.
    # Since target fixed, compute for each t whether any group position == (R,C). This is equivalent to existence of group birth b such that (R,C) = (0,0) + displacement_b(t), where displacement_b(t) = sum directions of steps b..t (if b<=t). And that group was created at b. But groups born at b are created when (0,0) empty after step b. All smoke groups born after that? Wait a group born at b moves at steps b+1..t, not at step b? At step b, generation occurs after wind. The group born at b is at (0,0) after wind at time b, so its position at time b+0.5 is (0,0). At step b+1 it moves. So for t>=b, position = sum of steps b+1..t? Hmm if group born at time b (after step b), at time t+0.5 after step t, it has moved at steps b+1..t, total t-b moves. At b itself it is at (0,0). For t=b, position=(0,0). So displacement = sum directions of steps b+1..t.
    # But also initial group born at time 0 (t=0) with position (0,0) at time 0, then at t=1 it moves. For t, initial group position = sum steps 1..t.
    # Generation condition: after step t, if no smoke in (0,0) (position equal origin after moving all groups), then new group born at (0,0). Thus the origin is empty after wind at t; note that all groups moved away from origin; no group remains at origin. New group born.
    # A new group born at t is at origin at time t+0.5, and then moves at subsequent steps.
    # We can compute generation times and intervals. Each segment (group) born at time b has position trajectory for t>=b: (0,0)+ sum directions of steps b+1..t (for t>b). Initial group b=0: position = sum steps 1..t.
    # Need determine target occupancy at each t. Could iterate over t and groups; O(N * groups). Need O(N) or O(number groups).
    # Use segment representation: a segment spans times b..N with position = (0,0) + sum directions of steps b+1..t. But if t=b, position=(0,0).
    # For target (R,C), group born at b is at target at time t if sum directions steps b+1..t = (R,C). This is a prefix sum condition. Let P_t = cumulative displacement after t steps. For group b, displacement at time t = P_t - P_b (for b>=0? P_0=(0,0), group born at b has displacement P_t - P_b). Initial group b=0 displacement P_t - P_0 = P_t. For b=t, displacement P_t - P_t = 0 = (0,0), not target. Good.
    # So group born at b is at target at time t if P_t - P_b = (R,C), i.e. P_b = P_t - (R,C). For each t, need to know if there exists a generation time b <= t with P_b = P_t - (R,C), and group born at b. But groups born at b are determined by generation rule: b is a generation time iff after step b, (0,0) empty. That is P_b == (0,0)? Let's see after step b, positions are P_b for initial group and all older groups at P_b - P_{older}. Origin empty iff no group at (0,0), i.e. no b_old <= b with P_b - P_{b_old}=0 -> P_{b_old}=P_b. But b is generation time iff origin empty after wind at b. Origin after wind at b is occupied by initial group if P_b=(0,0) (because initial group at P_b), and by any group born at b_old <= b with P_b=P_{b_old}. So origin empty iff P_b != P_{b_old} for all generation times b_old<=b and P_b != (0,0)? Wait initial group is born at b=0, and its position after step b is P_b. Origin empty iff P_b != (0,0) (initial group not at origin) AND no generation group born at b_old has P_b = P_{b_old}. But any group born at b_old is at P_b - P_{b_old}; at origin iff P_b = P_{b_old}. Thus origin empty iff P_b is not equal to P_0=(0,0) (initial group) and not equal to P_{b_old} for any prior generation time b_old. Since P_b=0 implies initial group at origin, not empty. So origin empty iff P_b != 0 and P_b != P_{b_old} for all b_old in generations <= b.
    # This is tricky but generation times are exactly times b where P_b not seen before? Let's verify: after wind at t, if no smoke in (0,0), new smoke generated at (0,0). Origin empty iff P_b not equal to any previous P_x for x in {0} ∪ generation times? Actually previous groups all have birth times in {0}∪generations. Their positions after step b are P_b - P_{b_old}. At origin iff P_b = P_{b_old}. So origin empty iff P_b not equal to P_{b_old} for all old birth times. Thus new generation iff P_b is a new value (not seen among P_0 and P_{b_old} for previous generations). Note P_0=0.
    # Since generation times are determined by equality of prefix sums, this can be computed online with a set of seen prefix sums.
    # For answer at time t, we need existence of b<=t with P_b = P_t - (R,C), where b is initial or a generation time. If that b is initial (b=0) or generation time, and b<=t, then smoke at target at t.
    # Since generation times are determined by prefix sums distinctness, we can simply compute set of prefix sums seen up to t that are generation times or 0. Then check if P_t - target is in that set. This gives O(1) per t with a set.
    # Need ensure P_b for generation times are all distinct and P_0=0 included. If P_b is new at generation, then it cannot be seen before. But P_t - target could be any seen prefix sum, including old non-generation sums. Need include only birth times 0 and generation times, not all previous positions. However maybe the smoke at target at time t can be from a group born at b where P_b = P_t - target. If that b is not a generation time, then no group born at b exists, so not valid. Thus need set of P_b for birth times (0 and generations).
    # Compute generations: iterate t=1..N, maintain set seen of prefix sums at birth times? At each t, P_t = P_{t-1}+delta. Check if P_t
