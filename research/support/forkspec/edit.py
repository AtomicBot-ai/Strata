from pathlib import Path
base=Path('.work/forkspec/source')
p=base/'engine/src/inkling2/metal/ink_metal_backend.mm'
s=p.read_text().replace('if (runner_.use_dspark || kv_dtype_ !=','if (kv_dtype_ !=',1)
s=s.replace('ink_metal::InkMetalRunner& runner;','InkMetalBackend& backend;\n            ink_metal::InkMetalRunner& runner;',1)
s=s.replace('explicit Saved(ink_metal::InkMetalRunner& r) : runner(r) {}','explicit Saved(InkMetalBackend& b) : backend(b), runner(b.runner_) {}')
s=s.replace('                for (const auto& slice : kv)','                backend.reset_slot(destination);\n                for (const auto& slice : kv)',1).replace('std::make_unique<Saved>(runner_)','std::make_unique<Saved>(*this)')
i=s.index('        for (int v = 0;',s.index('saved->payload_bytes = conv_bytes'))
j=s.index('        // Release',i)
s=s[:i]+'''        auto add = [&](uint8_t* base, size_t stride, size_t count) {
            if (!base || count > budget - saved->payload_bytes) return false;
            saved->kv.push_back({base, stride, saved->storage_size, count});
            saved->storage_size += count;
            saved->payload_bytes += count;
            return true;
        };
        auto add_kv = [&](auto& k, auto& v, int rows) {
            const size_t count = std::min(tokens, rows) * row_bytes;
            const size_t stride = rows * row_bytes;
            return add(k.template as<uint8_t>(), stride, count) &&
                   add(v.template as<uint8_t>(), stride, count);
        };
        for (int v = 0; v < c.n_visits; ++v)
            if (!add_kv(runner_.kv_k[v], runner_.kv_v[v], runner_.visit_kv_stride[v])) return nullptr;
        if (runner_.use_dspark) {
            for (int layer = 0; layer < 3; ++layer)
                if (!add_kv(runner_.dsp_ctx_k[layer], runner_.dsp_ctx_v[layer], runner_.dsp_kv_stride[layer]))
                    return nullptr;
            const size_t bytes = c.hidden * sizeof(float);
            if (!add(runner_.dsp_frnn_slot.as<uint8_t>(), bytes, bytes)) return nullptr;
        }
'''+s[j:]
name=next(line.split()[1] for line in s.splitlines() if line.startswith('class ') and 'InkBackend' in line)
s=s.replace('InkMetalBackend&',name+'&')
p.write_text(s)
p=base/'engine/src/inkling2/ink_serve.h'
s=p.read_text().replace('const bool state_enabled = snapshot_mib && !use_dspark', '''const char* fork_env = std::getenv("TURBINE_FORK_DSPARK");
    const bool fork_dspark = use_dspark && fork_env && std::string(fork_env) == "1";
    const bool state_enabled = snapshot_mib && (!use_dspark || fork_dspark)''').replace('ckpt_key=1 native_fork=%d"', 'ckpt_key=1 native_fork=%d fork_dspark=%d"').replace('int(state_enabled));','int(state_enabled), int(state_enabled && fork_dspark));',1)
# Scope greedy to explicit restore with compatible prefix; disallow sampled source save, including after invalid admissions.
s=s.replace('    bool shared_pending = false;', '    bool fork_restored = false;\n    bool shared_pending = false;')
s=s.replace('        rq.active = true;','''        if (state_enabled && fork_dspark && rq.fork_restored &&
            (!pg.s.greedy() || pg.s.penalties())) {
            err = "DSpark fork requires greedy generation without penalties";
            return false;
        }
        rq.active = true;''',1)
s=s.replace('        rq.prefill_pos = reuse;', '        rq.fork_restored = false;\n        rq.prefill_pos = reuse;',1)
s=s.replace('                    const size_t budget =','''                    if (fork_dspark && (!rq.s.greedy() || rq.s.penalties())) {
                        proto("ERR DSpark fork requires greedy generation without penalties"); return true;
                    }
                    const size_t budget =''',1)
s=s.replace('                    rq.cached_prefix.swap(ids);','                    rq.cached_prefix.swap(ids);\n                    rq.fork_restored = fork_dspark;')
p.write_text(s)
p=base/'terminal/serve/server.py'
s=p.read_text().replace('{"native_fork": enabled, "backend": state.family if enabled else None,','''{"native_fork": enabled, "fork_dspark": enabled and
                                     str(svc.engine.info.get("fork_dspark")) == "1", "backend": state.family if enabled else None,''')
p.write_text(s)
