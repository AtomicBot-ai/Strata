from pathlib import Path
root=Path('.work/spec-policy-fast/source/engine/src/inkling2')
def change(path, edits):
    p=root/path
    s=p.read_text()
    for old,new in edits:
        if s.count(old)!=1: raise RuntimeError((old,s.count(old)))
        s=s.replace(old,new)
    p.write_text(s)
change('ink_backend.h',[('    // Optional fused on-device greedy', '''    // Start a new per-slot cost estimate with ms=0, or observe a completed plain decode step.
    virtual void observe_plain_step(int /*slot*/, double /*ms*/) {}

    // Optional fused on-device greedy''')])
change('ink_serve.h',[
('    double gov_t_plain =', '''    const char* cost_env = std::getenv("TURBINE_ADAPTIVE_PLAIN_COST");
    const bool measured_cost = spec_adapt && use_dspark && std::string(backend.backend_name()) == "metal" &&
        cost_env && std::string(cost_env) == "1";
    double gov_t_plain ='''),
('        rq.gov_calib_left = (spec_adapt && gov_t_plain <= 0.0) ? 4 : 0;', '''        const bool probe = measured_cost && rq.s.greedy() && !rq.s.penalties();
        if (measured_cost) backend.observe_plain_step(rq.slot, 0.0);
        rq.gov_calib_left = (spec_adapt && (gov_t_plain <= 0.0 || probe)) ? 4 : 0;'''),
('                    continue;\n                }\n            }\n            int32_t draft_ids', '''                    if (measured_cost && drafted == 0 && kept == 1) {
                        backend.observe_plain_step(rq.slot, (now_s() - gov_t0) * 1000.0);
                    }
                    continue;
                }
            }
            int32_t draft_ids'''),
('            if (rg.gov_calib_left > 0) {','''            // Ignore the first calibration step, which can include initial graph setup.
            if (measured_cost && rg.s.greedy() && !rg.s.penalties() && rg.gov_calib_left != 4) {
                backend.observe_plain_step(rg.slot, ms);
            }
            if (rg.gov_calib_left > 0) {''')])
change('metal/ink_metal_backend.mm',[
('        slot_ema_gain_.assign','        plain_cost_ms_.assign((size_t)par, 0.0);\n        slot_ema_gain_.assign'),
('    int dspark_spec_step_greedy(','''    void observe_plain_step(int slot, double ms) override {
        double& estimate = plain_cost_ms_[slot];
        if (ms == 0.0) estimate = 0.0;
        else if (std::isfinite(ms) && ms > 0.0) estimate = estimate > 0.0 ? 0.9 * estimate + 0.1 * ms : ms;
    }

    int dspark_spec_step_greedy('''),
('        const double t_plain_ms = runner_', '        const double default_plain_ms = runner_'),
('        auto update_gain = [&](int n_emit) {','''        const double t_plain_ms = plain_cost_ms_[slot] > 0.0 ? plain_cost_ms_[slot] : default_plain_ms;
        static const bool trace = std::getenv("TURBINE_POLICY_TRACE") != nullptr;
        auto update_gain = [&](int n_emit, int nodes) {'''),
('            const double step_gain =','''            if (trace) std::fprintf(stderr, "policy pos=%d nodes=%d emit=%d verify_gpu_ms=%.4f round_ms=%.4f plain_ms=%.4f\\n",
                                    anchor_pos, nodes, n_emit, runner_.last_gpu_ms, step_ms, t_plain_ms);
            const double step_gain ='''),
('            update_gain(1 + acc);','            update_gain(1 + acc, tm);'),
('\n        update_gain(1 + acc);','\n        update_gain(1 + acc, tm);'),
('    std::vector<double> slot_ema_gain_;','    std::vector<double> plain_cost_ms_;\n    std::vector<double> slot_ema_gain_;')])
