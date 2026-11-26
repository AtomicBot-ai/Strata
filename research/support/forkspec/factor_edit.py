from pathlib import Path
import difflib
root=Path('.work/forkspec/policy-src/engine/src/inkling2')
changes=[]
def edit(n, rules):
 p=root/n;old=p.read_text();s=old
 for a,b in rules:
  assert s.count(a)==1,(n,a,s.count(a))
  s=s.replace(a,b)
 p.write_text(s)
 path='engine/src/inkling2/'+n
 changes.extend(difflib.unified_diff(old.splitlines(True),s.splitlines(True),'a/'+path,'b/'+path))
edit('ink_backend.h',[('    // Optional fused on-device greedy speculative step', '''    virtual void set_plain_cost(int, double) {}
    virtual bool last_step_was_plain() const { return false; }

    // Optional fused on-device greedy speculative step''')])
edit('metal/ink_metal_backend.mm',[
('        ckpts_.assign','        cost_.assign(par, 0.0);\n        ckpts_.assign'),
('    int dspark_spec_step_greedy(', '''    void set_plain_cost(int slot, double ms) override { cost_[slot] = ms; }
    bool last_step_was_plain() const override { return cooldown_step_; }

    int dspark_spec_step_greedy('''),
('        if (!runner_.use_dspark || !runner_.use_dspark_meff || slot < 0', '        cooldown_step_ = false;\n        if (!runner_.use_dspark || !runner_.use_dspark_meff || slot < 0'),
('            --slot_cooldown_[slot];','            cooldown_step_ = true;\n            --slot_cooldown_[slot];'),
('const double t_plain_ms = runner_.is_apple10','const double t_plain_ms = cost_[slot] > 0.0 ? cost_[slot] : runner_.is_apple10'),
('    std::vector<double> slot_ema_gain_;','    bool cooldown_step_ = false;\n    std::vector<double> cost_;\n    std::vector<double> slot_ema_gain_;')])
edit('ink_serve.h',[
('    int gov_plain_left = 0;', '''    int rounds = 0, ordinary = 0, cooldown = 0, probes = 0;
    uint64_t policy_request = 0;
    double observed_ms = 0.0;
    int gov_plain_left = 0;'''),
('    double gov_t_plain =', '''    auto enabled = [](const char* name) { auto* v = std::getenv(name); return v && std::string(v) == "1"; };
    const bool measure_cost = spec_adapt && enabled("FORKSPEC_MEASURE_COST");
    const bool warm_four = spec_adapt && enabled("FORKSPEC_WARM_FOUR");
    const bool trace_steps = enabled("FORKSPEC_POLICY_TRACE");
    uint64_t admission_id = 0;
    auto ordinary_step = [&](ActiveReq& rq, bool cooldown, double ms) {
        ++rq.ordinary;
        if (cooldown) ++rq.cooldown;
        if (rq.gov_calib_left) ++rq.probes;
        if (trace_steps) std::fprintf(stderr, "plain request=%llu slot=%d pos=%d path=%s calib=%d ms=%.4f\\n",
            (unsigned long long)rq.policy_request, rq.slot, rq.cur_pos, cooldown ? "fused_cooldown" : "ordinary_forward", rq.gov_calib_left, ms);
        if (measure_cost && rq.ordinary > 1 && std::isfinite(ms) && ms > 0.0) {
            rq.observed_ms = rq.observed_ms ? 0.9 * rq.observed_ms + 0.1 * ms : ms;
            backend.set_plain_cost(rq.slot, rq.observed_ms);
        }
    };
    double gov_t_plain ='''),
('        if (rq.is_solo) {\n            // Emit full', '''        std::fprintf(stderr, "factor request=%llu rounds=%d plain=%d probes=%d cooldown=%d ema_ms=%.4f\\n",
                     (unsigned long long)rq.policy_request, rq.rounds, rq.ordinary, rq.probes, rq.cooldown, rq.observed_ms);
        if (rq.is_solo) {
            // Emit full'''),
('        rq.gov_calib_left = (spec_adapt && gov_t_plain <= 0.0) ? 4 : 0;', '''        rq.policy_request = ++admission_id;
        rq.rounds = rq.ordinary = rq.cooldown = rq.probes = 0;
        rq.observed_ms = 0.0;
        backend.set_plain_cost(rq.slot, 0.0);
        rq.gov_calib_left = (spec_adapt && (gov_t_plain <= 0.0 || warm_four)) ? 4 : 0;'''),
('                    rq.drafts_offered += drafted;', '''                    if (backend.last_step_was_plain()) ordinary_step(rq, true, (now_s() - gov_t0) * 1000);
                    else ++rq.rounds;
                    rq.drafts_offered += drafted;'''),
('                rq.drafts_offered += nd;', '                ++rq.rounds;\n                rq.drafts_offered += nd;'),
('            const bool stop = is_stop_tok(tok);', '''            if (!just_finished_prefill && n_active == 1 && n_want == 1)
                ordinary_step(rq, false, (now_s() - t_step0) * 1000);
            const bool stop = is_stop_tok(tok);''')])
Path('research/forkspec/factor.patch').write_text(''.join(changes))
