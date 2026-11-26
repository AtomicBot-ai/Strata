from pathlib import Path
import difflib
base=Path('.work/forkspec/source')
n='engine/src/inkling2/metal/ink_metal_backend.mm'
p=base/n
before=p.read_text()
s=before.replace('    void rollback_slot(int slot, int keep_len) override {','''    // Test observer only. Compare an old K row still required by the next query.
    std::vector<uint16_t> before_k_[2];
    int observed_pos_ = -1;
    uint16_t* probe_row(int slot, int future, bool draft) {
        const auto& c = mod_.man.c;
        int index = 0;
        if (!draft) while (!c.is_swa[c.phys_for_visit(index)]) ++index;
        int stride = draft ? runner_.dsp_kv_stride[0] : runner_.visit_kv_stride[index];
        auto& k = draft ? runner_.dsp_ctx_k[0] : runner_.kv_k[index];
        return k.as<uint16_t>() + (size_t(slot) * stride + future % stride) * c.n_kv * c.head_dim;
    }
    void observe(int slot, int pos, int count) {
        observed_pos_ = -1;
        if (!std::getenv("FORKSPEC_OBSERVE") || pos < 1030 || count < 4) return;
        observed_pos_ = pos + count - 1;
        const auto& c = mod_.man.c;
        for (int d = 0; d <= 1; ++d) {
            auto* row = probe_row(slot, observed_pos_, d);
            before_k_[d].assign(row, row + c.n_kv * c.head_dim);
        }
    }
    void check_rows(int slot, int keep) {
        if (observed_pos_ < keep + 1) return;
        for (int d = 0; d <= 1; ++d) {
            auto& row = before_k_[d];
            auto* actual = probe_row(slot, observed_pos_, d);
            int changed = 0;
            for (size_t i = 0; i < row.size(); ++i) changed += row[i] != actual[i];
            std::fprintf(stderr, "ring_probe draft=%d slot=%d anchor=%d keep=%d future=%d stride=%d changed=%d words=%zu\\n",
                         d, slot, last_ver_pos0_, keep, observed_pos_, d ? runner_.dsp_kv_stride[0] : mod_.man.c.swa_win, changed, row.size());
        }
        observed_pos_ = -1;
    }
    void rollback_slot(int slot, int keep_len) override {''').replace('runner_.restore_verify_step(slot, keep_len - last_ver_pos0_ - 1);','runner_.restore_verify_step(slot, keep_len - last_ver_pos0_ - 1);\n            check_rows(slot, keep_len);').replace('                last_ver_m_ = st.M;','                last_ver_m_ = st.M;\n                if (runner_.use_dspark) observe(st.slot_ids[0], st.pos[0], st.M);')
# Corrupt only the proposed draft, before normal target verification. Native target chooses the retained token.
s=s.replace('        return n;\n    }\n\n    int dspark_spec_step_greedy','        if (n && std::getenv("FORKSPEC_FORCE_REJECT")) out_draft_ids[0] = 17;\n        return n;\n    }\n\n    int dspark_spec_step_greedy')
p.write_text(s)
Path('research/forkspec/observer.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True),s.splitlines(True),'a/'+n,'b/'+n)))
